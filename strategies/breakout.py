from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import StrategyConfig
from indicators import adx, is_volume_spike, is_bb_squeeze, SRLevel


@dataclass
class BreakoutSignal:
    direction: int
    strength: float
    reason: str
    broken_level: Optional[float]
    volume_confirmed: bool
    retest: bool


class BreakoutStrategy:
    def __init__(self, config: StrategyConfig):
        self._cfg = config

    def analyze(
        self,
        df_primary: pd.DataFrame,
        df_confirm: pd.DataFrame,
        sr_levels: Optional[list[SRLevel]] = None,
    ) -> BreakoutSignal:
        if len(df_primary) < 30 or not sr_levels:
            return BreakoutSignal(0, 0.0, "no SR levels or insufficient data",
                                  None, False, False)

        close_p = df_primary["close"]
        current_close = close_p.iloc[-1]
        current_candle = df_primary.iloc[-1]
        prev_close = close_p.iloc[-2]

        vol_spike = is_volume_spike(
            df_primary["volume"], 20, self._cfg.volume_spike_mult
        ).iloc[-1]
        squeeze = is_bb_squeeze(close_p, 20, 2.0)
        adx_val = adx(df_primary["high"], df_primary["low"], close_p).iloc[-1]

        # Candle body ratio
        candle_range = current_candle["high"] - current_candle["low"]
        body = abs(current_candle["close"] - current_candle["open"])
        body_ratio = body / candle_range if candle_range > 0 else 0

        bull_score = 0.0
        bear_score = 0.0
        broken_level = None
        retest = False

        tolerance = current_close * 0.002

        for level in sr_levels:
            lp = level.price

            # Bullish breakout: close above resistance
            if (level.level_type == "resistance"
                    and current_close > lp
                    and prev_close <= lp):
                bull_score += 0.4
                broken_level = lp
                if body_ratio > 0.6:
                    bull_score += 0.1

            # Bearish breakout: close below support
            elif (level.level_type == "support"
                  and current_close < lp
                  and prev_close >= lp):
                bear_score += 0.4
                broken_level = lp
                if body_ratio > 0.6:
                    bear_score += 0.1

            # Bullish retest: price retested old resistance now acting as support
            elif (level.level_type == "resistance"
                  and abs(current_close - lp) <= tolerance
                  and current_close > lp):
                bull_score += 0.25
                broken_level = lp
                retest = True

            # Bearish retest: price retested old support now acting as resistance
            elif (level.level_type == "support"
                  and abs(current_close - lp) <= tolerance
                  and current_close < lp):
                bear_score += 0.25
                broken_level = lp
                retest = True

        if bull_score == 0.0 and bear_score == 0.0:
            return BreakoutSignal(0, 0.0, "no breakout", None, False, False)

        # Volume confirmation
        if vol_spike:
            if bull_score > bear_score:
                bull_score += 0.3
            else:
                bear_score += 0.3

        # 15m confirmation
        if len(df_confirm) >= 5:
            close_c = df_confirm["close"]
            if len(close_c) >= 2:
                if bull_score > bear_score and close_c.iloc[-1] > close_c.iloc[-2]:
                    bull_score += 0.2
                elif bear_score > bull_score and close_c.iloc[-1] < close_c.iloc[-2]:
                    bear_score += 0.2

        # ADX momentum
        if not pd.isna(adx_val) and adx_val > 20:
            if bull_score > bear_score:
                bull_score += 0.1
            else:
                bear_score += 0.1

        # BB squeeze penalty
        if squeeze:
            bull_score -= 0.3
            bear_score -= 0.3
            bull_score = max(bull_score, 0.0)
            bear_score = max(bear_score, 0.0)

        if bull_score > bear_score and bull_score > 0.1:
            return BreakoutSignal(
                direction=1, strength=min(bull_score, 1.0),
                reason=f"breakout above {broken_level:.2f} vol={vol_spike} retest={retest}",
                broken_level=broken_level, volume_confirmed=bool(vol_spike), retest=retest,
            )
        if bear_score > bull_score and bear_score > 0.1:
            return BreakoutSignal(
                direction=-1, strength=min(bear_score, 1.0),
                reason=f"breakout below {broken_level:.2f} vol={vol_spike} retest={retest}",
                broken_level=broken_level, volume_confirmed=bool(vol_spike), retest=retest,
            )
        return BreakoutSignal(0, 0.0, "conflicted breakout", broken_level, bool(vol_spike), retest)
