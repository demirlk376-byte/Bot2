"""SWEEP_V2 filtre birim testleri (sentetik; ağ yok)."""
import types
import numpy as np
from research.liquidity_sweep_v1 import config as C
from research.sweep_v2 import kos as K


def _r(side="LONG", t=1_700_000_000_000):
    return types.SimpleNamespace(side=side, signal_time=t, symbol="X", sweep_open=t - C.M15)


def test_seans_saatleri():
    gun = 1_699_920_000_000                     # UTC gün başı
    ek = K.Ek.__new__(K.Ek)
    assert not ek.seans_ok(_r(t=gun + 6 * C.H1 + 59 * C.MIN))
    assert ek.seans_ok(_r(t=gun + 7 * C.H1))
    assert ek.seans_ok(_r(t=gun + 20 * C.H1 + 55 * C.MIN))
    assert not ek.seans_ok(_r(t=gun + 21 * C.H1))


def test_son_kayit_gecikme_ve_gelecek_yok():
    import pandas as pd
    df = pd.DataFrame({"t_kapanis": [1000, 2000, 3000]})
    assert K.Ek._son(df, "t_kapanis", 2500, 600) == 1          # 2000 ≤ 2500
    assert K.Ek._son(df, "t_kapanis", 2999, 100) is None       # çok eski (gecikme > 100)
    assert K.Ek._son(df, "t_kapanis", 500, 10_000) is None      # öncesi yok → gelecek kullanılmaz
