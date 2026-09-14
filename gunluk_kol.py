"""
gunluk_kol.py — 1D (GÜNLÜK BAR) YAVAŞ TREND KOLU, KRONOS `Kol`u olarak.

NEDEN YENİDEN YAZILDI: kol 2026-09-12'de ayri_havuz.py + ayri_aile.py ile
ölçüldü ve AİLE TESTİ'nde reddedildi — ama o ölçümde FUNDING YOKTU. Kol ~24 gün
tutuyor (kitap ~2 gün); 8 saatte bir ödenen funding bu horizonda kitabınkinin
~12 katı. Bu dosya kolu KRONOS'un nedensellik zırhının ARKASINA taşır, böylece
funding motorun kendi `_funding_R` yoluyla (kitapla BİREBİR aynı formül,
Σrate/sl_pct) R'den düşülür.

SİNYAL KURALI daily_trend_test.gen_daily ile birebir:
  · kanal = ÖNCEKİ ch günün hi max / lo min  (mevcut bar HARİÇ: rolling+shift(1))
  · long : close > kanal_üst VE close > EMA(esp)
  · short: close < kanal_alt  VE close < EMA(esp)
  · SL = sl_a*ATR14, TP = rr*SL, max-hold = mh GÜN
  · ısınma = max(esp, ch+2), son bar (n-1) sinyal ÜRETMEZ
Denklik `gunluk_test.py` T0 ile kanıtlanır; nedensellik aynı dosyanın T2'siyle
(veri 3 tarihte kesilir, önceki kararlar birebir aynı kalmalı).

ÜRETİM KODUNA DOKUNULMADI: kronos/ altı ve main/execution/... değişmedi.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import fast_bt
from indicators import atr as atr_fn, ema as ema_fn
from kronos.motor import Besleme
from kronos.kollar import Kol, _ham


def gunluk_veri(coin, src="local", kadar=None):
    """1h önbellekten GÜNLÜK bar. `kadar` verilirse HAM veri orada kesilir —
    kesme testi göstergeleri de kesik seriden yeniden hesaplatır."""
    return fast_bt.resample(_ham(coin, src, kadar), "1D")


class GunlukKol(Kol):
    ad = "gunluk"; oncelik = 3

    def __init__(self, coin, src="local", sira=0, kadar=None,
                 ch=50, esp=200, sl_a=2.0, rr=3.0, mh=40, d=None):
        super().__init__(coin, sira)
        self.sl_a, self.rr, self.mh = float(sl_a), float(rr), int(mh)
        self.ch, self.esp = int(ch), int(esp)
        if d is None:
            d = gunluk_veri(coin, src, kadar)
        self.besleme = Besleme(d)
        # göstergeler: HEPSİ nedensel (ewm / rolling+shift(1)) ve Besleme'nin
        # TUTTUĞU seriden — veri kesilirse bunlar da kesik seriden doğar.
        self._atr = atr_fn(d["high"], d["low"], d["close"], 14).values
        self._ema = ema_fn(d["close"], self.esp).values
        self._rh = d["high"].rolling(self.ch).max().shift(1).values
        self._rl = d["low"].rolling(self.ch).min().shift(1).values
        self.warm = max(self.esp, self.ch + 2)

    def sinyal(self, i):
        if i < self.warm or i >= self.besleme.n - 1:
            return None
        a = self._atr[i]
        if not np.isfinite(a) or a <= 0:
            return None
        H, L, ev = self._rh[i], self._rl[i], self._ema[i]
        if not (np.isfinite(H) and np.isfinite(L) and H > L and np.isfinite(ev)):
            return None
        c = self.besleme.bar(i)[2]                 # i DAHİL, i+1 ASLA
        if c > H and c > ev:   d_ = 1
        elif c < L and c < ev: d_ = -1
        else: return None
        return d_, self.sl_a * a, self.rr, self.mh


def gunluk_kollar(coinler, src="local", kadar=None, ch=50, esp=200,
                  sl_a=2.0, rr=3.0, mh=40, onbellek=None):
    """onbellek = {coin: günlük DataFrame} → 270 kombinasyonluk taramada
    resample'ı bir kez yapıp tekrar tekrar kullanmak için."""
    ks = []
    for n, c in enumerate(coinler):
        d = None if onbellek is None else onbellek[c]
        ks.append(GunlukKol(c, src, n, kadar, ch, esp, sl_a, rr, mh, d))
    return ks
