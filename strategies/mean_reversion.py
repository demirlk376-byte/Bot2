"""
Mean-reversion strategy — the empirically validated core edge.

Research across 12 months (May 2025 – Apr 2026) showed that on BTC, trend
following on short timeframes LOSES after costs, while fading Bollinger-band
extremes on the 1h timeframe has a real, out-of-sample edge:
    SL=3xATR, TP=5xATR, max hold 48h →
    Train (May–Dec 2025): +13.3% PF 1.09
    Test  (Jan–Apr 2026): +22.1% PF 1.26

Entry rule: when a candle CLOSES beyond the Bollinger band (20, 2.0), fade it
(buy below lower band, sell above upper band). No higher-timeframe trend filter
— adding one hurt performance (BB extremes are reversion points regardless of
the macro trend). RSI is used only as a light tie-breaker for signal strength.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import StrategyConfig
from indicators import bollinger_bands, rsi


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

        # Long: price closed below the lower band
        if bb_pos < 0.0:
            # Strength grows with how far below the band, plus RSI confirmation
            depth = min(abs(bb_pos), 1.0)
            strength = 0.6 + 0.4 * depth
            if rsi_val < self._cfg.rsi_oversold:
                strength = min(strength + 0.1, 1.0)
            return MeanReversionSignal(
                direction=1, strength=strength,
                reason=f"close below lower band (bb_pos={bb_pos:.2f}, RSI={rsi_val:.0f})",
                bb_pos=bb_pos, rsi_value=rsi_val,
            )

        # Short: price closed above the upper band
        if bb_pos > 1.0:
            depth = min(bb_pos - 1.0, 1.0)
            strength = 0.6 + 0.4 * depth
            if rsi_val > self._cfg.rsi_overbought:
                strength = min(strength + 0.1, 1.0)
            return MeanReversionSignal(
                direction=-1, strength=strength,
                reason=f"close above upper band (bb_pos={bb_pos:.2f}, RSI={rsi_val:.0f})",
                bb_pos=bb_pos, rsi_value=rsi_val,
            )

        return MeanReversionSignal(0, 0.0, f"inside bands (bb_pos={bb_pos:.2f})", bb_pos, rsi_val)
