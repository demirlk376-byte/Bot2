from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import StrategyConfig
from strategies.trend import TrendSignal
from strategies.mean_reversion import MeanReversionSignal
from strategies.breakout import BreakoutSignal

ENTRY_THRESHOLD = 0.42   # trend alone fires in trending regime (0.50 weight) with strength ≥ 0.84
CONFLICT_STRENGTH = 0.6


@dataclass
class CombinedSignal:
    direction: int            # +1 | -1 | 0
    confidence: float         # 0.0 – 1.0
    trend_score: float
    mean_rev_score: float
    breakout_score: float
    dominant_strategy: str
    reasons: list[str] = field(default_factory=list)
    entry_price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SignalCombiner:
    # Default weights
    _W_TREND_DEFAULT = 0.40
    _W_BREAK_DEFAULT = 0.35
    _W_MR_DEFAULT = 0.25

    # Trending regime weights
    _W_TREND_TREND = 0.50
    _W_BREAK_TREND = 0.35
    _W_MR_TREND = 0.15

    # Ranging regime weights
    _W_TREND_RANGE = 0.20
    _W_BREAK_RANGE = 0.25
    _W_MR_RANGE = 0.55

    def __init__(self, config: StrategyConfig):
        self._cfg = config

    def combine(
        self,
        trend_sig: TrendSignal,
        mr_sig: MeanReversionSignal,
        break_sig: BreakoutSignal,
        current_price: float,
        adx_value: float,
        htf_bias: int = 0,   # +1 = 1h trend bullish, -1 = bearish, 0 = unknown
    ) -> CombinedSignal:
        # Regime detection
        if adx_value > 25:
            w_trend, w_break, w_mr = self._W_TREND_TREND, self._W_BREAK_TREND, self._W_MR_TREND
            regime = "trending"
        elif adx_value < 20:
            w_trend, w_break, w_mr = self._W_TREND_RANGE, self._W_BREAK_RANGE, self._W_MR_RANGE
            regime = "ranging"
        else:
            w_trend, w_break, w_mr = self._W_TREND_DEFAULT, self._W_BREAK_DEFAULT, self._W_MR_DEFAULT
            regime = "transitional"

        t_eff = trend_sig.direction * trend_sig.strength
        mr_eff = mr_sig.direction * mr_sig.strength
        b_eff = break_sig.direction * break_sig.strength

        weighted = t_eff * w_trend + mr_eff * w_mr + b_eff * w_break

        # Conflict detection: one strong signal opposing the majority
        signals = [
            ("trend", trend_sig.direction, trend_sig.strength),
            ("mean_rev", mr_sig.direction, mr_sig.strength),
            ("breakout", break_sig.direction, break_sig.strength),
        ]

        if weighted > 0:
            opposing = [s for s in signals if s[1] < 0 and s[2] >= CONFLICT_STRENGTH]
        else:
            opposing = [s for s in signals if s[1] > 0 and s[2] >= CONFLICT_STRENGTH]

        if opposing:
            return CombinedSignal(
                direction=0, confidence=0.0,
                trend_score=t_eff, mean_rev_score=mr_eff, breakout_score=b_eff,
                dominant_strategy="conflict",
                reasons=[f"Conflict: {[o[0] for o in opposing]} opposes signal strongly"],
                entry_price=current_price,
            )

        # 1h higher-timeframe bias: soft modifier (-0.08 penalty if going against 1h trend)
        # Does not block trades — just raises the bar slightly for counter-trend entries.
        if htf_bias != 0 and weighted != 0:
            if (htf_bias > 0 and weighted < 0) or (htf_bias < 0 and weighted > 0):
                weighted *= 0.85  # 15% reduction for counter-trend signals

        # Threshold gate
        if abs(weighted) < ENTRY_THRESHOLD:
            return CombinedSignal(
                direction=0, confidence=0.0,
                trend_score=t_eff, mean_rev_score=mr_eff, breakout_score=b_eff,
                dominant_strategy="below_threshold",
                reasons=[f"Score {weighted:.3f} < threshold {ENTRY_THRESHOLD}"],
                entry_price=current_price,
            )

        direction = 1 if weighted > 0 else -1
        confidence = min(abs(weighted), 1.0)

        # Dominant strategy
        contribs = [
            ("trend", abs(t_eff * w_trend)),
            ("mean_rev", abs(mr_eff * w_mr)),
            ("breakout", abs(b_eff * w_break)),
        ]
        dominant = max(contribs, key=lambda x: x[1])[0]

        reasons = [
            f"Regime={regime} ADX={adx_value:.1f}",
            f"Trend: dir={trend_sig.direction} str={trend_sig.strength:.2f} ({trend_sig.reason})",
            f"MeanRev: dir={mr_sig.direction} str={mr_sig.strength:.2f} ({mr_sig.reason})",
            f"Breakout: dir={break_sig.direction} str={break_sig.strength:.2f} ({break_sig.reason})",
            f"WeightedScore={weighted:.3f} confidence={confidence:.2f}",
        ]

        return CombinedSignal(
            direction=direction,
            confidence=confidence,
            trend_score=t_eff,
            mean_rev_score=mr_eff,
            breakout_score=b_eff,
            dominant_strategy=dominant,
            reasons=reasons,
            entry_price=current_price,
        )
