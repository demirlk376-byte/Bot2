from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional

import pandas as pd

from config import StrategyConfig

logger = logging.getLogger(__name__)

TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
}


@dataclass
class Candle:
    timestamp: int  # Unix ms open time
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


class CandleBuffer:
    def __init__(self, symbol: str, timeframe: str, maxlen: int = 200):
        self.symbol = symbol
        self.timeframe = timeframe
        self._buf: deque[Candle] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def update(self, candle: Candle) -> bool:
        async with self._lock:
            if not candle.is_closed:
                return False
            if self._buf and self._buf[-1].timestamp == candle.timestamp:
                self._buf[-1] = candle
                return False
            self._buf.append(candle)
            return True

    def to_dataframe(self) -> pd.DataFrame:
        if not self._buf:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        rows = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in self._buf
        ]
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["timestamp"], unit="ms")
        df.drop(columns=["timestamp"], inplace=True)
        return df

    def latest_close(self) -> float:
        return self._buf[-1].close if self._buf else 0.0

    def size(self) -> int:
        return len(self._buf)


def _parse_ohlcv(raw: list) -> Candle:
    return Candle(
        timestamp=int(raw[0]),
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        volume=float(raw[5]),
        is_closed=True,
    )


class DataManager:
    REST_POLL_INTERVAL = 30  # seconds for REST candle reconciliation

    def __init__(self, exchange, config: StrategyConfig, symbol: str):
        self._exchange = exchange
        self._config = config
        self._symbol = symbol
        self._buffers: dict[str, CandleBuffer] = {
            config.primary_tf: CandleBuffer(symbol, config.primary_tf),
            config.confirm_tf: CandleBuffer(symbol, config.confirm_tf),
        }
        self._callbacks: dict[str, list[Callable[[Candle], Awaitable[None]]]] = {
            config.primary_tf: [],
            config.confirm_tf: [],
        }
        self._current_price: float = 0.0
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._last_closed_ts: dict[str, int] = {}

    async def initialize(self) -> None:
        # _last_closed_ts tracks the last CLOSED candle per timeframe so close
        # callbacks fire exactly once per close (never on the forming candle).
        for tf, buf in self._buffers.items():
            try:
                raw = await self._exchange.fetch_ohlcv(
                    self._symbol, tf, since=None, limit=200
                )
                # ccxt returns the still-forming candle as the LAST element.
                # Exclude it so the analysis buffer holds only CLOSED candles.
                closed_rows = raw[:-1] if len(raw) > 1 else raw
                for row in closed_rows:
                    candle = _parse_ohlcv(row)
                    await buf.update(candle)
                if closed_rows:
                    self._last_closed_ts[tf] = int(closed_rows[-1][0])
                logger.info("Loaded %d closed candles for %s %s",
                            buf.size(), self._symbol, tf)
            except Exception as e:
                logger.error("Failed to load initial candles %s %s: %s", self._symbol, tf, e)

        if self._buffers[self._config.primary_tf].size() > 0:
            self._current_price = self._buffers[self._config.primary_tf].latest_close()

    def _spawn(self, coro, name: str) -> asyncio.Task:
        """Create a feed task with a done-callback so a silent death (the feed
        loop raising and the exception never being retrieved) is logged loudly
        instead of leaving the coin with a frozen candle buffer unnoticed."""
        task = asyncio.create_task(coro, name=name)

        def _done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.critical("Feed task '%s' CRASHED: %r — %s feed is now DEAD",
                                name, exc, self._symbol)
            elif not self._stop_event.is_set():
                logger.error("Feed task '%s' exited unexpectedly — %s feed stalled",
                             name, self._symbol)

        task.add_done_callback(_done)
        return task

    async def start_feeds(self) -> None:
        self._tasks.append(self._spawn(
            self._ticker_loop(), f"ticker:{self._symbol}"))
        self._tasks.append(self._spawn(
            self._rest_poll_loop(self._config.primary_tf),
            f"poll:{self._symbol}:{self._config.primary_tf}"))
        self._tasks.append(self._spawn(
            self._rest_poll_loop(self._config.confirm_tf),
            f"poll:{self._symbol}:{self._config.confirm_tf}"))

    async def stop(self) -> None:
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()

    async def _ticker_loop(self) -> None:
        backoff = 1
        while not self._stop_event.is_set():
            try:
                ticker = await self._exchange.watch_ticker(self._symbol)
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price > 0:
                    self._current_price = price
                    if hasattr(self._exchange, "update_price"):
                        # Pass the symbol so a shared PaperExchange keeps a
                        # separate price per coin (multi-coin correctness).
                        await self._exchange.update_price(price, self._symbol)
                    # Tick-level SL/TP: exit within seconds of price touching the
                    # stop, not at the next candle close (paper mode).
                    if hasattr(self._exchange, "check_sl_tp_tick"):
                        await self._exchange.check_sl_tp_tick(self._symbol, price)
                backoff = 1
            except Exception as e:
                logger.warning("Ticker feed error: %s (retry in %ds)", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _rest_poll_loop(self, timeframe: str) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self.REST_POLL_INTERVAL)
            try:
                await self._poll_once(timeframe)
            except Exception as e:
                logger.warning("REST poll error %s %s: %s", self._symbol, timeframe, e)

    async def _poll_once(self, timeframe: str) -> None:
        """Fetch latest candles and fire a close callback for newly-closed candles.
        The LAST row from fetch_ohlcv is the still-forming candle and is never
        analyzed or fired on; everything before it is closed.

        limit=50 (not 3) so that after a network outage or pause longer than a
        couple of candles we still see every closed candle since we last polled.
        We backfill the buffer with ALL missed closed candles (so indicators are
        computed on a complete series), but fire the close callback only for the
        MOST RECENT one — replaying stale intermediate candles could open trades
        on signals that are already hours old."""
        buf = self._buffers[timeframe]
        raw = await self._exchange.fetch_ohlcv(
            self._symbol, timeframe, since=None, limit=50
        )
        if not raw:
            return
        closed_rows = raw[:-1] if len(raw) > 1 else []
        last_ts = self._last_closed_ts.get(timeframe, 0)
        new_candles = []
        for row in closed_rows:
            candle = _parse_ohlcv(row)
            if candle.timestamp > last_ts:
                new_candles.append(candle)
        if not new_candles:
            return
        for candle in new_candles:
            await buf.update(candle)
            self._last_closed_ts[timeframe] = candle.timestamp
        await self._fire_callbacks(timeframe, new_candles[-1])

    async def _fire_callbacks(self, timeframe: str, candle: Candle) -> None:
        for cb in self._callbacks.get(timeframe, []):
            try:
                await cb(candle)
            except Exception as e:
                logger.error("Callback error: %s", e)

    def subscribe_candle_close(
        self, timeframe: str, callback: Callable[[Candle], Awaitable[None]]
    ) -> None:
        if timeframe not in self._callbacks:
            self._callbacks[timeframe] = []
        self._callbacks[timeframe].append(callback)

    async def get_candles(self, timeframe: str, n: int = 100) -> pd.DataFrame:
        buf = self._buffers.get(timeframe)
        if buf is None:
            return pd.DataFrame()
        df = buf.to_dataframe()
        return df.tail(n)

    async def get_current_price(self) -> float:
        return self._current_price

    def staleness_seconds(self) -> float:
        """Seconds elapsed since the last CLOSED primary-tf candle was recorded,
        beyond the timeframe interval. ~0 under normal operation; grows without
        bound if the REST poll feed dies (network down, exchange hiccup). The
        heartbeat uses this to detect a silently stalled feed."""
        import time
        tf = self._config.primary_tf
        last_ts = self._last_closed_ts.get(tf, 0)
        if last_ts <= 0:
            # No candle ever recorded → the feed never came up. Report a large
            # staleness (not 0/"healthy") so the heartbeat flags it instead of
            # silently masking a coin whose feed failed to initialize.
            return 1e9
        tf_secs = TIMEFRAME_SECONDS.get(tf, 60)
        now_ms = time.time() * 1000
        age_secs = (now_ms - last_ts) / 1000.0
        return max(0.0, age_secs - tf_secs)
