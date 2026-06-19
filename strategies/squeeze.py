"""
Volatility Squeeze strategy — BB tightens inside Keltner Channel, then explodes.

EDGE (research_squeeze.py, BTC 1h 2023-2026, honest TRAIN/TEST + year-by-year):
  MTF (1h squeeze + 4h trend filter): KC1.5, min_squeeze=5, SL=2.0×ATR, RR=2.5:
    PF 1.31, WR 43%, 240 trades, POSITIVE EVERY YEAR:
      2023 PF 1.31 | 2024 PF 1.46 | 2025 PF 1.15 | 2026 PF 1.34
    Max DD: 18%  |  26/36 months profitable  |  TR≈TE (1.30 vs 1.34 — no test inflation)

LOGIC:
  Squeeze detection: Bollinger Bands (20, 2.0) contract inside Keltner Channel
  (EMA20 ± 1.5×ATR). When BB upper < KC upper AND BB lower > KC lower, the market
  is coiling — low volatility accumulating energy. After >= 5 consecutive bars in
  squeeze, when the BB finally breaks OUT of the KC, momentum fires.

  Direction: close > KC_midline (EMA20) → long; < → short.
  MTF filter: 4h close vs 4h KC midline must agree with 1h direction.
    This is the key PF lift: 1h standalone PF 1.31 but max-DD 25%, train/test gap
    1.21/1.85; MTF version same PF with DD 18%, TR≈TE 1.30/1.34.

  SL = entry ± 2.0 × ATR.  TP = entry ± 2.5 × SL-distance.
  Position slot: {symbol}:squeeze (independent of BB/ORB/Asia/FVG).

WHY IT WORKS (hypothesis):
  Low-volatility consolidations (squeeze) represent equilibrium — supply and demand
  balanced. When one side wins (BB expands) the initial expansion tends to continue
  because stop hunts clear the other side's positions. The 4h agreement filter
  ensures we're not fighting a larger-timeframe trend reversal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from indicators import atr as atr_fn, ema as ema_fn


@dataclass
class SqueezeSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 – 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0
    squeeze_bars: int = 0  # how many bars the market was in squeeze before firing


class SqueezeStrategy:
    """Pure volatility-squeeze signal. analyze() is called on each closed 1h candle
    with a recent OHLCV buffer. Computes 4h direction internally via resample."""

    def __init__(
        self,
        kc_period: int = 20,
        kc_mult: float = 1.5,
        bb_period: int = 20,
        bb_std: float = 2.0,
        min_squeeze_bars: int = 5,
        sl_atr: float = 2.0,
        rr: float = 2.5,
        mtf_filter: bool = True,
    ):
        self._kc_period = kc_period
        self._kc_mult = kc_mult
        self._bb_period = bb_period
        self._bb_std = bb_std
        self._min_sq = min_squeeze_bars
        self._sl_atr = sl_atr
        self._rr = rr
        self._mtf = mtf_filter

    def _min_bars(self) -> int:
        return max(self._kc_period, self._bb_period) + self._min_sq + 5

    def analyze(self, df: pd.DataFrame, atr_val: float) -> SqueezeSignal:
        """df: recent 1h OHLCV (DatetimeIndex, columns open/high/low/close).
        atr_val: pre-computed 1h ATR for sizing (avoids recomputing twice)."""
        if len(df) < self._min_bars():
            return SqueezeSignal(0, 0.0, f"insufficient data ({len(df)} < {self._min_bars()})")
        if atr_val <= 0:
            return SqueezeSignal(0, 0.0, "ATR not available")

        close = df["close"]
        high  = df["high"]
        low   = df["low"]

        # Bollinger Bands
        bb_mid = close.rolling(self._bb_period).mean()
        bb_std = close.rolling(self._bb_period).std()
        bb_up  = bb_mid + self._bb_std * bb_std
        bb_lo  = bb_mid - self._bb_std * bb_std

        # Keltner Channel
        kc_mid = ema_fn(close, self._kc_period)
        at_kc  = atr_fn(high, low, close, self._kc_period)
        kc_up  = kc_mid + self._kc_mult * at_kc
        kc_lo  = kc_mid - self._kc_mult * at_kc

        # Squeeze: BB inside KC
        in_sq = (bb_up < kc_up) & (bb_lo > kc_lo)

        # Current bar = last bar; previous bar = second-to-last
        is_sq_curr = bool(in_sq.iloc[-1])
        is_sq_prev = bool(in_sq.iloc[-2]) if len(in_sq) >= 2 else False

        # Not a squeeze release
        if is_sq_curr or not is_sq_prev:
            return SqueezeSignal(
                0, 0.0,
                f"no release (in_sq={is_sq_curr}, prev={is_sq_prev})"
            )

        # Count consecutive squeeze bars ending at the previous bar
        sq_vals = in_sq.values
        count = 0
        for j in range(len(sq_vals) - 2, -1, -1):
            if sq_vals[j]:
                count += 1
            else:
                break

        # Require min_sq + 1 bars: the backtest processes the release candle as
        # iloc[-1] while still holding min_sq prior squeeze bars in the window,
        # making the effective threshold min_sq+1. Without the +1 the live code
        # fires a bar earlier than the validated backtest edge.
        if count < self._min_sq + 1:
            return SqueezeSignal(
                0, 0.0,
                f"squeeze too short ({count} < {self._min_sq + 1} bars)"
            )

        # Direction: 1h close vs KC midline
        direction_1h = 1 if float(close.iloc[-1]) > float(kc_mid.iloc[-1]) else -1

        # MTF filter: resample 1h to 4h, compare close vs KC midline on 4h
        if self._mtf:
            dir_4h = self._htf_direction(df)
            if dir_4h != 0 and dir_4h != direction_1h:
                return SqueezeSignal(
                    0, 0.0,
                    f"MTF filter: 1h={'+' if direction_1h==1 else '-'} "
                    f"4h={'+' if dir_4h==1 else '-'} (conflict)"
                )

        entry = float(close.iloc[-1])
        sl    = entry - direction_1h * self._sl_atr * atr_val
        tp    = entry + direction_1h * self._rr * self._sl_atr * atr_val
        side  = "long" if direction_1h == 1 else "short"

        return SqueezeSignal(
            direction=direction_1h,
            strength=min(1.0, 0.6 + 0.04 * count),
            reason=f"squeeze {side}: {count}bar coil → release",
            sl_price=sl,
            tp_price=tp,
            entry_price=entry,
            squeeze_bars=count,
        )

    def _htf_direction(self, df_1h: pd.DataFrame) -> int:
        """Compute 4h momentum direction by resampling the 1h buffer."""
        need = (self._kc_period + 2) * 4  # need enough 4h bars
        if len(df_1h) < need:
            return 0
        df4 = df_1h.resample("4h").agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last",
        }).dropna()
        if len(df4) < self._kc_period + 2:
            return 0
        kc_mid4 = ema_fn(df4["close"], self._kc_period)
        # Use the last COMPLETE 4h bar (iloc[-2] since iloc[-1] may be incomplete)
        c4   = float(df4["close"].iloc[-2])
        mid4 = float(kc_mid4.iloc[-2])
        if pd.isna(mid4):
            return 0
        return 1 if c4 > mid4 else -1
