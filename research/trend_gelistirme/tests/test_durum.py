"""B0 durum eşdeğerliği: toplu ↔ adım adım ↔ kaydet/yükle ↔ veri kesilmiş (gelecek sızıntısı yok)."""
import copy, pickle
import pandas as pd
import pytest
from research.liquidity_sweep_v1 import config as C
from research.trend_gelistirme.motor import Motor
from research.trend_gelistirme.veri import yukle

ms = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
COINS = ["ETH", "SOL", "XRP", "DOGE"]
T0, T1, KES = ms("2021-01-01"), ms("2022-06-01"), ms("2021-10-01")


def ozet(m):
    return ([(x["coin"], x["giris_t"], x["cikis_t"], x["neden"], round(x["pnl"], 6)) for x in m.islemler],
            [(t, round(v, 6)) for t, v, *_ in m.seri],
            {k: (p.giris_t, round(p.stop, 9), len(p.lots), dict(p.bekleyen)) for k, p in m.poz.items()},
            dict(m.bek_giris))


@pytest.fixture(scope="module")
def veri():
    return yukle(COINS)[0]


@pytest.mark.parametrize("v", ["B0", "B1", "B2", "B3"])
def test_toplu_adim_kaydet_ayni(veri, v):
    a = Motor(veri, "ETH", v, C.TWIN_MARKET_PROFILE, t_bas=T0, t_bit=T1).kos()
    b = Motor(veri, "ETH", v, C.TWIN_MARKET_PROFILE, t_bas=T0, t_bit=T1)
    yarim = len(b.saat) // 2
    b.kos(yarim)
    b = pickle.loads(pickle.dumps(b))          # kaydet → yükle
    for i in range(yarim, len(b.saat)):        # mum mum
        b.kos(i + 1)
    assert ozet(a) == ozet(b)


def test_veri_kesilince_gecmis_ayni(veri):
    tam = Motor(veri, "ETH", "B0", C.TWIN_MARKET_PROFILE, t_bas=T0, t_bit=T1).kos()
    kesik_veri = yukle(COINS, kesim=KES)[0]
    kes = Motor(kesik_veri, "ETH", "B0", C.TWIN_MARKET_PROFILE, t_bas=T0, t_bit=KES).kos()
    a = [x for x in tam.islemler if x["cikis_t"] <= KES - 4 * 3_600_000]
    b = [x for x in kes.islemler if x["cikis_t"] <= KES - 4 * 3_600_000]
    assert [(x["coin"], x["giris_t"], x["cikis_t"], round(x["pnl"], 6)) for x in a] == \
           [(x["coin"], x["giris_t"], x["cikis_t"], round(x["pnl"], 6)) for x in b]
    sa = [(t, round(v, 6)) for t, v, *_ in tam.seri if t <= KES]
    sb = [(t, round(v, 6)) for t, v, *_ in kes.seri if t <= KES]
    assert sa == sb


def test_cakisma_yok_ve_rejim_bilinmezse_giris_yok(veri):
    m = Motor(veri, "ETH", "B0", C.TWIN_MARKET_PROFILE, t_bas=T0, t_bit=T1).kos()
    acik = {}
    for x in sorted(m.islemler, key=lambda x: x["giris_t"]):
        assert acik.get(x["coin"], -1) <= x["giris_t"], "aynı coinde çakışan iki trend pozisyonu"
        acik[x["coin"]] = x["cikis_t"]
        g = x["giris_t"]
        assert m._rejim(g) is not None
    # ETH rejimi bilinmeyen dönemde (SMA200 dolmadan) giriş olmamalı: rejimi tamamen sil → işlem yok
    m2 = Motor(veri, "ETH", "B0", C.TWIN_MARKET_PROFILE, t_bas=T0, t_bit=T1)
    m2.rejim = {}
    m2.kos()
    assert m2.islemler == [] and not m2.poz
