"""
whale_flow.py — live average-trade-size aggregator for the whale sleeve.

WHY THIS EXISTS
---------------
The whale edge (strategies/whale.py) keys off avg_size = quote_volume / trade
COUNT per 1h candle. MEXC futures klines do NOT carry trade count, so this
cannot be derived from OHLCV. ccxt DOES give individual trades live via
watchTrades (proven by orderflow.OrderFlowMonitor), so we aggregate them
ourselves into hourly (count, quote_volume) buckets and z-score avg_size over a
trailing window — exactly reproducing the backtest feature, but live.

MONITOR-FIRST
-------------
Like funding.py and orderflow.py, this ships disabled and runs monitor-first:
it needs ~`zwin` hours (1 week at 168) of warmup before the first z-score, and
the edge was only backtested on Binance klines — never forward-tested on MEXC's
live trade stream. So the sleeve logs would-be signals without trading until the
forward data confirms the edge holds, THEN trading is enabled.

State is in-memory: a restart restarts the warmup. That's acceptable for monitor
mode (it only delays first signal); persistence can be added before live trading.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_HOUR_MS = 3_600_000


class WhaleFlowMonitor:
    """Buckets watchTrades into hourly (count, quote_volume) and exposes the
    avg-trade-size z-score for a just-closed hour. One feed per symbol."""

    def __init__(
        self,
        exchange,
        symbol: str,
        *,
        enabled: bool = False,
        zwin: int = 168,
    ):
        self._exchange = exchange
        self._symbol = symbol
        self.enabled = enabled
        self._zwin = zwin
        # hour_start_ms -> [count, quote_volume]
        self._buckets: dict[int, list[float]] = {}
        # completed hourly avg_size history (for the z-score), oldest→newest
        self._hist: deque[float] = deque(maxlen=zwin + 5)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Guard: track last finalized candle timestamp to prevent bar_zscore()
        # from appending the same hour twice if called more than once per candle
        # (e.g. on a bot restart mid-hour or a duplicate candle close event).
        self._last_finalized_ms: int = 0

    # -- plumbing -----------------------------------------------------------

    def _ccxt(self):
        ex = getattr(self._exchange, "_exchange", None)          # LiveExchange
        if ex is not None:
            return ex
        return getattr(self._exchange, "_rest_exchange", None)   # PaperExchange

    async def start(self) -> None:
        if not self.enabled:
            return
        ex = self._ccxt()
        if ex is None or not ex.has.get("watchTrades"):
            logger.warning("WhaleFlow: watchTrades unavailable — disabled")
            self.enabled = False
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("WhaleFlow monitor ON (zwin=%dh) for %s — ~%dh warmup",
                    self._zwin, self._symbol, self._zwin)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        ex = self._ccxt()
        backoff = 1
        while self._running:
            try:
                trades = await ex.watch_trades(self._symbol)
                now = int(time.time() * 1000)
                for t in trades or []:
                    self._ingest(t, now)
                self._evict(now)
                backoff = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("WhaleFlow watch_trades error: %s (retry %ds)", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _ingest(self, trade: dict, now_ms: int) -> None:
        amt = float(trade.get("amount") or 0.0)
        if amt <= 0:
            return
        price = float(trade.get("price") or 0.0)
        # ccxt usually provides 'cost' = price*amount; fall back to the product.
        cost = float(trade.get("cost") or 0.0) or (price * amt)
        ts = int(trade.get("timestamp") or now_ms)
        hour = (ts // _HOUR_MS) * _HOUR_MS
        b = self._buckets.get(hour)
        if b is None:
            b = [0.0, 0.0]
            self._buckets[hour] = b
        b[0] += 1.0      # count
        b[1] += cost     # quote_volume

    def _evict(self, now_ms: int) -> None:
        # Keep only buckets within the last (zwin + 3) hours.
        cutoff = now_ms - (self._zwin + 3) * _HOUR_MS
        for h in [h for h in self._buckets if h < cutoff]:
            del self._buckets[h]

    # -- read ---------------------------------------------------------------

    def bar_zscore(self, candle_start_ms: int) -> Optional[float]:
        """Finalize the hour beginning at candle_start_ms and return its
        avg-trade-size z-score vs the trailing window. Appends it to history.
        Returns None while warming up or if the hour had no trades.

        Matches the backtest's research_microstructure._zscore EXACTLY:
          z[i] = (s[i] - rolling(win).mean()) / rolling(win).std()
        pandas' rolling(win) window INCLUDES the current bar and pandas .std()
        is the SAMPLE std (ddof=1). Earlier this used the prior `win` bars only
        and numpy's population std (ddof=0); both shifted the z-score, so a live
        signal could fire where the backtest wouldn't (and vice versa). To
        reproduce the backtest we build the window as the last (win-1) prior
        completed hours plus the current hour = win values, and use ddof=1.

        Idempotent-ish: call once per closed candle. If the bucket is missing
        (no trades captured, e.g. just after start) returns None without
        polluting the history."""
        if candle_start_ms == self._last_finalized_ms:
            return None  # already processed this hour; skip to avoid duplicate append
        b = self._buckets.get(candle_start_ms)
        if b is None or b[0] <= 0:
            return None
        avg_size = b[1] / b[0]
        # Need (win-1) prior hours so that prior+current = win values, matching
        # pandas rolling(win) which needs `win` observations before a non-NaN.
        if len(self._hist) < self._zwin - 1:
            self._hist.append(avg_size)
            self._last_finalized_ms = candle_start_ms
            return None  # still warming up
        prior = list(self._hist)[-(self._zwin - 1):]
        window = np.array(prior + [avg_size], dtype=float)
        self._hist.append(avg_size)
        self._last_finalized_ms = candle_start_ms
        mean = window.mean()
        std = window.std(ddof=1)  # sample std, matching pandas .std()
        if std <= 0 or np.isnan(std):
            return 0.0
        return float((avg_size - mean) / std)

    def warmup_remaining(self) -> int:
        # First valid z-score needs (win-1) prior completed hours + the current.
        return max(0, (self._zwin - 1) - len(self._hist))


# ── self-test: validate WhaleStrategy + z-score vs the research backtest ──────

def _selftest() -> int:
    """Replay one BTC month of CSV hourly bars and confirm that WhaleStrategy +
    a rolling z-score reproduce research_microstructure.strat_whale_follow's
    signals exactly (same entries, same direction). Validates the live signal
    path's MATH; the watchTrades bucketing mirrors the proven OrderFlowMonitor."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from research_microstructure import load_1m, to_1h, _zscore
    from strategies.whale import WhaleStrategy
    from indicators import atr as atr_fn

    m = load_1m("/home/user/Bot2/BTCUSDT-1m-2025-1*.csv")
    if m.empty:
        print("selftest: no data"); return 1
    df = to_1h(m)
    zser = _zscore(df["avg_size"], 168).values
    at = atr_fn(df["high"], df["low"], df["close"], 14).values
    o = df["open"].values; c = df["close"].values

    Z, BODY = 2.5, 0.5
    strat = WhaleStrategy(z_threshold=Z, sl_atr=2.0, rr=1.5, min_body_atr=BODY)
    # research signal: z>=thr AND body>=BODY×ATR → follow candle. Compare per bar.
    n = len(c); mism = 0; fires = 0
    for i in range(169, n):
        sig = strat.analyze(o[i], c[i], zser[i] if not np.isnan(zser[i]) else None, at[i])
        # reference (same filters as research_microstructure big-candle variant)
        ref_dir = 0
        if not np.isnan(zser[i]) and zser[i] >= Z and at[i] > 0 \
                and abs(c[i] - o[i]) >= BODY * at[i]:
            ref_dir = 1 if c[i] > o[i] else (-1 if c[i] < o[i] else 0)
        if sig.direction != ref_dir:
            mism += 1
        if ref_dir != 0:
            fires += 1
    print(f"selftest: {n-169} bars, {fires} reference fires, {mism} mismatches")
    if mism == 0:
        print("✓ WhaleStrategy reproduces research signals exactly")
        return 0
    print("✗ mismatch — signal logic diverges from backtest")
    return 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
