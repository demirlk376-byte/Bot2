"""
Asia Range Breakout (ARB) strategy — 00:00–08:00 UTC range, London/NY breakout.

EDGE (research_daytrading2.py, BTC 12 months May 2025 – Apr 2026):
  Asia BO SL=1.0×ATR RR=2.0: PF 2.15, WR 59%, +14%
                               TR W60% +$809 | TE W58% +$598  ← both positive
  DD: 0.6%

LOGIC:
  • Asia range: high/low of all 1h candles opening 00:00–07:59 UTC.
  • After 08:00 UTC (London open), watch for the first 1h close outside the range.
  • ONE trade per day per symbol. No re-entry on the same calendar day.
  • SL:  entry ± 1.0 × ATR (tighter than the Asia range, which can be wide).
  • TP:  entry ± 2.0 × ATR (RR = 2.0).
  • Max hold: 6h (DAY_MAX_HOLD_CANDLES) — enforced by the normal max-hold loop
    via the 'max_hold' key stored in strategy_scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

ASIA_END_HOUR = 8   # UTC: breakout zone starts at 08:00 (London open)
DEFAULT_RR = 2.0
DEFAULT_SL_ATR = 1.0


@dataclass
class AsiaBoSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 – 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    asia_high: float = 0.0
    asia_low: float = 0.0


class AsiaBoStrategy:
    """Asia Range Breakout on 1h candles. analyze() is called on every 1h candle-close."""

    def __init__(self, rr: float = DEFAULT_RR, sl_atr_mult: float = DEFAULT_SL_ATR):
        self._rr = rr
        self._sl_atr = sl_atr_mult
        self._traded_dates: set[date] = set()

    def analyze(self, df: pd.DataFrame, atr_val: float) -> AsiaBoSignal:
        if df is None or len(df) < 10:
            return AsiaBoSignal(0, 0.0, "insufficient data")
        if atr_val <= 0:
            return AsiaBoSignal(0, 0.0, "ATR not available")

        last = df.index[-1]
        today_utc: date = last.date()

        if today_utc in self._traded_dates:
            return AsiaBoSignal(0, 0.0, f"already traded {today_utc}")

        # London/NY session only — Asia must be fully closed
        if last.hour < ASIA_END_HOUR:
            return AsiaBoSignal(0, 0.0, f"Asia session not over (hour={last.hour})")

        # Build Asia range from today's 1h candles with hour in [0, 7]
        mask = (pd.to_datetime(df.index).date == today_utc) & (df.index.hour < ASIA_END_HOUR)
        asia_rows = df[mask]
        if len(asia_rows) < 4:
            return AsiaBoSignal(
                0, 0.0, f"insufficient Asia candles ({len(asia_rows)})"
            )

        asia_high = float(asia_rows["high"].max())
        asia_low  = float(asia_rows["low"].min())
        if asia_high <= asia_low:
            return AsiaBoSignal(0, 0.0, "degenerate Asia range")

        sl_dist = self._sl_atr * atr_val
        current_close = float(df["close"].iloc[-1])

        if current_close > asia_high:
            entry = current_close
            sl    = entry - sl_dist
            tp    = entry + self._rr * sl_dist
            self._traded_dates.add(today_utc)
            return AsiaBoSignal(
                direction=1, strength=0.80,
                reason=(
                    f"Asia BO long: close {current_close:.0f} "
                    f"> range {asia_low:.0f}–{asia_high:.0f}"
                ),
                sl_price=sl, tp_price=tp, asia_high=asia_high, asia_low=asia_low,
            )

        if current_close < asia_low:
            entry = current_close
            sl    = entry + sl_dist
            tp    = entry - self._rr * sl_dist
            self._traded_dates.add(today_utc)
            return AsiaBoSignal(
                direction=-1, strength=0.80,
                reason=(
                    f"Asia BO short: close {current_close:.0f} "
                    f"< range {asia_low:.0f}–{asia_high:.0f}"
                ),
                sl_price=sl, tp_price=tp, asia_high=asia_high, asia_low=asia_low,
            )

        return AsiaBoSignal(
            0, 0.0,
            f"inside Asia range ({asia_low:.0f}–{asia_high:.0f}, close={current_close:.0f})",
        )
