from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class SRLevel:
    price: float
    touches: int
    level_type: str  # 'support' | 'resistance'


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=high.index)
    minus_dm_s = pd.Series(minus_dm, index=high.index)

    atr_s = atr(high, low, close, period)

    plus_di = 100 * plus_dm_s.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm_s.ewm(alpha=1 / period, adjust=False).mean() / atr_s

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(period).mean()


def is_volume_spike(
    volume: pd.Series, period: int = 20, multiplier: float = 1.5
) -> pd.Series:
    avg = volume_sma(volume, period)
    return volume > avg * multiplier


def find_sr_levels(
    df: pd.DataFrame,
    lookback: int = 50,
    min_touches: int = 2,
    tolerance_pct: float = 0.002,
) -> list[SRLevel]:
    data = df.tail(lookback)
    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values

    swing_highs: list[float] = []
    swing_lows: list[float] = []

    for i in range(2, len(data) - 2):
        if highs[i] >= highs[i - 1] and highs[i] >= highs[i - 2] and \
           highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
            swing_highs.append(highs[i])
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and \
           lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            swing_lows.append(lows[i])

    current_price = closes[-1]

    def cluster_levels(raw: list[float], level_type: str) -> list[SRLevel]:
        if not raw:
            return []
        raw_sorted = sorted(raw)
        clusters: list[list[float]] = []
        for price in raw_sorted:
            placed = False
            for cluster in clusters:
                center = sum(cluster) / len(cluster)
                if abs(price - center) / center <= tolerance_pct:
                    cluster.append(price)
                    placed = True
                    break
            if not placed:
                clusters.append([price])

        result = []
        for cluster in clusters:
            if len(cluster) >= min_touches:
                center = sum(cluster) / len(cluster)
                result.append(SRLevel(price=center, touches=len(cluster), level_type=level_type))
        return result

    # Include all levels within ±8% of current price regardless of which side they're on.
    # The current-price filter was a bug: resistance levels above current price were
    # immediately excluded the moment price broke through them, making breakout detection impossible.
    price_range = current_price * 0.08
    resistances = cluster_levels(
        [h for h in swing_highs if abs(h - current_price) <= price_range], "resistance"
    )
    supports = cluster_levels(
        [lo for lo in swing_lows if abs(lo - current_price) <= price_range], "support"
    )

    return resistances + supports


def bb_width(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    upper, middle, lower = bollinger_bands(close, period, std_dev)
    return (upper - lower) / middle


def is_bb_squeeze(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> bool:
    width = bb_width(close, period, std_dev)
    if len(width.dropna()) < period:
        return False
    current_width = width.iloc[-1]
    avg_width = width.tail(period).mean()
    return current_width < avg_width * 0.7
