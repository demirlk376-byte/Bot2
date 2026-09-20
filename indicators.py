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


# ──────────────────────────────────────────────────────────────────────────
# ⚠ rsi/atr/adx HIZLANDIRILDI, HESABI DEGISMEDI (2026-09-20).
#
# Profil: 20 gunluk ikiz kosusunda adx 26.3s, rsi 20.4s, yani toplam surenin
# yarisi. Ama harcanan sure MATEMATIK degildi -- numpy'nin asil hesabi 1.1s,
# geri kalani pandas nesne yuku (Series.__init__ 332 bin cagri, __finalize__
# 883 bin). Tampon 260 mumla sinirli, yani diziler minik; her ara adimda bir
# Series kurmak hesabin kendisinden pahaliya geliyordu.
#
# COZUM: elemanlar arasi islemler numpy'da, `ewm` AYNEN pandas'ta. ewm asil
# ustel yumusatmayi C'de yapiyor ve onun kendine ozgu NaN/yuvarlama davranisi
# var; yeniden yazmak sonucu son bitte kaydirabilirdi. Boylece Series sayisi
# indikator basina ~12'den 1-2'ye dusuyor, sonuc BIT DUZEYINDE ayni kaliyor.
#
# Bunu iddia degil TEST soyluyor: tests/test_indicators_hiz.py eski surumleri
# referans tutup gercek BTC verisinde TAM ESITLIK ariyor (NaN'lar ayni yerde,
# sayilar son bite kadar ayni). Tek bit saparsa test duser.
# ──────────────────────────────────────────────────────────────────────────

def _dizi(s: pd.Series) -> np.ndarray:
    return np.asarray(s, dtype="float64")


def _ewm(arr: np.ndarray, period: int) -> np.ndarray:
    """pandas'in ewm(alpha=1/period, adjust=False).mean() hesabi -- AYNEN.

    Indeks verilmiyor: ewm indeksi kullanmiyor, varsayilan RangeIndex kurmak
    gercek indeksi kopyalamaktan ucuz."""
    return pd.Series(arr).ewm(alpha=1 / period, adjust=False).mean().to_numpy()


def _geri_kaydir(a: np.ndarray) -> np.ndarray:
    """Series.shift(1) karsiligi: bas NaN, kalan bir saga kayik."""
    out = np.empty_like(a)
    out[0] = np.nan
    out[1:] = a[:-1]
    return out


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    c = _dizi(close)
    delta = c - _geri_kaydir(c)
    # clip(lower=0) / -clip(upper=0) karsiligi; NaN her ikisinde de NaN kalir
    gain = np.maximum(delta, 0.0)
    loss = -np.minimum(delta, 0.0)
    avg_gain = _ewm(gain, period)
    avg_loss = _ewm(loss, period)
    rs = avg_gain / np.where(avg_loss == 0.0, np.nan, avg_loss)
    out = 100 - (100 / (1 + rs))
    # Zero-loss window (unbroken up-run) → RSI = 100, not NaN. Otherwise the
    # strongest-momentum candles — exactly where the overbought guard should
    # bite — get a NaN RSI that silently bypasses the extreme-RSI filters.
    out = np.where(avg_loss != 0.0, out, 100.0)
    # Flat window (no gain AND no loss) → neutral 50, not 100.
    out = np.where((avg_gain == 0.0) & (avg_loss == 0.0), 50.0, out)
    return pd.Series(out, index=close.index)


def _atr_dizi(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int) -> np.ndarray:
    prev_close = _geri_kaydir(c)
    # concat(...).max(axis=1) skipna=True ile calisiyordu: ilk satirda kaydirma
    # kaynakli NaN'lar atlanip h-l aliniyordu. np.fmax de NaN'i atlar.
    tr = np.fmax(np.fmax(h - l, np.abs(h - prev_close)), np.abs(l - prev_close))
    return _ewm(tr, period)


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    return pd.Series(
        _atr_dizi(_dizi(high), _dizi(low), _dizi(close), period),
        index=close.index,
    )


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    h, l, c = _dizi(high), _dizi(low), _dizi(close)

    up_move = h - _geri_kaydir(h)
    down_move = _geri_kaydir(l) - l

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr_v = _atr_dizi(h, l, c, period)

    plus_di = 100 * _ewm(plus_dm, period) / atr_v
    minus_di = 100 * _ewm(minus_dm, period) / atr_v

    toplam = plus_di + minus_di
    dx = 100 * np.abs(plus_di - minus_di) / np.where(toplam == 0.0, np.nan, toplam)
    return pd.Series(_ewm(dx, period), index=close.index)


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
    if len(width.dropna()) < period + 1:
        return False
    current_width = width.iloc[-1]
    # Baseline EXCLUDES the current bar — including the value being tested in its
    # own comparison average biases the threshold and makes the squeeze fire too
    # rarely.
    avg_width = width.iloc[-period - 1:-1].mean()
    return current_width < avg_width * 0.7


def vwap(
    high: pd.Series, low: pd.Series, close: pd.Series,
    volume: pd.Series, period: int = 24,
) -> pd.Series:
    """Rolling VWAP over `period` candles (typical price weighted by volume)."""
    typical = (high + low + close) / 3
    tpv = typical * volume
    return tpv.rolling(period).sum() / volume.rolling(period).sum()


def atr_percentile(
    high: pd.Series, low: pd.Series, close: pd.Series,
    atr_period: int = 14, lookback: int = 50,
) -> pd.Series:
    """Percentile rank (0-100) of current ATR vs last `lookback` bars."""
    atr_series = atr(high, low, close, atr_period)
    def _rank(window):
        if len(window) < 2:
            return 50.0
        return float((window[:-1] < window[-1]).sum() / (len(window) - 1) * 100)
    return atr_series.rolling(lookback + 1).apply(_rank, raw=True)
