from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
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

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TRADES)
        await self._db.execute(_CREATE_DAILY)
        await self._db.execute(_CREATE_META)
        await self._db.commit()

    async def set_meta(self, key: str, value: str) -> None:
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

    async def get_open_trades(self) -> list[TradeRecord]:
        """Trades with no exit yet — used to rebuild the in-memory portfolio
        after a restart so open positions are not orphaned."""
        async with self._db.execute(
            "SELECT * FROM trades WHERE exit_time IS NULL"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_trade(r) for r in rows]

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log_trade_open(self, trade: TradeRecord) -> None:
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
        await self._db.execute(
            """UPDATE trades
               SET exit_price=?, exit_time=?, pnl_usdt=?, pnl_pct=?,
                   exit_reason=?, fees_usdt=?
               WHERE id=?""",
            (exit_price, exit_time, pnl_usdt, pnl_pct, exit_reason, fees_usdt, trade_id),
        )
        await self._db.commit()

    async def get_daily_pnl(self, day: str) -> float:
        async with self._db.execute(
            "SELECT COALESCE(SUM(pnl_usdt),0) FROM trades WHERE exit_time LIKE ? AND exit_time IS NOT NULL",
            (f"{day}%",),
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0

    async def get_all_trades(self, limit: int = 100) -> list[TradeRecord]:
        async with self._db.execute(
            "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_trade(r) for r in rows]

    async def upsert_daily_stats(self, stats: DailyStats) -> None:
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

    async def get_strategy_breakdown(self) -> list[dict]:
        """Per-strategy closed-trade stats for Telegram /strategy and dashboard."""
        async with self._db.execute("""
            SELECT
                COALESCE(json_extract(strategy_scores, '$.strategy'), 'unknown') AS strategy,
                COUNT(*) AS total,
                SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(COALESCE(pnl_usdt, 0)) AS total_pnl
            FROM trades
            WHERE exit_time IS NOT NULL
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """) as cur:
            rows = await cur.fetchall()
        return [
            {"strategy": r[0], "total": r[1], "win": r[2] or 0, "pnl": r[3] or 0.0}
            for r in rows
        ]

    async def get_performance_summary(self) -> PerformanceSummary:
        async with self._db.execute(
            "SELECT pnl_usdt FROM trades WHERE exit_time IS NOT NULL"
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
            dd = (peak - equity) / peak if peak > 0 else 0.0
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


def _row_to_trade(row: aiosqlite.Row) -> TradeRecord:
    d = dict(row)
    d["is_paper"] = bool(d["is_paper"])
    d["strategy_scores"] = json.loads(d["strategy_scores"] or "{}")
    return TradeRecord(**d)
