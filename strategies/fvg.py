"""
Fair Value Gap (FVG) strategy — ICT / price-action, indicator-light.

EDGE (research_ict.py + strengthen_fvg.py, BTC 1h 2023-2026, realistic limit
fills, look-ahead fixed, fixed $1000 / 2% risk):
  FVG + EMA200 trend + gap>=0.5×ATR + RR 2.5:
    PF 1.37, WR 40%, 646 trades, positive EVERY year:
      2023 PF 1.31 | 2024 PF 1.53 | 2025 PF 1.17 | 2026 PF 1.55

LOGIC:
  • A bullish FVG is a 3-candle imbalance: high[-3] < low[-1] leaves an unfilled
    gap (zone = [high[-3], low[-1]]). Bearish FVG is the mirror: low[-3] > high[-1].
  • Only "significant" gaps count: gap size >= 0.5 × ATR (small gaps are noise).
  • After the gap forms, we wait for price to RETURN into the zone (a retest) and
    enter a LIMIT in the gap-fill direction:
      bullish → limit BUY at the zone top (low[-3 candle]); price dips in, bounces.
      bearish → limit SELL at the zone bottom.
  • Trend filter: only longs when close > EMA200, only shorts when close < EMA200.
  • SL = zone far edge ± 0.3×ATR buffer.  TP = entry ± 2.5 × stop-distance.
  • A zone expires unused after 24 candles; one fill per zone.

WHY IT WORKS (hypothesis):
  A fast move that leaves an imbalance tends to be partially retraced as resting
  liquidity inside the gap gets filled; entering on that retrace, in the higher-
  timeframe trend direction, captures the continuation after the fill. Unlike a
  breakout chase, the limit entry rests in the path of price → realistic fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from indicators import ema

DEFAULT_MIN_GAP_ATR = 0.5
DEFAULT_RR = 2.5
DEFAULT_EXPIRE = 24
DEFAULT_EMA = 200
SL_BUFFER_ATR = 0.3


@dataclass
class FvgSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 – 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0


class FvgStrategy:
    """Stateful FVG tracker. analyze() is called on every 1h candle-close.

    Unlike ORB/Asia (one trade per day), FVG is continuous: it accumulates active
    gap zones and fires whenever price retests one in the trend direction.
    """

    def __init__(
        self,
        min_gap_atr: float = DEFAULT_MIN_GAP_ATR,
        rr: float = DEFAULT_RR,
        expire_bars: int = DEFAULT_EXPIRE,
        ema_period: int = DEFAULT_EMA,
    ):
        self._min_gap = min_gap_atr
        self._rr = rr
        self._expire = expire_bars
        self._ema_period = ema_period
        # Each zone: {"dir", "top", "bottom", "age", "fresh"}
        self._active: list[dict] = []
        self._last_ts = None

    def analyze(self, df: pd.DataFrame, atr_val: float) -> FvgSignal:
        if df is None or len(df) < 3 or atr_val <= 0:
            return FvgSignal(0, 0.0, "insufficient data")

        last_ts = df.index[-1]
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values

        # Only mutate zone state once per new candle (analyze may be called again
        # within the same bar by other code paths).
        new_bar = self._last_ts != last_ts
        if new_bar:
            # Outage/backfill guard (audit fix): the feed backfills ALL missed
            # closed candles after a gap but fires the close callback only for
            # the newest one. Zone state mutated once per callback would then
            # be stale — ages advance 1 instead of N and, worse, a zone break
            # that happened on an INTERMEDIATE bar is never seen, leaving a
            # flipped level tradeable in the wrong direction. If the previous
            # processed bar is not this bar's immediate predecessor, reset all
            # zone state — conservatively missing a few post-outage trades
            # instead of ever trading a corrupted zone map.
            if (self._last_ts is not None and len(df.index) >= 2
                    and df.index[-2] != self._last_ts):
                self._active.clear()
            # Age existing zones, then drop expired ones.
            for z in self._active:
                z["age"] += 1
                z["fresh"] = False
            self._active = [z for z in self._active if z["age"] < self._expire]

            # Detect a new FVG ending on the just-closed candle (candles -3,-2,-1).
            if h[-3] < l[-1]:
                gap = l[-1] - h[-3]
                if gap >= self._min_gap * atr_val:
                    self._active.append(
                        {"dir": 1, "top": float(l[-1]), "bottom": float(h[-3]),
                         "age": 0, "fresh": True}
                    )
            if l[-3] > h[-1]:
                gap = l[-3] - h[-1]
                if gap >= self._min_gap * atr_val:
                    self._active.append(
                        {"dir": -1, "top": float(l[-3]), "bottom": float(h[-1]),
                         "age": 0, "fresh": True}
                    )
            self._last_ts = last_ts

        # Trend filter (EMA200). Needs a long enough buffer; if NaN, skip trades.
        ema_series = ema(df["close"], self._ema_period)
        ema_val = float(ema_series.iloc[-1]) if not pd.isna(ema_series.iloc[-1]) else None
        cur_close = float(c[-1])
        cur_low = float(l[-1])
        cur_high = float(h[-1])

        # Look for the first active zone (formed on a PRIOR bar) that price retests.
        for z in list(self._active):
            if z["fresh"]:
                continue  # formed this bar — cannot enter same candle (look-ahead)
            top = z["top"]
            bottom = z["bottom"]
            sld = (top - bottom) + SL_BUFFER_ATR * atr_val

            if z["dir"] == 1 and cur_low <= top and cur_close > bottom:
                if ema_val is None or cur_close <= ema_val:
                    continue  # trend filter: only longs above EMA200
                ep = top
                sl = ep - sld
                tp = ep + self._rr * sld
                self._active.remove(z)
                return FvgSignal(
                    direction=1, strength=0.70,
                    reason=f"FVG long retest {bottom:.0f}-{top:.0f}",
                    sl_price=sl, tp_price=tp, entry_price=ep,
                )

            if z["dir"] == -1 and cur_high >= bottom and cur_close < top:
                if ema_val is None or cur_close >= ema_val:
                    continue  # trend filter: only shorts below EMA200
                ep = bottom
                sl = ep + sld
                tp = ep - self._rr * sld
                self._active.remove(z)
                return FvgSignal(
                    direction=-1, strength=0.70,
                    reason=f"FVG short retest {bottom:.0f}-{top:.0f}",
                    sl_price=sl, tp_price=tp, entry_price=ep,
                )

        return FvgSignal(0, 0.0, f"{len(self._active)} active FVG, no retest")
