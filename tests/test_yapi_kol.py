"""
YapiStrategy — main.py'nin cagirdigi, bar bar calisan URETIM kolu.

EN ONEMLI TEST ILK SIRADA: kol VARSAYILAN KAPALI. Acilmadikca canli
davranis bit bit ayni kalmali.

Ikinci onemli grup: BEKLEME MANTIGI. Bekleme borsada degil burada, cunku
PaperExchange duran limit emrini modellemiyor (cagrildigi anda dolduruyor).
Bu yuzden "ayni barda dolmaz", "suresi dolunca iptal", "kesintide temizle"
kurallari BU KOLUN dogrulugunun tamamidir.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.yapi import YapiStrategy


def _veri(n=4000):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    d = d[["open", "high", "low", "close"]].astype("float64").iloc[:n]
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift(1)).abs(),
                    (d.low - d.close.shift(1)).abs()], axis=1).max(axis=1)
    return d, tr.ewm(alpha=1 / 14, adjust=False).mean()


def _tara(s, d, atr, pencere=400, bas=300):
    cikti = []
    for i in range(bas, len(d)):
        sig = s.analyze(d.iloc[max(0, i - pencere + 1): i + 1], float(atr.iloc[i]))
        if sig.direction:
            cikti.append((i, sig.direction, round(sig.entry_price, 6),
                          round(sig.sl_price, 6), round(sig.tp_price, 6)))
    return cikti


# --------------------------------------------------------------------------
# VARSAYILAN KAPALI
# --------------------------------------------------------------------------

def test_kol_VARSAYILAN_KAPALI():
    """⚠ EN KRITIK. config varsayilani kapali olmali; acik gelseydi canli bot
    haberi olmadan yeni bir kolla islem acardi."""
    import config as C
    c = C.load_config()
    assert c.strategy.yapi_enabled is False


def test_kapaliyken_main_kol_INSA_ETMEZ():
    import config as C
    c = C.load_config()
    assert c.strategy.yapi_enabled is False
    # main.py insa kosulu: yapi_enabled -> aksi halde None
    assert (YapiStrategy() if c.strategy.yapi_enabled else None) is None


# --------------------------------------------------------------------------
# BEKLEME MANTIGI
# --------------------------------------------------------------------------

def test_kurulum_AYNI_BARDA_dolmaz():
    """MSS barinda emir konur, o barda DOLMAZ. On elemede de dolum m+1'den
    baslar; burada dolsaydi olculen modelden sapardik."""
    d, atr = _veri(1500)
    s = YapiStrategy()
    for i in range(300, len(d)):
        onceki = len(s._bekleyen)
        sig = s.analyze(d.iloc[max(0, i - 399): i + 1], float(atr.iloc[i]))
        if len(s._bekleyen) > onceki:
            # bu barda YENI kurulum kaydedildi -> ayni barda sinyal OLMAMALI
            assert sig.direction == 0, f"bar {i}: kurulum ayni barda doldu"


def test_bekleyen_emir_SURESI_DOLUNCA_iptal():
    d, atr = _veri(2000)
    az = YapiStrategy(bekle_bar=1)
    cok = YapiStrategy(bekle_bar=24)
    n_az = len(_tara(az, d, atr))
    n_cok = len(_tara(cok, d, atr))
    assert n_az < n_cok, f"bekle_bar etkisiz (az={n_az} cok={n_cok})"
    assert n_az > 0


def test_KESINTI_bekleyenleri_TEMIZLER():
    """Besleme kopukluktan sonra tum kacan mumlari doldurur ama geri cagriyi
    yalniz en yenisi icin tetikler. Bekleyen emir o arada dolmus olabilir;
    bilemedigimiz icin hepsi iptal edilmeli (fvg.py'deki ayni koruma)."""
    d, atr = _veri(1200)
    s = YapiStrategy()
    # once bir kurulum olussun
    for i in range(300, 900):
        s.analyze(d.iloc[i - 399: i + 1], float(atr.iloc[i]))
        if s._bekleyen:
            break
    assert s._bekleyen, "test icin bekleyen kurulum olusmadi"
    # simdi 50 bar ATLA (kopukluk) -> bekleyenler temizlenmeli
    j = i + 50
    s.analyze(d.iloc[j - 399: j + 1], float(atr.iloc[j]))
    assert s._bekleyen == [] or all(b["yas"] == 0 for b in s._bekleyen), \
        "kopukluktan sonra eski bekleyen emir hayatta kaldi"


def test_ayni_bar_IKI_KEZ_cagrilinca_durum_bozulmaz():
    """analyze() ayni bar icin birden fazla cagrilabilir (baska kod yollari).
    Durum yalnizca YENI barda degismeli."""
    d, atr = _veri(1000)
    s = YapiStrategy()
    for i in range(300, 700):
        s.analyze(d.iloc[i - 399: i + 1], float(atr.iloc[i]))
    once = [dict(b) for b in s._bekleyen]
    s.analyze(d.iloc[699 - 399: 700], float(atr.iloc[699]))   # AYNI bar
    assert [dict(b) for b in s._bekleyen] == once, "ayni bar durumu degistirdi"


# --------------------------------------------------------------------------
# SINYAL GEOMETRISI
# --------------------------------------------------------------------------

def test_RR_tam_2_0_ve_SL_dogru_tarafta():
    d, atr = _veri(3000)
    s = YapiStrategy()
    n = 0
    for i, yon, giris, sl, tp in _tara(s, d, atr):
        risk = abs(giris - sl)
        assert risk > 0
        assert abs(tp - giris) / risk == pytest.approx(2.0, rel=1e-6)
        if yon > 0:
            assert sl < giris < tp
        else:
            assert tp < giris < sl
        n += 1
    assert n > 20, f"yeterli sinyal yok ({n})"


def test_seviye_ATR_mesafesi_girisi_UZAKLASTIRIR():
    d, atr = _veri(2000)
    yakin = _tara(YapiStrategy(seviye_atr=0.5), d, atr)
    uzak = _tara(YapiStrategy(seviye_atr=2.0), d, atr)
    assert yakin and uzak
    # uzak seviye daha az dolar
    assert len(uzak) <= len(yakin), f"uzak={len(uzak)} yakin={len(yakin)}"


def test_TAMPON_BOYUTU_sinyali_DEGISTIRMEZ():
    """⚠ Hiz icin swingler kisa bir kuyrukta hesaplaniyor. Bu, sinyali
    degistirmemeli -- degistirseydi IKIZ ile canli ayrisirdi (tampon
    uzunluklari farkli olabilir)."""
    d, atr = _veri(2500)
    a = _tara(YapiStrategy(), d, atr, pencere=400)
    b = _tara(YapiStrategy(), d, atr, pencere=250)
    assert a == b, "tampon uzunlugu sinyali degistirdi"
    assert len(a) > 10


def test_ayni_ADAY_iki_kez_emir_DOGURMAZ():
    """⚠ Iki asamali makinede FARKLI adaylarin ardisik barlarda kirilmasi
    MESRUDUR (eski tek asamali tasarimda degildi; test onu kodluyordu, gercek
    kurali degil). Asil kural: AYNI aday (ayni kok swing, ayni yon) birden
    fazla emir dogurmamali -- dogursaydi tek bir yapiyi ust uste alirdik."""
    d, atr = _veri(2500)
    s = YapiStrategy()
    dogan = []
    for i in range(300, len(d)):
        onceki = {id(b) for b in s._bekleyen}
        s.analyze(d.iloc[i - 399: i + 1], float(atr.iloc[i]))
        for b in s._bekleyen:
            if id(b) not in onceki:
                dogan.append((i, b["yon"], round(b["sl"], 8)))
    assert len(dogan) > 20, f"yeterli emir yok ({len(dogan)})"
    # ayni (yon, sl) ikilisi = ayni kok swing'den gelen emir. mss_bar penceresi
    # icinde tekrarlamamali.
    for x in range(len(dogan)):
        for y in range(x + 1, len(dogan)):
            if dogan[y][0] - dogan[x][0] > 12:
                break
            assert dogan[x][1:] != dogan[y][1:], (
                f"ayni aday iki kez emir dogurdu: bar {dogan[x][0]} ve {dogan[y][0]}")


def test_aday_MSS_olmadan_SURESI_DOLUNCA_dusser():
    """Aday, mss_bar icinde kirilmazsa listeden dusmeli; yoksa aylar once
    olusmus bir swing bugun MSS uretirdi."""
    d, atr = _veri(1500)
    kisa = YapiStrategy(mss_bar=2)
    uzun = YapiStrategy(mss_bar=24)
    n_kisa = len(_tara(kisa, d, atr))
    n_uzun = len(_tara(uzun, d, atr))
    assert n_kisa < n_uzun, f"mss_bar etkisiz (kisa={n_kisa} uzun={n_uzun})"
