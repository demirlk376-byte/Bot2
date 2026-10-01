"""
Gösterge sözleşmesi (şartname §4):
  EMA200: alpha=2/201, EMA[0]=close[0], EMA[i]=alpha*close[i]+(1-alpha)*EMA[i-1]
  TR[0]=high[0]-low[0]; TR[i]=max(h-l, |h-c[i-1]|, |l-c[i-1]|)
  ATR14: ATR[0]=TR[0]; ATR[i]=TR[i]/14 + ATR[i-1]*13/14   (ilk TR tohumu; 14-ortalama tohumu DEĞİL)

Repodaki indicators.ema / indicators.atr bu sözleşmenin aynısıdır (ewm adjust=False, span=200 /
alpha=1/14, ilk değerle tohumlu) — eşitlik testte gösterilir. Fark yalnız EKSİK BAR işleyişi:
ızgarada eksik bar NaN'dır; özyineleme yalnız geçerli barlar üzerinden ilerler (TR, bir önceki
GEÇERLİ kapanışı kullanır), eksik barın gösterge değeri NaN'dır. Böylece veri doldurulmaz.
"""
from __future__ import annotations

import numpy as np


def ema(close: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(close), np.nan)
    a = 2.0 / (period + 1)
    prev = None
    for i in range(len(close)):
        x = close[i]
        if not np.isfinite(x):
            continue
        prev = x if prev is None else a * x + (1 - a) * prev
        out[i] = prev
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(close), np.nan)
    prev_atr = None
    prev_c = None
    k = 1.0 / period
    for i in range(len(close)):
        h, l, c = high[i], low[i], close[i]
        if not (np.isfinite(h) and np.isfinite(l) and np.isfinite(c)):
            continue
        tr = h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
        prev_atr = tr if prev_atr is None else tr * k + prev_atr * (1 - k)
        out[i] = prev_atr
        prev_c = c
    return out


def valid_count(valid: np.ndarray) -> np.ndarray:
    """i. bar dahil o ana kadar tamamlanmış geçerli bar sayısı."""
    return np.cumsum(valid.astype(np.int64))


def usable(x) -> bool:
    return x is not None and np.isfinite(x) and x > 0
