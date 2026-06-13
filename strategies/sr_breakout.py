"""
Support/Resistance Breakout strategy — 1h, strong levels only.

EDGE (research_sr.py, BTC 12 months May 2025 – Apr 2026):
  lb80 touch3 SL=3.0×ATR RR=3.0: PF 1.72, WR 47%, +22.4%
                                  TR W45% +$1240 | TE W53% +$998  ← both positive
  DD: 4.2%  (best risk-adjusted of all sleeves: return/DD ≈ 5.3)

CRITICAL CONDITIONS (without these it loses money):
  • touch>=3: only levels touched 3+ times count. touch2 (weak levels) is noisy
    and goes negative out-of-sample.
  • Volume + body filter: raw breakouts (no filter) lose on every config.

LOGIC:
  • find_sr_levels over the last `lookback` 1h candles (clustered swing pts).
  • Bullish break: close > resistance + 0.2% AND previous close <= resistance.
  • Bearish break: close < support − 0.2% AND previous close >= support.
  • Confirm: volume spike (>1.5× avg) AND candle body ratio > 0.6.
  • SL = entry ∓ 3.0×ATR,  TP = entry ± 3.0 × (3.0×ATR)  (RR = 3.0).
  • Swing-style: uses the normal 48h max-hold (NOT the 6h day-trade window).

This is momentum (follow the break) — complementary to the BB mean-reversion
core (fade the extreme). In the cascade it fires only when BB stays neutral.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from indicators import find_sr_levels, is_volume_spike

DEFAULT_LOOKBACK = 80
DEFAULT_MIN_TOUCHES = 3
DEFAULT_SL_ATR = 3.0
DEFAULT_RR = 3.0
MIN_BREAK_PCT = 0.002    # 0.2% past the level — filters micro/false breaks
BODY_RATIO_MIN = 0.6


@dataclass
class SrBreakoutSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    broken_level: float = 0.0


class SrBreakoutStrategy:
    """S/R breakout on 1h candles. analyze() called on every 1h candle-close."""

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK,
        min_touches: int = DEFAULT_MIN_TOUCHES,
        sl_atr_mult: float = DEFAULT_SL_ATR,
        rr: float = DEFAULT_RR,
    ):
        self._lookback = lookback
        self._min_touches = min_touches
        self._sl_atr = sl_atr_mult
        self._rr = rr

    def analyze(self, df: pd.DataFrame, atr_val: float) -> SrBreakoutSignal:
        if df is None or len(df) < self._lookback + 5:
            return SrBreakoutSignal(0, 0.0, "insufficient data")
        if atr_val <= 0:
            return SrBreakoutSignal(0, 0.0, "ATR not available")

        window = df.iloc[-(self._lookback + 1):]
        levels = find_sr_levels(
            window, lookback=self._lookback, min_touches=self._min_touches
        )
        if not levels:
            return SrBreakoutSignal(0, 0.0, "no strong S/R levels")

        cur = float(df["close"].iloc[-1])
        prev = float(df["close"].iloc[-2])
        min_break = cur * MIN_BREAK_PCT

        direction = 0
        broken = 0.0
        for lvl in levels:
            lp = lvl.price
            if lvl.level_type == "resistance" and cur > lp + min_break and prev <= lp:
                direction = 1; broken = lp; break
            if lvl.level_type == "support" and cur < lp - min_break and prev >= lp:
                direction = -1; broken = lp; break
        if direction == 0:
            return SrBreakoutSignal(0, 0.0, "no breakout")

        # Volume spike confirmation (essential — raw breakouts lose).
        vol_spike = bool(
            is_volume_spike(df["volume"], 20, 1.5).iloc[-1]
        )
        if not vol_spike:
            return SrBreakoutSignal(0, 0.0, f"break {broken:.0f} but no volume spike")

        # Body ratio confirmation — reject indecisive (long-wick) breaks.
        candle = df.iloc[-1]
        crange = float(candle["high"] - candle["low"])
        body = abs(float(candle["close"] - candle["open"]))
        if crange <= 0 or body / crange <= BODY_RATIO_MIN:
            return SrBreakoutSignal(0, 0.0, f"break {broken:.0f} but weak body")

        sl_dist = self._sl_atr * atr_val
        entry = cur
        sl = entry - direction * sl_dist
        tp = entry + direction * self._rr * sl_dist
        side = "long" if direction == 1 else "short"
        return SrBreakoutSignal(
            direction=direction, strength=0.75,
            reason=f"S/R {side} break {broken:.0f} (vol+body confirmed)",
            sl_price=sl, tp_price=tp, broken_level=broken,
        )
