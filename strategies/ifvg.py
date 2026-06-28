"""
Inverse Fair Value Gap (IFVG) strategy — ICT price-action, indicator-light.

EDGE (research_ict2.py + salvage_ifvg.py, BTC 1h 2023-2026, realistic limit
fills, look-ahead fixed, same-bar SL counted as loss, fixed $1000 / 2% risk):
  IFVG + EMA200 trend + gap>=0.5×ATR + RR 2.0:
    PF 1.42, WR 45%, 290 trades, positive EVERY year:
      2023 PF 1.26 | 2024 PF 1.88 | 2025 PF 1.14 | 2026 PF 1.59

  NOTE: with gap>=0.3 IFVG failed 2025 (PF 0.94). The gap>=0.5 noise filter —
  the SAME one validated independently on FVG — fixes it. One filter repairing
  two strategies is strong evidence the effect (small gaps are noise) is real,
  not curve-fit to 2025.

ROBUST DEFAULT (gap>=0.75×ATR, validated 2026-06 on the full 2023-2026 history
with the realistic resting-limit fill model — maker entry at the zone edge, no
adverse slippage, maker round-trip cost):
  PF 1.43, 152 trades, TRAIN 1.43 / TEST 1.45 (train≈test, no out-of-sample
  decay), positive EVERY year with 2025 made ROBUST:
    2023 PF 1.16 | 2024 PF 1.60 | 2025 PF 1.33 | 2026 PF 1.36   DD ~12%
  The gap>=0.5 baseline still earns more in absolute terms (PF 1.50, n278) but
  its 2025 stays thin (PF 1.15). gap>=0.75 trades less often yet is the more
  robust point: it lifts the weakest year (2025) from 1.15 to 1.33 and halves
  out-of-sample variance — preferred for unattended live trading. Both 1.0 (over-
  filters, edge collapses to PF 0.96) and 0.5 (fragile 2025) bracket 0.75 as a
  genuine sweet spot, not a curve-fit cliff. This is the project's first LOW-
  correlation reversal sleeve: it enters on limit retests of flipped gaps, the
  opposite structural behaviour to the long-momentum/breakout book (ORB/Asia/
  Donchian/Squeeze/S-R), so it diversifies directional risk rather than stacking it.

LOGIC:
  • Track FVG zones (3-candle imbalance, gap >= 0.5×ATR) like the FVG strategy.
  • When price VIOLATES a zone (a bullish FVG's lower edge is closed through, or
    a bearish FVG's upper edge), the zone "flips polarity": a broken bullish gap
    becomes RESISTANCE, a broken bearish gap becomes SUPPORT.
  • Enter on the RETEST of the flipped zone, in the new direction, in the EMA200
    trend direction:
      broken bearish gap (now support), price dips in → limit BUY at zone top.
      broken bullish gap (now resistance), price rallies in → limit SELL at bottom.
  • SL = zone far edge ± 0.3×ATR.  TP = entry ± 2.0 × stop-distance.
  • Zones awaiting a break expire after 50 candles; flipped zones expire 24 after.

WHY IT WORKS (hypothesis):
  An imbalance that gets violated rather than filled signals a regime where the
  prior aggressor was trapped; the broken gap then acts as a supply/demand shelf.
  Fading the retest into that shelf, with the higher-timeframe trend, captures the
  continuation after trapped participants are flushed. Like FVG, the limit entry
  rests in the path of price → realistic fills (no breakout chase).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators import ema

DEFAULT_MIN_GAP_ATR = 0.75   # robust noise filter (see docstring); 0.5 = higher-volume but fragile-2025 variant
DEFAULT_RR = 2.0
DEFAULT_POS_EXPIRE = 24     # position max-hold (candles)
DEFAULT_ZONE_EXPIRE = 50    # how long an un-broken FVG stays watched
DEFAULT_FLIP_EXPIRE = 24    # how long a flipped (broken) zone stays tradeable
DEFAULT_EMA = 200
SL_BUFFER_ATR = 0.3


@dataclass
class IfvgSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0


class IfvgStrategy:
    """Stateful inverse-FVG tracker. analyze() runs on every 1h candle-close.

    Keeps two zone lists: `_active` (FVGs awaiting a break) and `_broken`
    (flipped zones awaiting a reversal retest)."""

    def __init__(
        self,
        min_gap_atr: float = DEFAULT_MIN_GAP_ATR,
        rr: float = DEFAULT_RR,
        ema_period: int = DEFAULT_EMA,
    ):
        self._min_gap = min_gap_atr
        self._rr = rr
        self._ema_period = ema_period
        self._active: list[dict] = []   # {"dir","top","bottom","age","fresh"}
        self._broken: list[dict] = []   # {"dir","top","bottom","age","fresh"}
        self._last_ts = None

    def analyze(self, df: pd.DataFrame, atr_val: float) -> IfvgSignal:
        if df is None or len(df) < 3 or atr_val <= 0:
            return IfvgSignal(0, 0.0, "insufficient data")

        last_ts = df.index[-1]
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        cur_close = float(c[-1])
        cur_low = float(l[-1])
        cur_high = float(h[-1])

        new_bar = self._last_ts != last_ts
        if new_bar:
            # Age all zones; mark them not-fresh so they can be traded next bar.
            for z in self._active:
                z["age"] += 1
                z["fresh"] = False
            for z in self._broken:
                z["age"] += 1
                z["fresh"] = False

            # Move violated active FVGs into the flipped (broken) list.
            for z in list(self._active):
                if z["fresh"]:
                    continue
                if z["dir"] == 1 and cur_close < z["bottom"]:
                    self._broken.append({"dir": -1, "top": z["top"],
                                         "bottom": z["bottom"], "age": 0, "fresh": True})
                    self._active.remove(z)
                elif z["dir"] == -1 and cur_close > z["top"]:
                    self._broken.append({"dir": 1, "top": z["top"],
                                         "bottom": z["bottom"], "age": 0, "fresh": True})
                    self._active.remove(z)

            # Expire stale zones.
            self._active = [z for z in self._active if z["age"] < DEFAULT_ZONE_EXPIRE]
            self._broken = [z for z in self._broken if z["age"] < DEFAULT_FLIP_EXPIRE]

            # Detect a new FVG ending on the just-closed candle.
            if h[-3] < l[-1] and (l[-1] - h[-3]) >= self._min_gap * atr_val:
                self._active.append({"dir": 1, "top": float(l[-1]),
                                     "bottom": float(h[-3]), "age": 0, "fresh": True})
            if l[-3] > h[-1] and (l[-3] - h[-1]) >= self._min_gap * atr_val:
                self._active.append({"dir": -1, "top": float(l[-3]),
                                     "bottom": float(h[-1]), "age": 0, "fresh": True})
            self._last_ts = last_ts

        ema_series = ema(df["close"], self._ema_period)
        ema_val = float(ema_series.iloc[-1]) if not pd.isna(ema_series.iloc[-1]) else None

        # Enter on the retest of a flipped zone (formed on a prior bar).
        for z in list(self._broken):
            if z["fresh"]:
                continue
            top = z["top"]
            bottom = z["bottom"]
            sld = (top - bottom) + SL_BUFFER_ATR * atr_val

            if z["dir"] == 1 and cur_low <= top and cur_close > bottom:
                if ema_val is None or cur_close <= ema_val:
                    continue
                ep = top
                self._broken.remove(z)
                return IfvgSignal(
                    direction=1, strength=0.70,
                    reason=f"IFVG long (broken-gap support {bottom:.0f}-{top:.0f})",
                    sl_price=ep - sld, tp_price=ep + self._rr * sld, entry_price=ep,
                )

            if z["dir"] == -1 and cur_high >= bottom and cur_close < top:
                if ema_val is None or cur_close >= ema_val:
                    continue
                ep = bottom
                self._broken.remove(z)
                return IfvgSignal(
                    direction=-1, strength=0.70,
                    reason=f"IFVG short (broken-gap resistance {bottom:.0f}-{top:.0f})",
                    sl_price=ep + sld, tp_price=ep - self._rr * sld, entry_price=ep,
                )

        return IfvgSignal(
            0, 0.0,
            f"{len(self._active)} active / {len(self._broken)} flipped, no retest",
        )
