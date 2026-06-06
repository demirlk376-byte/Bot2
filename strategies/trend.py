from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import StrategyConfig
from indicators import ema, macd, adx, rsi


@dataclass
class TrendSignal:
    direction: int       # +1 long, -1 short, 0 neutral
    strength: float      # 0.0 – 1.0
    reason: str
    ema_cross: str       # 'bullish_cross' | 'bearish_cross' | 'pullback' | 'none'
    macd_aligned: bool


class TrendStrategy:
    PULLBACK_TOUCH_PCT = 0.002  # price must have touched EMA-fast within 0.2%
    MIN_SEPARATION = 0.002      # EMA fast/slow must be ≥ 0.2% apart to signal a real trend

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
        rsi_val = rsi(close_p, self._cfg.rsi_period).iloc[-1]

        curr_fast = ema_fast.iloc[-1]
        curr_slow = ema_slow.iloc[-1]
        separation = (curr_fast - curr_slow) / curr_slow

        bull_score = 0.0
        bear_score = 0.0
        cross = "none"

        # --- Signal 1: Fresh EMA 9/21 crossover (last 3 bars) ---
        for i in range(-3, 0):
            pf = ema_fast.iloc[i - 1]
            ps = ema_slow.iloc[i - 1]
            cf = ema_fast.iloc[i]
            cs = ema_slow.iloc[i]
            if pf <= ps and cf > cs:
                cross = "bullish_cross"
                break
            if pf >= ps and cf < cs:
                cross = "bearish_cross"
                break

        if cross == "bullish_cross":
            bull_score += 0.4
        elif cross == "bearish_cross":
            bear_score += 0.4

        # --- Signal 2: EMA pullback bounce (continuation entry in established trend) ---
        # Only fires if:
        #   - No fresh cross (cross handles that case)
        #   - EMA stack is clearly separated (real trend exists, not noise)
        #   - Price recently touched EMA-fast and bounced back
        elif abs(separation) >= self.MIN_SEPARATION:
            price = close_p.iloc[-1]
            ema_f = curr_fast
            tolerance = ema_f * self.PULLBACK_TOUCH_PCT

            if separation > 0:  # uptrend
                recent_lows = df_primary["low"].iloc[-4:-1]
                touched = recent_lows.min() <= ema_f + tolerance
                recovered = price > ema_f
                if touched and recovered:
                    bull_score += 0.30
                    cross = "pullback"
            else:  # downtrend
                recent_highs = df_primary["high"].iloc[-4:-1]
                touched = recent_highs.max() >= ema_f - tolerance
                recovered = price < ema_f
                if touched and recovered:
                    bear_score += 0.30
                    cross = "pullback"

        # --- Confirmation layers ---

        # 15m EMA stack alignment
        if close_c is not None and len(close_c) >= self._cfg.ema_slow:
            ema_fast_c = ema(close_c, self._cfg.ema_fast).iloc[-1]
            ema_slow_c = ema(close_c, self._cfg.ema_slow).iloc[-1]
            if ema_fast_c > ema_slow_c:
                bull_score += 0.2
            else:
                bear_score += 0.2

        # MACD histogram direction and momentum
        macd_aligned = False
        if len(hist.dropna()) >= 3:
            h0 = hist.iloc[-1]
            h1 = hist.iloc[-2]
            if h0 > 0 and h0 > h1:
                bull_score += 0.2
                macd_aligned = True
            elif h0 < 0 and h0 < h1:
                bear_score += 0.2
                macd_aligned = True

        # ADX: confirm trend regime; penalize in ranging market
        if not pd.isna(adx_val):
            if adx_val > 25:
                if bull_score > bear_score:
                    bull_score += 0.2
                elif bear_score > bull_score:
                    bear_score += 0.2
            elif adx_val < 18:
                bull_score *= 0.65
                bear_score *= 0.65

        # RSI extreme guard: buying overbought (RSI>68) or shorting oversold (RSI<32)
        # are low-probability entries — reduce signal strength
        if not pd.isna(rsi_val):
            if rsi_val > 68 and bull_score > bear_score:
                bull_score *= 0.55
            elif rsi_val < 32 and bear_score > bull_score:
                bear_score *= 0.55

        if bull_score > bear_score and bull_score > 0.18:
            return TrendSignal(
                direction=1, strength=min(bull_score, 1.0),
                reason=f"sep={separation:.3%} cross={cross} MACD={macd_aligned} ADX={adx_val:.1f} RSI={rsi_val:.1f}",
                ema_cross=cross, macd_aligned=macd_aligned,
            )
        if bear_score > bull_score and bear_score > 0.18:
            return TrendSignal(
                direction=-1, strength=min(bear_score, 1.0),
                reason=f"sep={separation:.3%} cross={cross} MACD={macd_aligned} ADX={adx_val:.1f} RSI={rsi_val:.1f}",
                ema_cross=cross, macd_aligned=macd_aligned,
            )
        return TrendSignal(0, 0.0, f"no signal (sep={separation:.3%} cross={cross})", "none", False)
