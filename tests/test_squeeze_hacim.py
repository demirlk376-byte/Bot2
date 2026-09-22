"""
Squeeze hacim kapisi.

Bu kol hacme HIC bakmiyordu. Donchian'da olculdu: dusuk hacimli kirilim sahte
cikma egiliminde ve hacim esigi TEST MAR'i 1.47 -> 3.64 yapti. Squeeze de bir
KIRILIM kolu (sikismadan cikis), ayni mantik gecerli OLABILIR -- ama sinanmadi.

EN ONEMLI TEST ILK SIRADA: varsayilan (vol_mult=0) ile davranis DEGISMEMELI.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.squeeze import SqueezeStrategy


def _veri(n=600, hacim=None):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol).iloc[:n]
    d.index = pd.to_datetime(d["ts"], utc=True)
    d = d[["open", "high", "low", "close", "volume"]].astype("float64")
    if hacim is not None:
        d["volume"] = hacim
    return d


def _pencereler(d, adim=1):
    for i in range(200, len(d), adim):
        alt = d.iloc[: i + 1]
        tr = pd.concat([alt.high - alt.low,
                        (alt.high - alt.close.shift(1)).abs(),
                        (alt.low - alt.close.shift(1)).abs()], axis=1).max(axis=1)
        yield alt, float(tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1])


def test_VARSAYILAN_davranis_degismez():
    """⚠ vol_mult=0 -> kol hacme hic bakmamali, eski haliyle BIREBIR ayni."""
    d = _veri()
    a, b = SqueezeStrategy(), SqueezeStrategy(vol_mult=0.0)
    n = 0
    for alt, atr in _pencereler(d, adim=2):
        sa, sb = a.analyze(alt, atr), b.analyze(alt, atr)
        assert sa.direction == sb.direction
        assert sa.sl_price == pytest.approx(sb.sl_price)
        n += sa.direction != 0
    assert n > 0, "karsilastirma icin sinyal yok"


def test_imkansiz_esik_hepsini_eler():
    d = _veri()
    s = SqueezeStrategy(vol_mult=1000.0)
    for alt, atr in _pencereler(d, adim=5):
        assert s.analyze(alt, atr).direction == 0


def test_duz_hacimde_esik_1_ustu_hepsini_eler_1_alti_hicbirini():
    """Hacim sabitse oran her zaman 1.0 -> esik 1.01 hepsini eler, 0.99 hicbirini."""
    d = _veri(hacim=np.full(600, 1000.0))
    taban = SqueezeStrategy()
    ustu, alti = SqueezeStrategy(vol_mult=1.01), SqueezeStrategy(vol_mult=0.99)
    t = 0
    for alt, atr in _pencereler(d, adim=3):
        t += taban.analyze(alt, atr).direction != 0
        assert ustu.analyze(alt, atr).direction == 0, "esik ustu elemeliydi"
        assert alti.analyze(alt, atr).direction == taban.analyze(alt, atr).direction
    assert t > 0, "duz hacimli veride sinyal yok -- test anlamsiz"


def test_hacim_sutunu_yoksa_sinyal_uretmez():
    """Veri eksikse SESSIZCE gecmemeli -- filtre acikken hacim sarttir."""
    d = _veri().drop(columns=["volume"])
    s = SqueezeStrategy(vol_mult=1.5)
    for alt, atr in _pencereler(d, adim=10):
        sig = s.analyze(alt, atr)
        assert sig.direction == 0
