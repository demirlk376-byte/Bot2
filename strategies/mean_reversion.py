from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import StrategyConfig
from indicators import bollinger_bands, rsi, is_bb_squeeze, SRLevel


@dataclass
class MeanReversionSignal:
    direction: int
    strength: float
    reason: str
    bb_signal: str     # 'below_lower' | 'above_upper' | 'none'
    rsi_signal: str    # 'oversold' | 'overbought' | 'none'
    bb_squeeze: bool


class MeanReversionStrategy:
    def __init__(self, config: StrategyConfig):
        self._cfg = config

    def analyze(
        self,
        df_primary: pd.DataFrame,
        df_confirm: pd.DataFrame,
        sr_levels: Optional[list[SRLevel]] = None,
    ) -> MeanReversionSignal:
        if len(df_primary) < self._cfg.bb_period + 5:
            return MeanReversionSignal(0, 0.0, "insufficient data", "none", "none", False)

        close_p = df_primary["close"]
        upper, middle, lower = bollinger_bands(close_p, self._cfg.bb_period, self._cfg.bb_std)
        rsi_p = rsi(close_p, self._cfg.rsi_period)
        squeeze = is_bb_squeeze(close_p, self._cfg.bb_period, self._cfg.bb_std)

        current_close = close_p.iloc[-1]
        current_rsi = rsi_p.iloc[-1] if not pd.isna(rsi_p.iloc[-1]) else 50.0

        # 15m RSI
        rsi_15m = 50.0
        if len(df_confirm) >= self._cfg.rsi_period + 2:
            rsi_c = rsi(df_confirm["close"], self._cfg.rsi_period)
            if not pd.isna(rsi_c.iloc[-1]):
                rsi_15m = rsi_c.iloc[-1]

        bull_score = 0.0
        bear_score = 0.0
        bb_signal = "none"
        rsi_signal = "none"

        # BB signal
        if current_close < lower.iloc[-1]:
            bull_score += 0.35
            bb_signal = "below_lower"
        elif current_close > upper.iloc[-1]:
            bear_score += 0.35
            bb_signal = "above_upper"

        # RSI signal
        if current_rsi < self._cfg.rsi_oversold:
            bull_score += 0.35
            rsi_signal = "oversold"
        elif current_rsi > self._cfg.rsi_overbought:
            bear_score += 0.35
            rsi_signal = "overbought"

        # 15m RSI confirmation
        if rsi_15m < 40 and bb_signal == "below_lower":
            bull_score += 0.15
        elif rsi_15m > 60 and bb_signal == "above_upper":
            bear_score += 0.15

        # S/R proximity
        if sr_levels:
            tolerance = current_close * 0.003
            for level in sr_levels:
                if abs(level.price - current_close) <= tolerance:
                    if level.level_type == "support" and bull_score > 0:
                        bull_score += 0.15
                    elif level.level_type == "resistance" and bear_score > 0:
                        bear_score += 0.15

        # BB squeeze penalty
        if squeeze:
            bull_score *= 0.5
            bear_score *= 0.5

        if bull_score > bear_score and bull_score > 0.1:
            return MeanReversionSignal(
                direction=1, strength=min(bull_score, 1.0),
                reason=f"BB={bb_signal} RSI={current_rsi:.1f} squeeze={squeeze}",
                bb_signal=bb_signal, rsi_signal=rsi_signal, bb_squeeze=squeeze,
            )
        if bear_score > bull_score and bear_score > 0.1:
            return MeanReversionSignal(
                direction=-1, strength=min(bear_score, 1.0),
                reason=f"BB={bb_signal} RSI={current_rsi:.1f} squeeze={squeeze}",
                bb_signal=bb_signal, rsi_signal=rsi_signal, bb_squeeze=squeeze,
            )
        return MeanReversionSignal(0, 0.0, "no MR signal", "none", "none", squeeze)
