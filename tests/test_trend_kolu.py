"""trend_kolu (saf mantık) ve trend_canli (sinyal modu) testleri — ağ yok, emir yok."""
import asyncio
import importlib
import json
import os

import numpy as np
import pandas as pd
import pytest

import trend_kolu as TK

T0 = 1_577_836_800_000  # 2020-01-01


def bars(closes, ms=TK.DAY_MS, spread=1.0):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"t": T0 + np.arange(len(c)) * ms, "open": o, "high": np.maximum(o, c) + spread,
                         "low": np.minimum(o, c) - spread, "close": c})


def yukselis(n_duz=80, up=60, down=40):
    return [100.0] * n_duz + [100 + 2 * i for i in range(1, up + 1)] + [220 - 4 * i for i in range(1, down + 1)]


def test_kirilim_ertesi_acilista_giris_ve_iz_suren_stopla_cikis():
    d = TK.Defter()
    b = bars(yukselis())
    ol = d.mum_isle("AAA", "1D", b, {})
    tur = [o.tur for o in ol]
    assert tur[0] == "GIRIS_SINYALI" and tur[1] == "GIRIS"
    g = next(o for o in ol if o.tur == "GIRIS")
    assert g.t == b.t[81]                      # kırılım 80. mumda (101 > 100+1 tepesi değil → ilk gerçek kırılım)
    assert "CIKIS" in tur and d.kapanan[0]["R"] > 3
    assert d.kapanan[0]["ekler"] == 2           # +2R ve +4R'de iki ek


def test_ayni_mum_iki_kez_islenmez_ve_durum_json_dongusu():
    d = TK.Defter()
    b = bars(yukselis(up=30, down=0))
    d.mum_isle("AAA", "1D", b, {})
    d2 = TK.Defter.yukle(json.loads(json.dumps(d.durum())))
    assert d2.mum_isle("AAA", "1D", b, {}) == []          # yeni mum yok → olay yok
    assert d2.poz.keys() == d.poz.keys()


def test_eth_rejimi_kapaliyken_giris_yok():
    b = bars(yukselis())
    kapali = {int(t): False for t in b.t}
    d = TK.Defter()
    assert not [o for o in d.mum_isle("AAA", "1D", b, kapali) if o.tur.startswith("GIRIS")]


def test_coin_basina_tek_pozisyon_iki_modul():
    d = TK.Defter()
    b1 = bars(yukselis())
    d.mum_isle("AAA", "1D", b1, {})
    assert "AAA" in d.poz or d.kapanan
    b4 = bars([100.0] * 200 + [100 + i for i in range(1, 50)], ms=TK.H4_MS)
    # 1D pozisyonu açıkken (aynı zaman dilimi değil ama defter tek pozisyon tutar) 4H girişi açılmaz
    if "AAA" in d.poz:
        assert not [o for o in d.mum_isle("AAA", "4H", b4, {}) if o.tur == "GIRIS"]


def test_erken_cikis_tutmayan_kirilim():
    c = [100.0] * 80 + [103.0] + [103.0] * 30
    d = TK.Defter()
    d.mum_isle("AAA", "1D", bars(c, spread=0.5), {})
    assert d.kapanan and d.kapanan[0]["neden"] == "ERKEN_ÇIKIŞ"


def test_gunluk_4h_den_yalniz_tam_gunler():
    b4 = bars(list(range(1, 20)), ms=TK.H4_MS)           # 19 mum = 3 tam gün + 1 eksik
    g = TK.gunluk_4h_den(b4)
    assert len(g) == 3 and g.close.iloc[0] == 6 and g.high.iloc[1] == 12 + 1


def test_trend_canli_kapaliyken_hicbir_sey_yapmaz(monkeypatch):
    monkeypatch.setenv("TREND_MODE", "kapali")
    import trend_canli
    importlib.reload(trend_canli)
    assert trend_canli.AKTIF is False
    trend_canli.tetikle(pd.Timestamp("2026-01-01 03:00", tz="UTC"), None, [], None, None)   # istisna yok, görev yok
    assert not trend_canli._gorevler


def test_trend_canli_sinyal_modu_sahte_borsayla(monkeypatch, tmp_path):
    monkeypatch.setenv("TREND_MODE", "sinyal")
    monkeypatch.setenv("TREND_DURUM_DOSYASI", str(tmp_path / "durum.json"))
    import trend_canli
    importlib.reload(trend_canli)
    simdi = 1_800_000_000_000
    n = 700
    t = (simdi // TK.H4_MS) * TK.H4_MS - np.arange(n)[::-1] * TK.H4_MS - TK.H4_MS
    fiyat = np.r_[np.full(500, 100.0), 100 + np.arange(1, 201) * 0.5]

    class Sahte:
        emir = 0

        async def fetch_ohlcv(self, sym, tf, since, limit):
            assert tf == "4h"
            m = t >= (since or 0)
            idx = np.flatnonzero(m)[:limit]
            return [[int(t[i]), fiyat[i], fiyat[i] + 1, fiyat[i] - 1, fiyat[i], 1.0] for i in idx]

        async def create_order(self, *a, **k):   # çağrılırsa test düşer
            Sahte.emir += 1
            raise AssertionError("sinyal modunda emir gönderilmemeli")

    monkeypatch.setattr(trend_canli.time, "time", lambda: simdi / 1000)
    mesajlar = []

    async def gonder(m):
        mesajlar.append(m)

    async def ozs():
        return 1000.0

    asyncio.run(trend_canli._calistir(Sahte(), ["AAA/USDT:USDT", "ETH/USDT:USDT"], gonder, ozs))
    assert mesajlar and "sinyal modu" in mesajlar[0]
    assert os.path.exists(tmp_path / "durum.json") and Sahte.emir == 0
