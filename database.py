from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import aiosqlite


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    sl_price: float
    tp_price: float
    entry_time: str
    is_paper: bool
    strategy_scores: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl_usdt: Optional[float] = None
    pnl_pct: Optional[float] = None
    exit_reason: Optional[str] = None
    fees_usdt: Optional[float] = None


@dataclass
class DailyStats:
    date: str
    starting_balance: float
    ending_balance: float
    total_trades: int
    winning_trades: int
    total_pnl_usdt: float
    max_drawdown: float
    is_paper: bool


@dataclass
class PerformanceSummary:
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl_usdt: float
    profit_factor: float
    max_drawdown: float


_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    quantity        REAL NOT NULL,
    sl_price        REAL NOT NULL,
    tp_price        REAL NOT NULL,
    entry_time      TEXT NOT NULL,
    exit_time       TEXT,
    pnl_usdt        REAL,
    pnl_pct         REAL,
    exit_reason     TEXT,
    strategy_scores TEXT,
    fees_usdt       REAL,
    is_paper        INTEGER NOT NULL
)
"""

_CREATE_DAILY = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date             TEXT PRIMARY KEY,
    starting_balance REAL,
    ending_balance   REAL,
    total_trades     INTEGER,
    winning_trades   INTEGER,
    total_pnl_usdt   REAL,
    max_drawdown     REAL,
    is_paper         INTEGER
)
"""

