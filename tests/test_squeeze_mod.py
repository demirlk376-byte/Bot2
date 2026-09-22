"""
Squeeze GIRIS MODU — kirilimin yonunu VARSAYMAK yerine fiyatin DAVRANISINI
beklemek (kullanicinin 3. fikri).

Bugunku kural (mod="orta"): sikisma bitince kapanis KC orta cizgisinin
ustundeyse LONG. Kapanis ortalamanin bir tik ustunde olsa bile long der --
yani yonu VARSAYAR.
Yeni:
  aralik : cikis bari sikisma araliginin DISINA kapanmali, yoksa islem yok
  takip  : cikistan sonra en fazla N bar beklenir, aralik ILK hangi tarafa
           kirilirsa o yone girilir

EN ONEMLI TEST ILK SIRADA: mod="orta" canlidaki davranistir, BIREBIR ayni
kalmali.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indicators import atr as atr_fn, ema as ema_fn
from strategies.squeeze import SqueezeStrategy


def _veri(n=3000):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    return d[["open", "high", "low", "close", "volume"]].astype("float64").iloc[:n]


def _eski_analyze(df, atr_val, kc_period=20, kc_mult=1.5, bb_period=20,
                  bb_std=2.0, min_sq=5, sl_atr=2.0, rr=2.5):
    """Modlar eklenmeden ONCEKI surum (referans). MTF filtresi kapali
    karsilastirma icin ayri test var; burada tam surumu taklit ediyoruz."""
    if len(df) < max(kc_period, bb_period) + min_sq + 5 or atr_val <= 0:
        return 0
    close, high, low = df["close"], df["high"], df["low"]
    bb_mid = close.rolling(bb_period).mean()
    bb_s = close.rolling(bb_period).std()
    kc_mid = ema_fn(close, kc_period)
    at_kc = atr_fn(high, low, close, kc_period)
    in_sq = ((bb_mid + bb_std * bb_s) < (kc_mid + kc_mult * at_kc)) & \
            ((bb_mid - bb_std * bb_s) > (kc_mid - kc_mult * at_kc))
    v = in_sq.values
    if v[-1] or not v[-2]:
        return 0
    c = 0
    for j in range(len(v) - 2, -1, -1):
        if v[j]:
            c += 1
        else:
            break
    if c < min_sq:
        return 0
    return 1 if float(close.iloc[-1]) > float(kc_mid.iloc[-1]) else -1


def _pencereler(d, adim=1, pencere=400):
    for i in range(pencere, len(d), adim):
        alt = d.iloc[i - pencere + 1: i + 1]
        tr = pd.concat([alt.high - alt.low,
                        (alt.high - alt.close.shift(1)).abs(),
                        (alt.low - alt.close.shift(1)).abs()], axis=1).max(axis=1)
        yield alt, float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])


def test_VARSAYILAN_mod_eski_surumle_AYNI_cikis_barini_bulur():
    """⚠ EN KRITIK TEST. mod='orta' canlidaki davranistir.
    MTF/hacim filtreleri kapali tutulur ki yalniz mod mantigi karsilastirilsin."""
    d = _veri()
    s = SqueezeStrategy(mtf_filter=False)
    n = 0
    for alt, atr_val in _pencereler(d, adim=3):
        yeni = s.analyze(alt, atr_val)
        eski = _eski_analyze(alt, atr_val)
        assert yeni.direction == eski, f"{alt.index[-1]}: {yeni.direction} != {eski}"
        n += eski != 0
    assert n > 3, f"karsilastirma icin yeterli sinyal yok ({n})"


def test_mod_orta_ACIKCA_verilince_de_ayni():
    d = _veri(1500)
    a = SqueezeStrategy(mtf_filter=False)
    b = SqueezeStrategy(mtf_filter=False, mod="orta", takip_bar=6)
    for alt, atr_val in _pencereler(d, adim=5):
        x, y = a.analyze(alt, atr_val), b.analyze(alt, atr_val)
        assert x.direction == y.direction
        assert x.sl_price == y.sl_price and x.tp_price == y.tp_price


def test_bilinmeyen_mod_HATA_verir():
    """.env yazim hatasi SESSIZCE tabana dusmemeli."""
    with pytest.raises(ValueError):
        SqueezeStrategy(mod="aralk")       # bilerek yazim hatasi
    with pytest.raises(ValueError):
        SqueezeStrategy(mod="range")
    # buyuk harf/bosluk TEMIZLENIR, hata degildir:
    assert SqueezeStrategy(mod=" ARALIK ")._mod == "aralik"


# --------------------------------------------------------------------------
# sentetik: modun ASIL ISI
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# GERCEK VERI: modun ASIL ISI
# ⚠ Burasi eskiden sentetik seriyle yaziliydi; kurgu gercek bir "sikisma
# cikisi" URETMIYORDU, bu yuzden testler ya atlaniyor ya da bos yere
# direction==0 dogruluyordu -- yani HICBIR SEY olcmuyorlardi. Gercek BTC
# 1h verisine tasindi.
# --------------------------------------------------------------------------

def _sikisma_dizisi(df, kc_period=20, kc_mult=1.5, bb_period=20, bb_std=2.0):
    """in_sq dizisini BAGIMSIZ olarak yeniden hesapla (strateji koduna
    guvenmeden)."""
    close, high, low = df["close"], df["high"], df["low"]
    m = close.rolling(bb_period).mean()
    sd = close.rolling(bb_period).std()
    kmid = ema_fn(close, kc_period)
    a = atr_fn(high, low, close, kc_period)
    return (((m + bb_std * sd) < (kmid + kc_mult * a)) &
            ((m - bb_std * sd) > (kmid - kc_mult * a))).values


def _tarama(mod, takip_bar=3, n=12000, pencere=400):
    d = _veri(n)
    s = SqueezeStrategy(mtf_filter=False, mod=mod, takip_bar=takip_bar)
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift(1)).abs(),
                    (d.low - d.close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    cikan = {}
    for i in range(pencere, len(d)):
        sig = s.analyze(d.iloc[i - pencere + 1: i + 1], float(atr.iloc[i]))
        if sig.direction:
            cikan[i] = sig
    return d, atr, cikan


def test_aralik_ORTA_nin_ALT_KUMESI_ve_daha_dar():
    """aralik yeni firsat UYDURMAZ; ortanin girdiklerinden bir kismini eler."""
    _, _, o = _tarama("orta")
    _, _, a = _tarama("aralik")
    assert set(a) <= set(o), f"aralik ortada olmayan bar uretti: {set(a) - set(o)}"
    assert 0 < len(a) < len(o), f"aralik={len(a)} orta={len(o)}"


def test_aralik_ELEDIKLERI_GERCEKTEN_aralik_icinde_kapaniyor():
    """⚠ Modun ASIL ISI. Elenen her barda kapanis, sikisma araliginin ICINDE
    olmali -- sebep metnine degil, aralik BAGIMSIZ hesaplanarak dogrulanir."""
    d, atr, o = _tarama("orta")
    _, _, a = _tarama("aralik")
    elenen = sorted(set(o) - set(a))
    assert len(elenen) > 20, f"karsilastirma icin yeterli elenen yok ({len(elenen)})"
    v = _sikisma_dizisi(d)
    h, l, c = d.high.values, d.low.values, d.close.values
    for i in elenen:
        # cikis bari = su anki bar; ondan onceki ardisik sikisma barlari
        assert not v[i] and v[i - 1], f"{d.index[i]}: cikis bari degil"
        j, say = i - 1, 0
        while j >= 0 and v[j]:
            say += 1
            j -= 1
        ch = float(np.max(h[i - say:i]))
        cl = float(np.min(l[i - say:i]))
        assert cl <= c[i] <= ch, (
            f"{d.index[i]}: kapanis {c[i]:.2f} aralik disinda ({cl:.2f}..{ch:.2f}) "
            f"ama aralik modu elemis")


def test_takip_aralikin_UST_KUMESI_ve_GEC_kirilimlari_yakalar():
    _, _, a = _tarama("aralik")
    _, _, t = _tarama("takip", takip_bar=3)
    assert set(a) <= set(t), "takip, aralikin girdigi bir firsati kacirdi"
    assert len(t) > len(a), "takip hic GEC kirilim yakalamadi"


def test_takip_her_cikisa_EN_FAZLA_BIR_KEZ_girer():
    """Ayni sikisma cikisini ust uste birkaç bar almamali."""
    d, _, t = _tarama("takip", takip_bar=3)
    v = _sikisma_dizisi(d)
    cikislar = set()
    for i in sorted(t):
        # bu sinyalin dayandigi cikis barini bul (en yakin cikis, <= 3 bar geri)
        r = next((i - k for k in range(4) if i - k >= 1 and not v[i - k] and v[i - k - 1]), None)
        assert r is not None, f"{d.index[i]}: cikis bari bulunamadi"
        assert r not in cikislar, f"{d.index[i]}: ayni cikisa ({d.index[r]}) IKINCI kez girdi"
        cikislar.add(r)


def test_yon_ORTA_ile_CELISMIYOR():
    """Ikisi de girdiginde yon ayni olmali; aksi halde biri digerinin
    tersine islem acardi ve kiyaslama anlamsizlasirdi."""
    _, _, o = _tarama("orta")
    _, _, a = _tarama("aralik")
    for i in set(o) & set(a):
        assert o[i].direction == a[i].direction, f"{i}: yon celiskisi"


# --------------------------------------------------------------------------
# nedensellik
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mod,tb", [("aralik", 0), ("takip", 3)])
def test_GELECEGE_BAKIS_YOK(mod, tb):
    """Bir barin sinyali, pencereye SONRAKI barlar eklenince degismemeli."""
    d = _veri(1200)
    s = SqueezeStrategy(mtf_filter=False, mod=mod, takip_bar=tb or 3)
    for i in range(500, 1150, 11):
        alt = d.iloc[i - 399: i + 1]
        tr = pd.concat([alt.high - alt.low,
                        (alt.high - alt.close.shift(1)).abs(),
                        (alt.low - alt.close.shift(1)).abs()], axis=1).max(axis=1)
        atr_val = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        a = s.analyze(alt, atr_val)
        # pencereyi GENISLET (daha cok GECMIS ver) -> sinyal ayni kalmali
        genis = d.iloc[max(0, i - 599): i + 1]
        b = s.analyze(genis, atr_val)
        assert a.direction == b.direction, f"{alt.index[-1]}: pencereye duyarli"


@pytest.mark.parametrize("mod", ["aralik", "takip"])
def test_gercek_veride_sinyal_URETIYOR(mod):
    d = _veri(4000)
    s = SqueezeStrategy(mtf_filter=False, mod=mod)
    n = sum(1 for alt, a in _pencereler(d, adim=2) if s.analyze(alt, a).direction != 0)
    assert n >= 3, f"{mod}: gercek veride yalnizca {n} sinyal"
