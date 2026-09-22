"""
Yapi zinciri: supurme -> [displacement] -> MSS -> [FVG] -> limit retest.

EN ONEMLI TESTLER GELECEGE BAKIS uzerine. Bu depoda en pahaliya mal olan hata
(2026-09-20) IKIZ'in bir sonraki mumun kapanisini gormesiydi; bulunana kadar
tum taban PnL'i %86 yanlisti. Yapi tespiti (fractal swing) BU HATAYA ACIK bir
yerdir: bir swing ancak k bar SONRA onaylanir, erken kullanilirsa sinyal
gelecegi bilir.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.yapi import onayli_swingler, kurulumlari_bul, _fvg_bul


# --------------------------------------------------------------------------
# onayli_swingler
# --------------------------------------------------------------------------

def test_swing_k_BAR_SONRA_onaylanir_ONCE_DEGIL():
    """⚠ Bir swing high, olustugu barda BILINEMEZ."""
    k = 2
    h = np.array([1., 2., 3., 9., 3., 2., 1., 0.5, 0.4])   # tepe indeks 3
    l = h - 0.5
    son_sh, _ = onayli_swingler(h, l, k)
    assert (son_sh[:3 + k] == -1).all(), "swing erken 'bilindi' -> GELECEK SIZINTISI"
    assert son_sh[3 + k] == 3, "swing k bar sonra onaylanmadi"
    assert (son_sh[3 + k:] == 3).all()


def test_swing_dizisi_PENCEREDEN_BAGIMSIZ():
    """Seriyi uzatmak, gecmisteki swing kararlarini DEGISTIRMEMELI."""
    rng = np.random.RandomState(3)
    h = 100 + np.cumsum(rng.randn(400)) + rng.rand(400)
    l = h - 1 - rng.rand(400)
    a_sh, a_sl = onayli_swingler(h[:300], l[:300], 2)
    b_sh, b_sl = onayli_swingler(h, l, 2)
    assert (a_sh == b_sh[:300]).all()
    assert (a_sl == b_sl[:300]).all()


def test_duz_seride_swing_YOK():
    h = np.full(50, 10.0)
    l = np.full(50, 9.0)
    sh, sl = onayli_swingler(h, l, 2)
    assert (sh == -1).all() and (sl == -1).all(), "duz seride swing uretildi"


# --------------------------------------------------------------------------
# FVG geometrisi
# --------------------------------------------------------------------------

def test_fvg_boga_bosluk_dogru_bulunur():
    # i-2 tepesi 10, i tabani 12 -> arada 10..12 boslugu var
    h = np.array([10., 11., 13., 13.])
    l = np.array([9., 10., 12., 12.])
    bul = _fvg_bul(h, l, 2, 2, +1)
    assert bul is not None
    i, alt, ust = bul
    assert (i, alt, ust) == (2, 10.0, 12.0)


def test_fvg_bosluk_YOKSA_None():
    h = np.array([10., 11., 12., 12.])
    l = np.array([9., 9.5, 9.8, 9.8])          # low[2]=9.8 < high[0]=10 -> bosluk yok
    assert _fvg_bul(h, l, 2, 3, +1) is None


def test_fvg_ayi_bosluk():
    h = np.array([12., 11., 9., 9.])
    l = np.array([11., 10., 8., 8.])           # high[2]=9 < low[0]=11
    i, alt, ust = _fvg_bul(h, l, 2, 2, -1)
    assert (i, alt, ust) == (2, 9.0, 11.0)


# --------------------------------------------------------------------------
# zincir: gercek veri
# --------------------------------------------------------------------------

def _veri(n=6000):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    d = d[["open", "high", "low", "close"]].astype("float64").iloc[:n]
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift(1)).abs(),
                    (d.low - d.close.shift(1)).abs()], axis=1).max(axis=1)
    return (d.high.values, d.low.values, d.close.values,
            tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy())


def test_GELECEGE_BAKIS_YOK_kurulum_seviyesinde():
    """⚠ EN KRITIK TEST. Bir kurulum, MSS barindan SONRAKI barlar
    gorulmeden de AYNI sekilde bulunabilmeli."""
    h, l, c, a = _veri()
    tam = kurulumlari_bul(h, l, c, a)
    assert len(tam) > 20, f"test icin yeterli kurulum yok ({len(tam)})"
    for K in tam[::7]:                       # ornekle (hepsi cok yavas)
        m = K.mss_bar
        kesik = kurulumlari_bul(h[:m + 1], l[:m + 1], c[:m + 1], a[:m + 1])
        esler = [x for x in kesik
                 if x.mss_bar == m and x.yon == K.yon and x.supurme_bar == K.supurme_bar]
        assert esler, f"MSS bari {m}: seri kesilince kurulum KAYBOLDU -> gelecek sizintisi"
        e = esler[0]
        assert e.giris == pytest.approx(K.giris)
        assert e.sl == pytest.approx(K.sl)
        assert e.tp == pytest.approx(K.tp)


def test_R_orani_TAM_2_0():
    """Kullanicinin istedigi standart: yapisal SL + SABIT 2R. Kurulumlar
    arasi karsilastirma ancak bu sabitse anlamli."""
    h, l, c, a = _veri()
    for K in kurulumlari_bul(h, l, c, a)[:200]:
        risk = abs(K.giris - K.sl)
        odul = abs(K.tp - K.giris)
        assert odul / risk == pytest.approx(2.0), f"RR 2.0 degil: {odul/risk:.4f}"


def test_SL_supurulen_seviyenin_OTESINDE():
    """Yapisal SL'in tanimi: supurulen swing'in disi. Long'da giristen ASAGIDA,
    short'ta YUKARIDA olmali."""
    h, l, c, a = _veri()
    for K in kurulumlari_bul(h, l, c, a)[:300]:
        if K.yon > 0:
            assert K.sl < K.giris < K.tp
        else:
            assert K.tp < K.giris < K.sl


