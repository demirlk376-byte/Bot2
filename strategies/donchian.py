"""
Donchian Channel Swing Breakout (4h) — higher-timeframe trend-continuation.

EDGE (scratch_cand_donchian_4h_swing.py + scratch_donchian_close.py, BTC 4h
2023-01..2026-04, honest TRAIN/TEST split at 2026-01-01, TAKER cost 0.08% RT):
  CLOSE-confirmed market entry, channel=40, RR=2.0, SL=2.0xATR, EMA200 trend
  filter:  ALL PF 1.35 (172t)  TRAIN PF 1.39  TEST PF 1.11
  POSITIVE EVERY YEAR: 2023 PF 1.72 | 2024 PF 1.35 | 2025 PF 1.08 | 2026 PF 1.11
  (A resting-stop "fill-at-level" execution backtests materially stronger — ~PF
   1.5, TEST 1.55 — but needs a tick-watcher like ORB; this sleeve ships the
   simpler, lower-risk close-confirmed market entry that needs no new infra.)

WHY A NEW SLEEVE:
  The live book is almost entirely 1h INTRADAY momentum (ORB, FVG, IFVG, Squeeze,
  S/R) plus the 1h BB fade. There was NO higher-timeframe / multi-day swing sleeve
  — the 4h was only ever used as a confirmation filter, never as a primary entry
  timeframe. Donchian trades the 4h channel with 1-5 day holds, so it is
  decorrelated from the intraday sleeves by HOLDING PERIOD even though it is the
  same (momentum) style.

LOGIC:
  • Channel: highest-high / lowest-low of the prior `channel` 4h bars, EXCLUDING
    the just-closed bar (no lookahead).
  • Long  when the 4h candle CLOSES above the channel high AND close > EMA200(4h).
  • Short when the 4h candle CLOSES below the channel low  AND close < EMA200(4h).
    The EMA200 trend filter is the key robustness lever — it keeps breakouts
    aligned with the higher-timeframe trend (HTF alignment, not a holistic-edge
    partition) and was what lifted every yearly PF above 1.0.
  • Entry: market at the close (force_market — taker fill ~close, as validated).
  • SL = entry -/+ sl_atr x ATR(14, 4h).  TP = entry +/- rr x (sl_atr x ATR).
  • Max hold: 30 x 4h bars = 120h (5 days) — stored as 120 in 1h-candle units for
    the max-hold enforcer (which counts in primary-tf candles).
  • One position per `{symbol}:donchian` slot; analyze() only fires a fresh signal
    when the slot is empty (enforced by the executor), so an extended trend does
    not stack entries.

DATA NOTE:
  analyze() is fed the 4h OHLCV buffer (confirm_tf, ~260 bars) and the 4h ATR.
  It is called from the 1h candle loop only on a 4h boundary (UTC hour % 4 == 3),
  i.e. once per just-closed 4h bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators import atr as atr_fn, ema as ema_fn

DEFAULT_CHANNEL = 40
DEFAULT_RR = 2.0
DEFAULT_SL_ATR = 2.0
DEFAULT_EMA_TREND = 200
DEFAULT_BUFFER_ATR = 0.0
# Max hold in PRIMARY-tf (1h) candles: 30 x 4h bars = 120h (5 days).
MAX_HOLD_1H_CANDLES = 120


@dataclass
class DonchianSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 - 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0
    channel_high: float = 0.0
    channel_low: float = 0.0


class DonchianStrategy:
    """Donchian channel breakout on 4h with an EMA200 trend filter. analyze() is
    called once per closed 4h candle (from the 1h loop at a 4h boundary)."""

    def __init__(
        self,
        channel: int = DEFAULT_CHANNEL,
        rr: float = DEFAULT_RR,
        sl_atr: float = DEFAULT_SL_ATR,
        ema_trend: int = DEFAULT_EMA_TREND,
        buffer_atr: float = DEFAULT_BUFFER_ATR,
    ):
        self._channel = channel
        self._rr = rr
        self._sl_atr = sl_atr
        self._ema_trend = ema_trend
        self._buffer_atr = buffer_atr

    def _min_bars(self) -> int:
        # Need the channel lookback plus enough history for EMA200 to settle.
        return max(self._channel + 2, self._ema_trend)

    def analyze(self, df: pd.DataFrame, atr_val: float) -> DonchianSignal:
        """df: recent 4h OHLCV (DatetimeIndex, columns open/high/low/close).
        atr_val: pre-computed 4h ATR(14) for sizing/stops."""
        if df is None or len(df) < self._min_bars():
            return DonchianSignal(0, 0.0, f"insufficient data ({0 if df is None else len(df)} < {self._min_bars()})")
        if atr_val is None or atr_val <= 0:
            return DonchianSignal(0, 0.0, "ATR not available")

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # Channel over the prior `channel` bars, EXCLUDING the just-closed bar.
        chan_high = float(np.max(high[-(self._channel + 1):-1]))
        chan_low = float(np.min(low[-(self._channel + 1):-1]))
        if chan_high <= chan_low:
            return DonchianSignal(0, 0.0, "degenerate channel")

        ema_series = ema_fn(df["close"], self._ema_trend)
        ema_now = float(ema_series.iloc[-1])
        if np.isnan(ema_now):
            return DonchianSignal(0, 0.0, "EMA200 not ready")

        c = float(close[-1])
        buf = self._buffer_atr * atr_val
        sl_dist = self._sl_atr * atr_val

        # Long: fresh close above the channel, aligned with the HTF uptrend.
        if c > chan_high + buf and c > ema_now:
            sl = c - sl_dist
            tp = c + self._rr * sl_dist
            return DonchianSignal(
                direction=1, strength=0.80,
                reason=(f"Donchian long: close {c:.0f} > channel high "
                        f"{chan_high:.0f} (EMA200 {ema_now:.0f})"),
                sl_price=sl, tp_price=tp, entry_price=c,
                channel_high=chan_high, channel_low=chan_low,
            )

        # Short: fresh close below the channel, aligned with the HTF downtrend.
        if c < chan_low - buf and c < ema_now:
            sl = c + sl_dist
            tp = c - self._rr * sl_dist
            return DonchianSignal(
                direction=-1, strength=0.80,
                reason=(f"Donchian short: close {c:.0f} < channel low "
                        f"{chan_low:.0f} (EMA200 {ema_now:.0f})"),
                sl_price=sl, tp_price=tp, entry_price=c,
                channel_high=chan_high, channel_low=chan_low,
            )

        return DonchianSignal(
            0, 0.0,
            f"no breakout (close {c:.0f}, channel {chan_low:.0f}-{chan_high:.0f})",
        )
