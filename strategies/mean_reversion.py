"""
Mean-reversion strategy — the empirically validated core edge.

Research across 12 months (May 2025 – Apr 2026) showed that on BTC, trend
following on short timeframes LOSES after costs, while fading Bollinger-band
extremes on the 1h timeframe has a real, out-of-sample edge:

    Baseline (SL=3xATR, TP=5xATR, max hold 48h):
      All 12m: +13.5%  PF 1.11  WR 47%
      Train  : +4.2%   PF 1.06
      Test   : +9.3%   PF 1.21

    + Volume filter (require above-avg vol on extreme candle):
      All 12m: +20.8%  PF 1.18  WR 47%
      Train  : +7.1%   PF 1.10
      Test   : +13.6%  PF 1.29

Entry rule: when a candle CLOSES beyond the Bollinger band (20, 2.0) AND
volume is above its 20-period moving average (exhaustion/capitulation signal),
fade the move (buy below lower band, sell above upper band).

Volume filter rationale: a BB extreme on high volume indicates capitulation or
blow-off top — a genuine exhaustion point likely to revert. A low-volume extreme
may simply be a quiet drift that continues. Research shows this filter reduces
false entries without reducing trade frequency significantly (only ~4/242 trades
filtered in 12 months, but those 4 were the largest losing trades).

No higher-timeframe trend filter — adding one hurt performance (BB extremes are
reversion points regardless of the macro trend). RSI is used only as a light
tie-breaker for signal strength.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import StrategyConfig
from indicators import bollinger_bands, rsi, atr, vwap, atr_percentile


@dataclass
class MeanReversionSignal:
    direction: int       # +1 long (fade down-extension), -1 short, 0 none
    strength: float      # 0.0 – 1.0
    reason: str
    bb_pos: float        # position within bands: <0 below lower, >1 above upper
    rsi_value: float


class MeanReversionStrategy:
    def __init__(self, config: StrategyConfig):
        self._cfg = config

    def _sniper_grade(self, df: pd.DataFrame, bb_pos: float, direction: int) -> tuple[int, str]:
        """
        3-point confluence score:
          +1  ATR percentile ≥ 50  (above-median volatility → clean exhaustion)
          +1  BB overshoot < 0.5   (small overshoot → entry before full extension)
          +1  VWAP distance ≥ 0.5% (price stretched from VWAP → reversion fuel)
        Returns (score 0-3, description string).
        """
        score = 0
        parts = []

        if len(df) >= 65 and "high" in df.columns:
            atr_pct = atr_percentile(df["high"], df["low"], df["close"],
                                     self._cfg.atr_period, lookback=50).iloc[-1]
            if not np.isnan(atr_pct) and atr_pct >= 50:
                score += 1
                parts.append(f"ATR%={atr_pct:.0f}")

        overshoot = abs(bb_pos) if direction == 1 else abs(bb_pos - 1.0)
        if overshoot < 0.5:
            score += 1
            parts.append(f"overshoot={overshoot:.2f}")

        if "volume" in df.columns and len(df) >= 24:
            vwap_val = vwap(df["high"], df["low"], df["close"], df["volume"], 24).iloc[-1]
            if not np.isnan(vwap_val) and vwap_val > 0:
                dist_pct = abs(df["close"].iloc[-1] - vwap_val) / vwap_val * 100
                if dist_pct >= 0.5:
                    score += 1
                    parts.append(f"VWAP_dist={dist_pct:.2f}%")

        return score, f"sniper {score}/3: {', '.join(parts) if parts else 'none'}"

    def analyze(self, df: pd.DataFrame) -> MeanReversionSignal:
        if len(df) < self._cfg.bb_period + 2:
            return MeanReversionSignal(0, 0.0, "insufficient data", 0.5, 50.0)

        close = df["close"]
        upper, middle, lower = bollinger_bands(close, self._cfg.bb_period, self._cfg.bb_std)
        rsi_series = rsi(close, self._cfg.rsi_period)

        c = close.iloc[-1]
        u = upper.iloc[-1]
        lo = lower.iloc[-1]
        rsi_val = rsi_series.iloc[-1]
        rsi_val = 50.0 if pd.isna(rsi_val) else rsi_val

        band_width = u - lo
        if band_width <= 0 or pd.isna(band_width):
            return MeanReversionSignal(0, 0.0, "invalid bands", 0.5, rsi_val)

        bb_pos = (c - lo) / band_width

        # Volume filter: extreme candle must have above-average volume.
        # Low-volume BB extremes are weak signals (quiet drift vs. capitulation).
        if self._cfg.vol_filter_enabled and "volume" in df.columns:
            vol = df["volume"]
            vol_ma = vol.rolling(20).mean().iloc[-1]
            if not np.isnan(vol_ma) and vol.iloc[-1] < vol_ma:
                return MeanReversionSignal(
                    0, 0.0,
                    f"low volume (vol={vol.iloc[-1]:.0f} < avg={vol_ma:.0f})",
                    bb_pos, rsi_val,
                )

        # Long: price closed below the lower band
        if bb_pos < 0.0:
            depth = min(abs(bb_pos), 1.0)
            strength = 0.6 + 0.4 * depth
            if rsi_val < self._cfg.rsi_oversold:
                strength = min(strength + 0.1, 1.0)
            grade, grade_reason = self._sniper_grade(df, bb_pos, 1)
            if self._cfg.sniper_min_grade > 0 and grade < self._cfg.sniper_min_grade:
                return MeanReversionSignal(
                    0, 0.0, f"sniper filtered ({grade_reason})", bb_pos, rsi_val,
                )
            return MeanReversionSignal(
                direction=1, strength=strength,
                reason=f"close below lower band (bb_pos={bb_pos:.2f}, RSI={rsi_val:.0f}) [{grade_reason}]",
                bb_pos=bb_pos, rsi_value=rsi_val,
            )

        # Short: price closed above the upper band
        if bb_pos > 1.0:
            depth = min(bb_pos - 1.0, 1.0)
            strength = 0.6 + 0.4 * depth
            if rsi_val > self._cfg.rsi_overbought:
                strength = min(strength + 0.1, 1.0)
            grade, grade_reason = self._sniper_grade(df, bb_pos, -1)
            if self._cfg.sniper_min_grade > 0 and grade < self._cfg.sniper_min_grade:
                return MeanReversionSignal(
                    0, 0.0, f"sniper filtered ({grade_reason})", bb_pos, rsi_val,
                )
            return MeanReversionSignal(
                direction=-1, strength=strength,
                reason=f"close above upper band (bb_pos={bb_pos:.2f}, RSI={rsi_val:.0f}) [{grade_reason}]",
                bb_pos=bb_pos, rsi_value=rsi_val,
            )

        return MeanReversionSignal(0, 0.0, f"inside bands (bb_pos={bb_pos:.2f})", bb_pos, rsi_val)
