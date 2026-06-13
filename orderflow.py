"""
Order-flow collector for the mean-reversion edge (LIVE-ONLY, monitor-first).

WHY THIS EXISTS
---------------
The 1h Bollinger-fade edge is validated on OHLCV. OHLCV tells us price and
total volume, but NOT *who* traded aggressively — the split between taker buys
(market orders lifting the ask) and taker sells (hitting the bid). That split,
the "order flow", is what desks read to time reversions:

  * Cumulative delta = Σ(taker_buy_vol) − Σ(taker_sell_vol) over a window.
    Into a price extreme, exhausting aggression on the side of the move is a
    classic reversion tell (the sellers who dumped have run out → bounce).
  * Depth imbalance = resting bid liquidity vs ask liquidity in the order book.
    A wall of bids under a dumped price supports a long fade.

THE DATA PROBLEM (why this is monitor-first, default OFF)
---------------------------------------------------------
ccxt gives us this LIVE (watchTrades + fetchOrderBook on MEXC), but there is
NO historical tick/trade data in our CSVs, so an order-flow rule CANNOT be
backtested — only forward-tested. research_orderflow_vwap.py tried a 1m
taker-buy proxy and found NO reliable edge, so we do not trade on order flow.

Instead this module ships disabled and, when enabled in "monitor" mode, simply
logs cumulative delta + depth imbalance alongside every 1h signal. After a few
weeks of paper trading that builds a dataset tied to OUR actual signals, which
we can then analyse to decide whether order flow adds edge BEFORE it is ever
allowed to affect a trade.

THE THEORY (how flow aligns with a mean-reversion fade)
-------------------------------------------------------
We FADE the move. direction +1 = price closed below the lower band → go long.
direction -1 = price closed above the upper band → go short.

  Long fade (price dumped):
    flow strongly SELL-dominant (negative delta) = aggressive sellers still
      in control → falling knife → CONTRARY (caution)
    flow turning BUY-dominant / sell exhaustion = capitulation done → CONFIRMS
  Short fade (price pumped):
    flow strongly BUY-dominant (positive delta) = buyers still chasing
      → CONTRARY
    flow turning SELL-dominant = buy exhaustion → CONFIRMS

Depth imbalance is a secondary read: resting liquidity stacked on the side we
fade toward (bids for a long, asks for a short) supports the reversion.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderFlowSnapshot:
    """A point-in-time read of taker-flow + book imbalance over the window."""
    delta: float           # taker_buy_vol − taker_sell_vol over the window (base units)
    buy_vol: float         # taker buy volume in the window
    sell_vol: float        # taker sell volume in the window
    trade_count: int       # number of trades seen in the window
    buy_ratio: float       # buy_vol / (buy_vol + sell_vol); 0.5 = balanced
    depth_imbalance: float # (bid_vol − ask_vol)/(bid_vol + ask_vol) top-N levels; >0 = bid-heavy
    timestamp: int         # ms when this snapshot was taken

    @property
    def delta_pct(self) -> float:
        """Signed delta as a fraction of total window volume (−1..+1)."""
        total = self.buy_vol + self.sell_vol
        return (self.delta / total) if total > 0 else 0.0


@dataclass
class OrderFlowAssessment:
    """Verdict for a fade direction against an order-flow snapshot."""
    aligned: bool      # flow supports the fade (aggression exhausting on the faded side)
    contrary: bool     # flow opposes the fade (aggression still driving the move)
    reason: str


class OrderFlowMonitor:
    """Maintains a rolling taker-delta window from watchTrades and reads book
    imbalance on demand. Trade-side is the TAKER side (ccxt `side` on a public
    trade = the aggressor). Default OFF; runs a single background feed for the
    primary symbol only, so it adds negligible load until enabled."""

    def __init__(
        self,
        exchange,
        symbol: str,
        *,
        enabled: bool = False,
        mode: str = "monitor",          # "monitor" only for now (no trading on flow)
        window_minutes: float = 15.0,   # rolling window for cumulative delta
        depth_levels: int = 20,         # order-book levels for imbalance
        depth_cache_seconds: float = 5.0,
    ):
        self._exchange = exchange
        self._symbol = symbol
        self.enabled = enabled
        self.mode = mode
        self._window_ms = int(window_minutes * 60_000)
        self._depth_levels = depth_levels
        self._depth_cache_seconds = depth_cache_seconds
        # Each entry: (ts_ms, signed_qty, qty). signed: +buy taker, −sell taker.
        self._trades: deque[tuple[int, float, float]] = deque()
        self._depth_cache: tuple[float, float] = (0.0, 0.0)  # (imbalance, ts)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # -- plumbing -----------------------------------------------------------

    def _ccxt(self):
        """Return the underlying ccxt exchange, unwrapping PaperExchange."""
        ex = getattr(self._exchange, "_exchange", None)         # LiveExchange
        if ex is not None:
            return ex
        return getattr(self._exchange, "_rest_exchange", None)  # PaperExchange

    async def start(self) -> None:
        if not self.enabled:
            return
        ex = self._ccxt()
        if ex is None or not ex.has.get("watchTrades"):
            logger.warning("OrderFlow: watchTrades unavailable — collector disabled")
            self.enabled = False
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "OrderFlow monitor ON (mode=%s, window=%.0fm) for %s",
            self.mode, self._window_ms / 60_000, self._symbol,
        )

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
                    amt = float(t.get("amount") or 0.0)
                    if amt <= 0:
                        continue
                    ts = int(t.get("timestamp") or now)
                    signed = amt if t.get("side") == "buy" else -amt
                    self._trades.append((ts, signed, amt))
                self._evict(now)
                backoff = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("OrderFlow watch_trades error: %s (retry %ds)", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _evict(self, now_ms: int) -> None:
        cutoff = now_ms - self._window_ms
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()

    # -- reads --------------------------------------------------------------

    async def _depth_imbalance(self) -> float:
        """Top-N order-book imbalance in [−1, +1]; >0 = more bid than ask
        liquidity. Cached briefly so it can be called on every signal cheaply."""
        now = time.time()
        if now - self._depth_cache[1] < self._depth_cache_seconds:
            return self._depth_cache[0]
        ex = self._ccxt()
        if ex is None or not ex.has.get("fetchOrderBook"):
            return 0.0
        try:
            ob = await ex.fetch_order_book(self._symbol, limit=self._depth_levels)
            bid_vol = sum(float(b[1]) for b in ob.get("bids", [])[: self._depth_levels])
            ask_vol = sum(float(a[1]) for a in ob.get("asks", [])[: self._depth_levels])
            total = bid_vol + ask_vol
            imb = (bid_vol - ask_vol) / total if total > 0 else 0.0
        except Exception as e:
            logger.debug("OrderFlow depth fetch failed: %s", e)
            imb = 0.0
        self._depth_cache = (imb, now)
        return imb

    async def snapshot(self) -> OrderFlowSnapshot:
        """Compute the current rolling delta + book imbalance. Cheap; safe to
        call on every candle close."""
        now = int(time.time() * 1000)
        self._evict(now)
        buy_vol = sum(amt for _, signed, amt in self._trades if signed > 0)
        sell_vol = sum(amt for _, signed, amt in self._trades if signed < 0)
        total = buy_vol + sell_vol
        imb = await self._depth_imbalance()
        return OrderFlowSnapshot(
            delta=buy_vol - sell_vol,
            buy_vol=buy_vol,
            sell_vol=sell_vol,
            trade_count=len(self._trades),
            buy_ratio=(buy_vol / total) if total > 0 else 0.5,
            depth_imbalance=imb,
            timestamp=now,
        )

    def evaluate(self, direction: int, snap: Optional[OrderFlowSnapshot]) -> OrderFlowAssessment:
        """Score a snapshot against a fade direction (+1 long, −1 short).
        Monitor-only: this is logged, never acted on, until forward-tested."""
        if snap is None or direction == 0 or snap.trade_count == 0:
            return OrderFlowAssessment(False, False, "no order-flow data")
        # delta_pct > 0 = buy-dominant aggression, < 0 = sell-dominant.
        d = snap.delta_pct
        if direction == 1:   # long fade: want sell aggression to be exhausting
            aligned = d > 0.1
            contrary = d < -0.3
        else:                # short fade: want buy aggression to be exhausting
            aligned = d < -0.1
            contrary = d > 0.3
        reason = (
            f"flow delta={d:+.0%} (buy_ratio={snap.buy_ratio:.0%}, "
            f"depth_imb={snap.depth_imbalance:+.0%}, n={snap.trade_count}) "
            f"{'aligned' if aligned else 'contrary' if contrary else 'neutral'}"
        )
        return OrderFlowAssessment(aligned, contrary, reason)
