from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import StrategyConfig
from indicators import ema, macd, adx


@dataclass
class TrendSignal:
    direction: int       # +1 long, -1 short, 0 neutral
    strength: float      # 0.0 – 1.0
    reason: str
    ema_cross: str       # 'bullish_cross' | 'bearish_cross' | 'none'
    macd_aligned: bool


class TrendStrategy:
    def __init__(self, config: StrategyConfig):
        self._cfg = config

    def analyze(
        self, df_primary: pd.DataFrame, df_confirm: pd.DataFrame
    ) -> TrendSignal:
        if len(df_primary) < self._cfg.ema_slow + 5:
            return TrendSignal(0, 0.0, "insufficient data", "none", False)

        close_p = df_primary["close"]
        close_c = df_confirm["close"] if len(df_confirm) >= self._cfg.ema_slow else None

        ema_fast = ema(close_p, self._cfg.ema_fast)
        ema_slow = ema(close_p, self._cfg.ema_slow)
        _, _, hist = macd(close_p, self._cfg.macd_fast, self._cfg.macd_slow, self._cfg.macd_signal)
        adx_val = adx(df_primary["high"], df_primary["low"], close_p, self._cfg.adx_period).iloc[-1]

        # EMA crossover detection in last 3 bars
        cross = "none"
        bull_score = 0.0
        bear_score = 0.0

        for i in range(-3, 0):
            prev_fast = ema_fast.iloc[i - 1]
            prev_slow = ema_slow.iloc[i - 1]
            curr_fast = ema_fast.iloc[i]
            curr_slow = ema_slow.iloc[i]
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                cross = "bullish_cross"
                break
            if prev_fast >= prev_slow and curr_fast < curr_slow:
                cross = "bearish_cross"
                break

        # Scoring
        if cross == "bullish_cross":
            bull_score += 0.4
        elif cross == "bearish_cross":
            bear_score += 0.4
        elif ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            bull_score += 0.1
        else:
            bear_score += 0.1

        # 15m EMA alignment
        if close_c is not None and len(close_c) >= self._cfg.ema_slow:
            ema_fast_c = ema(close_c, self._cfg.ema_fast).iloc[-1]
            ema_slow_c = ema(close_c, self._cfg.ema_slow).iloc[-1]
            if ema_fast_c > ema_slow_c:
                bull_score += 0.2
            else:
                bear_score += 0.2

        # MACD histogram slope
        macd_aligned = False
        if len(hist.dropna()) >= 2:
            if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
                bull_score += 0.2
                macd_aligned = True
            elif hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2]:
                bear_score += 0.2
                macd_aligned = True

        # ADX trend strength
        if not pd.isna(adx_val) and adx_val > 25:
            if bull_score > bear_score:
                bull_score += 0.2
            elif bear_score > bull_score:
                bear_score += 0.2

        if bull_score > bear_score and bull_score > 0.1:
            return TrendSignal(
                direction=1, strength=min(bull_score, 1.0),
                reason=f"EMA {cross}, MACD aligned={macd_aligned}, ADX={adx_val:.1f}",
                ema_cross=cross, macd_aligned=macd_aligned,
            )
        if bear_score > bull_score and bear_score > 0.1:
            return TrendSignal(
                direction=-1, strength=min(bear_score, 1.0),
                reason=f"EMA {cross}, MACD aligned={macd_aligned}, ADX={adx_val:.1f}",
                ema_cross=cross, macd_aligned=macd_aligned,
            )
        return TrendSignal(0, 0.0, "no clear trend", "none", False)