def test_supurme_sarti_GERCEKTEN_daraltiyor():
    h, l, c, a = _veri()
    ile = kurulumlari_bul(h, l, c, a, supurme_sart=True)
    siz = kurulumlari_bul(h, l, c, a, supurme_sart=False)
    assert len(ile) > 0 and len(siz) > 0
    assert len(ile) != len(siz), "supurme_sart hicbir sey degistirmiyor"


def test_displacement_kapisi_daraltiyor():
    h, l, c, a = _veri()
    acik = kurulumlari_bul(h, l, c, a, displacement_atr=1.0)
    kapali = kurulumlari_bul(h, l, c, a, displacement_atr=0.0)
    assert len(acik) < len(kapali), "displacement kapisi elemiyor"


def test_fvg_derinligi_girisi_UZAKLASTIRIR():
    """Derin retest (d=1.0) girisi fiyattan daha UZAGA koyar -> stop daha dar,
    R daha buyuk ama dolum ihtimali dusuk. Geometri dogru mu?"""
    h, l, c, a = _veri()
    sig = {(*(k.supurme_bar, k.mss_bar),): k for k in
           kurulumlari_bul(h, l, c, a, fvg_derinlik=0.0)}
    tam = {(*(k.supurme_bar, k.mss_bar),): k for k in
           kurulumlari_bul(h, l, c, a, fvg_derinlik=1.0)}
    ortak = set(sig) & set(tam)
    assert len(ortak) > 20, f"karsilastirma icin yeterli ortak kurulum yok ({len(ortak)})"
    for anahtar in list(ortak)[:100]:
        s, t = sig[anahtar], tam[anahtar]
        if s.yon > 0:
            assert t.giris <= s.giris, "long'da tam dolum girisi DAHA YUKARI cikmis"
        else:
            assert t.giris >= s.giris, "short'ta tam dolum girisi DAHA ASAGI inmis"


def test_MSS_referansi_SUPURME_ANINDAKI_swing():
    """MSS, supurme anindaki karsi swing'e gore olculmeli. Sonradan olusan
    bir swing kullanilsaydi gelecege bakis olurdu."""
    h, l, c, a = _veri(3000)
    from strategies.yapi import onayli_swingler as OS
    son_sh, son_sl = OS(h, l, 2)
    for K in kurulumlari_bul(h, l, c, a)[:150]:
        s, m = K.supurme_bar, K.mss_bar
        ref = son_sh[s] if K.yon > 0 else son_sl[s]
        assert ref >= 0
        seviye = h[ref] if K.yon > 0 else l[ref]
        if K.yon > 0:
            assert c[m] > seviye, "MSS bari referans swing high'i KAPANISLA gecmemis"
        else:
            assert c[m] < seviye
        # referans swing supurmeden ONCE onaylanmis olmali
        assert ref + 2 <= s, "MSS referansi supurmeden SONRA onaylanmis -> sizinti"