# Small key/value store for state that must survive restarts (e.g. the paper
# balance, which otherwise resets to the initial balance on every reboot).
_CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
)
"""


class Database:
    def __init__(self, db_path: str):
        self._path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        # One shared connection serves many concurrent coroutines (per-coin
        # candle handlers, reconciliation, max-hold, Telegram /close). Serialize
        # writes so one coroutine's commit can't flush another's half-written
        # statement, and so read-modify-write (add_deposit) stays atomic.
        self._wlock = asyncio.Lock()

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        # WAL improves reader/writer concurrency (dashboard reads while the
        # engine writes) and reduces "database is locked" stalls.
        try:
            await self._db.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        await self._db.execute(_CREATE_TRADES)
        await self._db.execute(_CREATE_DAILY)
        await self._db.execute(_CREATE_META)
        await self._db.commit()

    async def add_deposit(self, amount: float) -> float:
        """Record a capital deposit/withdrawal (negative = withdrawal) so the
        dashboard can separate added money from real trading profit. Returns the
        new cumulative deposit total. Survives restarts via the meta table."""
        async with self._wlock:
            new_total = await self.get_meta_float("total_deposits", 0.0) + amount
            await self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                ("total_deposits", str(new_total)),
            )
            await self._db.commit()
            return new_total

    async def set_meta(self, key: str, value: str) -> None:
        async with self._wlock:
            await self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value)
            )
            await self._db.commit()

    async def get_meta(self, key: str) -> Optional[str]:
        async with self._db.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def get_meta_float(self, key: str, default: float = 0.0) -> float:
        v = await self.get_meta(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    async def get_open_trades(self) -> list[TradeRecord]:
        """Trades with no exit yet — used to rebuild the in-memory portfolio
        after a restart so open positions are not orphaned."""
        async with self._db.execute(
            "SELECT * FROM trades WHERE exit_time IS NULL"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_trade(r) for r in rows]

    async def get_today_traded_slots(self, is_paper: bool | None = None) -> set[str]:
        """Strategy names that already entered a trade today (open or closed).
        Used on restart to re-populate per-strategy _traded_dates so one-per-day
        intraday strategies (ORB, Asia BO) don't re-fire after a bot restart.

        is_paper filters to the current run mode so a paper trade from earlier
        today can't suppress the real live ORB/Asia entry (or vice-versa)."""
        today = datetime.now(timezone.utc).date().isoformat()
        clause, params = _paper_clause(is_paper)
        async with self._db.execute(
            """SELECT DISTINCT json_extract(strategy_scores, '$.strategy')
               FROM trades WHERE entry_time LIKE ?""" + clause,
            (f"{today}%", *params),
        ) as cur:
            rows = await cur.fetchall()
        return {r[0] for r in rows if r[0]}

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log_trade_open(self, trade: TradeRecord) -> None:
        async with self._wlock:
            await self._db.execute(
                """INSERT INTO trades
                   (id, symbol, side, entry_price, quantity, sl_price, tp_price,
                    entry_time, strategy_scores, is_paper)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade.id, trade.symbol, trade.side, trade.entry_price,
                    trade.quantity, trade.sl_price, trade.tp_price,
                    trade.entry_time, json.dumps(trade.strategy_scores),
                    int(trade.is_paper),
                ),
            )
            await self._db.commit()

    async def log_trade_close(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: str,
        pnl_usdt: float,
        pnl_pct: float,
        exit_reason: str,
        fees_usdt: float = 0.0,
    ) -> None:
        async with self._wlock:
            await self._db.execute(
                """UPDATE trades
                   SET exit_price=?, exit_time=?, pnl_usdt=?, pnl_pct=?,
                       exit_reason=?, fees_usdt=?
                   WHERE id=?""",
                (exit_price, exit_time, pnl_usdt, pnl_pct, exit_reason, fees_usdt, trade_id),
            )
            await self._db.commit()

    async def get_daily_pnl(self, day: str, is_paper: bool | None = None) -> float:
        clause, params = _paper_clause(is_paper)
        async with self._db.execute(
            "SELECT COALESCE(SUM(pnl_usdt),0) FROM trades "
            "WHERE exit_time LIKE ? AND exit_time IS NOT NULL" + clause,
            (f"{day}%", *params),
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0

    async def get_all_trades(
        self, limit: int = 100, is_paper: bool | None = None
    ) -> list[TradeRecord]:
        clause, params = _paper_clause(is_paper, leading_where=True)
        async with self._db.execute(
            "SELECT * FROM trades" + clause + " ORDER BY entry_time DESC LIMIT ?",
            (*params, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_trade(r) for r in rows]

    async def upsert_daily_stats(self, stats: DailyStats) -> None:
        async with self._wlock:
            await self._db.execute(
                """INSERT OR REPLACE INTO daily_stats
                   (date, starting_balance, ending_balance, total_trades,
                    winning_trades, total_pnl_usdt, max_drawdown, is_paper)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    stats.date, stats.starting_balance, stats.ending_balance,
                    stats.total_trades, stats.winning_trades, stats.total_pnl_usdt,
                    stats.max_drawdown, int(stats.is_paper),
                ),
            )
            await self._db.commit()

    async def get_daily_starting_balance(self, day: str) -> Optional[float]:
        async with self._db.execute(
            "SELECT starting_balance FROM daily_stats WHERE date=?", (day,)
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else None

    async def get_strategy_breakdown(
        self, is_paper: bool | None = None
    ) -> list[dict]:
        """Per-strategy closed-trade stats for Telegram /strategy and dashboard."""
        clause, params = _paper_clause(is_paper)
        async with self._db.execute("""
            SELECT
                COALESCE(json_extract(strategy_scores, '$.strategy'), 'unknown') AS strategy,
                COUNT(*) AS total,
                SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(COALESCE(pnl_usdt, 0)) AS total_pnl
            FROM trades
            WHERE exit_time IS NOT NULL""" + clause + """
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """, params) as cur:
            rows = await cur.fetchall()
        return [
            {"strategy": r[0], "total": r[1], "win": r[2] or 0, "pnl": r[3] or 0.0}
            for r in rows
        ]

    async def get_coin_breakdown(self, is_paper: bool | None = None) -> list[dict]:
        """Per-coin closed-trade stats for the dashboard's coin panel."""
        clause, params = _paper_clause(is_paper)
        async with self._db.execute("""
            SELECT
                symbol,
                COUNT(*) AS total,
                SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(COALESCE(pnl_usdt, 0)) AS total_pnl
            FROM trades
            WHERE exit_time IS NOT NULL""" + clause + """
            GROUP BY symbol
            ORDER BY total_pnl DESC
        """, params) as cur:
            rows = await cur.fetchall()
        return [
            {"symbol": r[0], "total": r[1], "win": r[2] or 0, "pnl": r[3] or 0.0}
            for r in rows
        ]

    async def get_monthly_pnl(
        self, limit: int = 12, is_paper: bool | None = None
    ) -> list[dict]:
        """Realised PnL grouped by calendar month (newest last) for the bar chart."""
        clause, params = _paper_clause(is_paper)
        async with self._db.execute("""
            SELECT substr(exit_time, 1, 7) AS month,
                   SUM(COALESCE(pnl_usdt, 0)) AS pnl,
                   COUNT(*) AS n
            FROM trades
            WHERE exit_time IS NOT NULL""" + clause + """
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
        """, (*params, limit)) as cur:
            rows = await cur.fetchall()
        out = [{"month": r[0], "pnl": r[1] or 0.0, "n": r[2]} for r in rows]
        out.reverse()  # chronological for the chart
        return out

    async def get_equity_curve(
        self, initial_balance: float, is_paper: bool | None = None
    ) -> list[dict]:
        """Realised equity curve: initial balance + running sum of closed-trade
        PnL ordered by exit time. The first point anchors the starting balance so
        the chart always has a baseline even before any trade closes."""
        clause, params = _paper_clause(is_paper)
        async with self._db.execute("""
            SELECT exit_time, COALESCE(pnl_usdt, 0) AS pnl
            FROM trades
            WHERE exit_time IS NOT NULL""" + clause + """
            ORDER BY exit_time ASC
        """, params) as cur:
            rows = await cur.fetchall()
        eq = float(initial_balance)
        curve = [{"t": None, "eq": eq}]
        for r in rows:
            eq += float(r[1])
            curve.append({"t": r[0], "eq": eq})
        return curve

    async def get_performance_summary(
        self, is_paper: bool | None = None
    ) -> PerformanceSummary:
        clause, params = _paper_clause(is_paper)
        async with self._db.execute(
            "SELECT pnl_usdt FROM trades WHERE exit_time IS NOT NULL" + clause,
            params,
        ) as cur:
            rows = await cur.fetchall()

        pnls = [float(r[0]) for r in rows if r[0] is not None]
        if not pnls:
            return PerformanceSummary(0, 0, 0.0, 0.0, 0.0, 0.0)

        total = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            # Cap at 1.0: equity below zero means full loss of peak gain,
            # not negative DD (which is mathematically valid but misleading).
            dd = min((peak - equity) / peak, 1.0) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return PerformanceSummary(
            total_trades=total,
            winning_trades=wins,
            win_rate=wins / total if total > 0 else 0.0,
            total_pnl_usdt=sum(pnls),
            profit_factor=profit_factor,
            max_drawdown=max_dd,
        )


def _paper_clause(
    is_paper: bool | None, *, leading_where: bool = False
) -> tuple[str, tuple]:
    """Build an is_paper filter so the dashboard never mixes paper-test trades
    with live trades in the same DB. None → no filter (kept for Telegram and any
    caller that wants the full history). Returns (sql_fragment, params)."""
    if is_paper is None:
        return "", ()
    kw = " WHERE" if leading_where else " AND"
    return f"{kw} is_paper = ?", (1 if is_paper else 0,)


def _row_to_trade(row: aiosqlite.Row) -> TradeRecord:
    d = dict(row)
    d["is_paper"] = bool(d["is_paper"])
    d["strategy_scores"] = json.loads(d["strategy_scores"] or "{}")
    return TradeRecord(**d)
