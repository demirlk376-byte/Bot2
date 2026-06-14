"""
Opening Range Breakout (ORB) strategy — NY session, 60-minute range.

EDGE (research_daytrading2.py, BTC 12 months May 2025 – Apr 2026):
  ORB 60min SL=1.0×range RR=2.0: PF 1.44, WR 51%, +23.4%
                                  TR W52% +$1331 | TE W50% +$1011  ← both positive
  DD: 4.1%  (vs 1h BB baseline DD 10.8%)

LOGIC:
  • ORB period: the 14:00 UTC 1h candle (NY open, 10:00 ET). Its high and low
    define the range to break.
  • After that candle closes (at 15:00 UTC), watch for the first 1h close
    outside the range on the same calendar day.
  • ONE trade per day per symbol. If the first break goes long and then fails,
    we do NOT re-enter short — avoids whipsawing.
  • SL:  at the opposite edge of the range (long: SL = orb_low, short: SL = orb_high).
  • TP:  entry ± 2.0 × range_size.
  • Max hold: 6h (DAY_MAX_HOLD_CANDLES) — exits via tick-level SL/TP or the
    normal max-hold enforcer.

WHY IT WORKS (hypothesis):
  NY open sees the largest institutional order flow of the trading day. The first
  hour absorbs most of the opening liquidity; a close above/below the opening
  range signals directional commitment by informed participants, not noise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

ORB_HOUR = 14          # UTC hour at which the ORB candle opens (14:00 UTC = 10:00 ET)
DEFAULT_RR = 2.0


@dataclass
class OrbSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 – 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    orb_high: float = 0.0
    orb_low: float = 0.0


class OrbStrategy:
    """ORB on 1h candles. analyze() is called on every 1h candle-close callback."""

    def __init__(self, rr: float = DEFAULT_RR):
        self._rr = rr
        self._traded_dates: set[date] = set()   # prevent re-entry on same day

    def analyze(self, df: pd.DataFrame) -> OrbSignal:
        if df is None or len(df) < 2:
            return OrbSignal(0, 0.0, "insufficient data")

        last = df.index[-1]
        today_utc: date = last.date()

        # Only one trade per day
        if today_utc in self._traded_dates:
            return OrbSignal(0, 0.0, f"already traded {today_utc}")

        # The just-closed candle must have opened at ORB_HOUR+1 or later (15:00+ UTC).
        # The ORB candle itself (14:00 UTC) is still forming when it closes at 15:00;
        # its bar opened at 14:00, so df.index[-1].hour == 14 means it just closed.
        # The first bar we can trade is the 15:00 candle (hour == 15).
        if last.hour <= ORB_HOUR:
            return OrbSignal(0, 0.0, f"ORB candle not yet complete (hour={last.hour})")

        # Find the ORB candle: the bar that opened at ORB_HOUR UTC on today_utc
        mask = (pd.to_datetime(df.index).date == today_utc) & (df.index.hour == ORB_HOUR)
        orb_rows = df[mask]
        if orb_rows.empty:
            return OrbSignal(0, 0.0, "no ORB candle in buffer")

        orb_high = float(orb_rows["high"].max())
        orb_low  = float(orb_rows["low"].min())
        orb_range = orb_high - orb_low
        if orb_range <= 0:
            return OrbSignal(0, 0.0, "degenerate ORB range")

        # Only fire once per day: if any post-ORB bar today already broke the range
        # before this bar, we should not fire again — but since we record
        # _traded_dates after firing, this naturally prevents a second fire on
        # the same day.  Just check the CURRENT close.
        current_close = float(df["close"].iloc[-1])

        if current_close > orb_high:
            # Limit entry fills at orb_high (the breakout boundary), not current_close.
            # SL/TP must be anchored to the limit price so the RR is accurate.
            sl = orb_low
            tp = orb_high + self._rr * orb_range
            self._traded_dates.add(today_utc)
            return OrbSignal(
                direction=1, strength=0.80,
                reason=f"ORB long: close {current_close:.0f} > range {orb_low:.0f}–{orb_high:.0f}",
                sl_price=sl, tp_price=tp, orb_high=orb_high, orb_low=orb_low,
            )

        if current_close < orb_low:
            # Limit entry fills at orb_low; anchor SL/TP to the limit price.
            sl = orb_high
            tp = orb_low - self._rr * orb_range
            self._traded_dates.add(today_utc)
            return OrbSignal(
                direction=-1, strength=0.80,
                reason=f"ORB short: close {current_close:.0f} < range {orb_low:.0f}–{orb_high:.0f}",
                sl_price=sl, tp_price=tp, orb_high=orb_high, orb_low=orb_low,
            )

        return OrbSignal(0, 0.0,
            f"inside ORB ({orb_low:.0f}–{orb_high:.0f}, close={current_close:.0f})")
