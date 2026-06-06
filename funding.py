"""
Funding rate + open interest monitoring for the mean-reversion edge.

WHY THIS EXISTS
---------------
The 1h Bollinger-fade edge was validated on 12 months of OHLCV data and yields
+28% / year. But OHLCV has no information about *positioning* — who is crowded
long vs short. On perpetual futures, two derivatives-only signals carry real,
documented predictive value for mean reversion:

  * Funding rate  — periodic payment between longs and shorts. Extreme funding
    means one side is crowded and paying up to hold; that crowd is fuel for a
    squeeze in the OTHER direction.
  * Open interest — total open contracts. Falling OI into a price extreme =
    positions being liquidated/closed (capitulation, reverts). Rising OI into
    an extreme = fresh money chasing the move (trend continuation risk).

These are NOT in our historical CSVs, so they cannot be backtested here. This
module therefore ships **disabled by default** and runs in "monitor" mode first:
it logs funding+OI alongside every signal so that after a few weeks of paper
trading you have a real dataset to validate whether they add edge BEFORE letting
them affect trades.

THE THEORY (how funding aligns with a mean-reversion fade)
----------------------------------------------------------
We FADE the move. Direction +1 = price closed below the lower band, we go long
(betting on a bounce). Direction -1 = price above upper band, we go short.

  Long fade (price dumped):
    funding very NEGATIVE  -> shorts are crowded/aggressive -> squeeze UP fuel
                              -> CONFIRMS our long  (boost)
    funding very POSITIVE  -> longs already crowded on a dump = falling knife
                              -> CONTRARY  (caution / skip in filter mode)

  Short fade (price pumped):
    funding very POSITIVE  -> longs crowded/aggressive -> squeeze DOWN fuel
                              -> CONFIRMS our short (boost)
    funding very NEGATIVE  -> shorts already crowded on a pump
                              -> CONTRARY  (caution / skip in filter mode)

Open interest is used as a secondary read: OI dropping over the recent window
into the extreme supports the reversion thesis (deleveraging).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FundingSnapshot:
    """A point-in-time read of perp positioning metrics."""
    funding_rate: float          # current funding rate (fraction per interval, e.g. 0.0001 = 0.01%)
    open_interest: float         # open interest in contracts/USD (exchange-dependent units)
    next_funding_ts: Optional[int]  # ms timestamp of next funding, if provided
    timestamp: int               # ms when this snapshot was taken

    @property
    def funding_pct(self) -> float:
        """Funding as a percent for human-readable logs."""
        return self.funding_rate * 100.0


@dataclass
class FundingAssessment:
    """The verdict for a given trade direction and funding snapshot."""
    aligned: bool            # funding confirms the fade direction
    contrary: bool           # funding opposes the fade (crowd already on our side of a knife)
    extreme: bool            # |funding| exceeded the extreme threshold
    oi_falling: bool         # open interest dropped over the recent window (deleveraging)
    bias: float              # multiplier in [min_mult, max_mult] for confidence/size
    reason: str

    @property
    def should_skip(self) -> bool:
        """In filter mode, skip only the clearly contrarian-extreme setups."""
        return self.contrary and self.extreme


class FundingMonitor:
    """Fetches and evaluates funding rate + open interest for a symbol.

    Stateless w.r.t. trading; safe to call on every candle close. Results are
    cached for `cache_seconds` to avoid hammering the REST API (funding only
    changes every 8h, OI drifts slowly).
    """

    def __init__(
        self,
        exchange,
        symbol: str,
        *,
        enabled: bool = False,
        mode: str = "monitor",            # "monitor" (log only) | "filter" (can skip) | "boost"
        extreme_threshold: float = 0.0005,  # 0.05% per interval = crowded
        max_mult: float = 1.15,           # confidence boost when aligned+extreme
        min_mult: float = 0.85,           # confidence cut when contrary (boost mode)
        cache_seconds: float = 120.0,
        oi_window: int = 6,               # snapshots to keep for OI trend
    ):
        self._exchange = exchange
        self._symbol = symbol
        self.enabled = enabled
        self.mode = mode
        self._extreme = extreme_threshold
        self._max_mult = max_mult
        self._min_mult = min_mult
        self._cache_seconds = cache_seconds
        self._cache: Optional[FundingSnapshot] = None
        self._cache_ts: float = 0.0
        self._oi_history: deque[float] = deque(maxlen=oi_window)

    # -- data fetch ---------------------------------------------------------

    def _ccxt(self):
        """Return the underlying ccxt exchange, unwrapping PaperExchange."""
        ex = getattr(self._exchange, "_exchange", None)        # LiveExchange
        if ex is not None:
            return ex
        return getattr(self._exchange, "_rest_exchange", None)  # PaperExchange

    async def fetch(self) -> Optional[FundingSnapshot]:
        """Fetch a fresh snapshot (cached). Returns None if unavailable."""
        now = time.time()
        if self._cache is not None and (now - self._cache_ts) < self._cache_seconds:
            return self._cache

        ex = self._ccxt()
        if ex is None:
            return None

        funding_rate = 0.0
        next_ts: Optional[int] = None
        open_interest = 0.0

        try:
            fr = await ex.fetch_funding_rate(self._symbol)
            funding_rate = float(fr.get("fundingRate") or 0.0)
            next_ts = fr.get("fundingTimestamp") or fr.get("nextFundingTimestamp")
        except Exception as e:
            logger.debug("fetch_funding_rate failed: %s", e)

        try:
            oi = await ex.fetch_open_interest(self._symbol)
            open_interest = float(
                oi.get("openInterestAmount")
                or oi.get("openInterestValue")
                or oi.get("openInterest")
                or 0.0
            )
        except Exception as e:
            logger.debug("fetch_open_interest failed: %s", e)

        snap = FundingSnapshot(
            funding_rate=funding_rate,
            open_interest=open_interest,
            next_funding_ts=int(next_ts) if next_ts else None,
            timestamp=int(now * 1000),
        )
        if open_interest > 0:
            self._oi_history.append(open_interest)
        self._cache = snap
        self._cache_ts = now
        return snap

    # -- evaluation ---------------------------------------------------------

    def _oi_falling(self) -> bool:
        """True if open interest trended down over the stored window."""
        if len(self._oi_history) < 3:
            return False
        first = self._oi_history[0]
        last = self._oi_history[-1]
        return first > 0 and (last - first) / first < -0.01  # >1% drop

    def evaluate(self, direction: int, snap: Optional[FundingSnapshot]) -> FundingAssessment:
        """Score a snapshot against a fade direction (+1 long, -1 short)."""
        if snap is None or direction == 0:
            return FundingAssessment(False, False, False, False, 1.0, "no funding data")

        fr = snap.funding_rate
        extreme = abs(fr) >= self._extreme

        # Aligned = funding sits on the side of the move we are fading.
        #   long fade  (+1): want negative funding (shorts crowded)
        #   short fade (-1): want positive funding (longs crowded)
        if direction == 1:
            aligned = fr < 0
            contrary = fr > 0
        else:
            aligned = fr > 0
            contrary = fr < 0

        oi_falling = self._oi_falling()

        # Bias multiplier: only nudge, never dominate the validated edge.
        bias = 1.0
        if aligned and extreme:
            bias = self._max_mult
            if oi_falling:
                bias = self._max_mult  # already capped; deleveraging confirms
        elif contrary and extreme:
            bias = self._min_mult

        reason = (
            f"funding={snap.funding_pct:+.4f}% "
            f"({'aligned' if aligned else 'contrary' if contrary else 'neutral'}"
            f"{', extreme' if extreme else ''}"
            f"{', OI falling' if oi_falling else ''})"
        )
        return FundingAssessment(aligned, contrary, extreme, oi_falling, bias, reason)
