"""KRONOS kolları. Her kol bir Besleme sarar ve YALNIZCA pencere(i) üzerinden karar verir.

NEDENSELLİK: göstergeler Besleme'nin TUTTUĞU seriden hesaplanır. Veri T'de kesilirse
göstergeler de kesilmiş seriden yeniden hesaplanır — bu yüzden kronos_test.py'nin
kesme testi yalnız sinyal mantığını değil, GÖSTERGE nedenselliğini de sınar.
(Merkezli rolling, ileriye bakan resample, ffill-with-future gibi sızıntılar yakalanır.)

Sinyal kuralları deployed_backtest.gen()/gen_bb() ile BİREBİR aynıdır; denklik
kronos_test.py ile kanıtlanır.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from .motor import Besleme


class Kol:
    """Arayüz. Yeni bir strateji eklemek = bu sınıftan türetip sinyal() yazmak."""
    ad = "?"; oncelik = 99

    def __init__(self, coin: str, sira: int = 0):
        self.coin = coin; self.sira = sira

    def sinyal(self, i: int):
        """→ (yon, sld, rr, mh) veya None.  pencere(i) DIŞINA ÇIKMAK YASAK."""
        raise NotImplementedError


def _ham(coin, src, kadar=None):
    m = fast_bt.load(coin, source=src)
    if kadar is not None:
        m = m[m.index <= kadar]
    return m


# ───────────────────────────── DONCHIAN ─────────────────────────────
class DonchianKol(Kol):
    ad = "donchian"; oncelik = 0

    def __init__(self, coin, src="local", sira=0, kadar=None,
                 kanal=40, sl_atr=2.0, rr=2.0, ema_trend=200, tampon=0.0):
        super().__init__(coin, sira)
        from strategies.donchian import DonchianStrategy
        tf, self.win, self.sl_a, self.rr, self.mh = ("4h", 259, sl_atr, 2.5, 30)
        d = fast_bt.resample(_ham(coin, src, kadar), tf)
        self.besleme = Besleme(d)
        self.s = DonchianStrategy(channel=kanal, rr=rr, sl_atr=sl_atr,
                                  ema_trend=ema_trend, buffer_atr=tampon)
        # göstergeler: NEDENSEL (rolling/ewm/shift) — kesme testiyle doğrulanır
        self._atr = atr_fn(d["high"], d["low"], d["close"], 14).values
        _dc = d["close"].resample("1D").last().dropna()
        _dp = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
        self._up = d["close"].values > _dp

    def sinyal(self, i):
        if i < 260 or i >= self.besleme.n - 1: return None
        a = self._atr[i]
        if not np.isfinite(a) or a <= 0: return None
        d_ = self.s.analyze(self.besleme.pencere(i, self.win + 1), float(a)).direction
        if d_ == 0: return None
        u = self._up[i]
        dup = bool(u) if not (isinstance(u, float) and np.isnan(u)) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): return None
        return d_, self.sl_a * a, self.rr, self.mh


# ───────────────────────────── SQUEEZE ─────────────────────────────
class SqueezeKol(Kol):
    ad = "squeeze"; oncelik = 1

    def __init__(self, coin, src="local", sira=0, kadar=None):
        super().__init__(coin, sira)
        from strategies.squeeze import SqueezeStrategy
        tf, self.win, self.sl_a, self.rr, self.mh = ("1h", 119, 2.0, 2.5, 48)
        d = fast_bt.resample(_ham(coin, src, kadar), tf)
        self.besleme = Besleme(d)
        self.s = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0,
                                 rr=2.5, mtf_filter=True)
        self._atr = atr_fn(d["high"], d["low"], d["close"], 14).values
        self._adx = adx_fn(d["high"], d["low"], d["close"], 14).values
        _dc = d["close"].resample("1D").last().dropna()
        _dp = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
        self._up = d["close"].values > _dp

    def sinyal(self, i):
        if i < 260 or i >= self.besleme.n - 1: return None
        a = self._atr[i]
        if not np.isfinite(a) or a <= 0: return None
        x = self._adx[i] if np.isfinite(self._adx[i]) else 20.0
        if x <= 20.0: return None
        d_ = self.s.analyze(self.besleme.pencere(i, self.win + 1), float(a)).direction
        if d_ == 0: return None
        return d_, self.sl_a * a, self.rr, self.mh


# ───────────────────────────── BB / MEAN-REV ─────────────────────────────
class BbKol(Kol):
    ad = "bb"; oncelik = 2

    def __init__(self, coin, src="local", sira=0, kadar=None):
        super().__init__(coin, sira)
        from indicators import bollinger_bands
        from strategies.mean_reversion import MeanReversionStrategy
        from config import load_config
        self.sl_a, self.rr, self.mh, self.adx_max = 3.0, 1.667, 48, 28.0
        d = fast_bt.resample(_ham(coin, src, kadar), "1h")
        self.besleme = Besleme(d)
        self.s = MeanReversionStrategy(load_config().strategy)
        ub, _m, lb = bollinger_bands(d["close"], 20, 2.0)
        cl = d["close"].values
        self._dis = (cl < lb.values) | (cl > ub.values)
        vma = d["volume"].rolling(20).mean().values
        self._vok = ~(np.isfinite(vma) & (d["volume"].values < vma))
        self._wd = d.index.weekday

    def sinyal(self, i):
        if i < 260 or i >= self.besleme.n - 1: return None
        if not (self._dis[i] and self._vok[i]): return None
        if self._wd[i] < 5: return None                       # YALNIZ hafta sonu
        sub = self.besleme.pencere(i, 120)                    # canlı get_candles(120)
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0: return None
        ax = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(ax) if np.isfinite(ax) else 20.0) >= self.adx_max: return None
        d_ = self.s.analyze(sub).direction
        if d_ == 0: return None
        return d_, self.sl_a * float(av), self.rr, self.mh


# ───────────────────────── hazır kurulum ─────────────────────────
def canli_kollar(src="local", kadar=None):
    """deployed_backtest'in canlı konfigürasyonu: donchian7 + squeeze4 + bb/LTC."""
    import deployed_backtest as A
    ks = []
    for n, c in enumerate(A.DONCH): ks.append(DonchianKol(c, src, n, kadar))
    for n, c in enumerate(A.SQZ):   ks.append(SqueezeKol(c, src, n, kadar))
    for n, c in enumerate(A.BB_COINS): ks.append(BbKol(c, src, n, kadar))
    return ks


def funding_yukle(coinler=None, tercih="bnc"):
    """{coin: pd.Series(rate, index=UTC dt)} — Binance tam kapsam (*_funding_bnc.csv),
    yoksa MEXC kısmi (*_funding.csv). Kapsam dışı coin sessizce ATLANMAZ: uyarı basar."""
    import glob, os
    out = {}
    for f in sorted(glob.glob("/home/user/Bot2/data/*_funding*.csv")):
        b = os.path.basename(f)
        coin = b.split("_funding")[0]
        bnc = b.endswith("_bnc.csv")
        if coin in out and not bnc: continue          # bnc tercih edilir
        if coinler and coin not in coinler: continue
        d = pd.read_csv(f)
        ix = pd.to_datetime(d["dt"], utc=True, format="mixed")
        d = pd.Series(d["rate"].values, index=ix).sort_index()
        out[coin] = d
    if coinler:
        eksik = [c for c in coinler if c not in out]
        if eksik: print(f"  ⚠ funding verisi YOK: {eksik} → bu coinlerde funding SIFIR sayılır")
    return out
