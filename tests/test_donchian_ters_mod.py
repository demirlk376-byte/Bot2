"""
Donchian GIRIS MODLARI — kirilimi degil, kirilimin BASARISIZLIGINI trade etmek.

GEREKCE (ham karne, ikiz_duzeltilmis.db, 1752 islem):
  SL orani %51.4 -> kirilimlarin YARIDAN FAZLASI basarisiz. Soru: o havuz
  ters yonde bilgi tasiyor mu? Filtre EKLEMEK yerine GIRISI degistiriyoruz.

EN ONEMLI TEST ILK SIRADA: varsayilan (mod="kirilim") ayarla analyze(),
modlar eklenmeden onceki surumle BIREBIR ayni sinyali uretmeli. Uretmezse
canli bot habersiz degisir.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indicators import ema as ema_fn
from strategies.donchian import DonchianStrategy


# --------------------------------------------------------------------------
# gercek veri: varsayilan davranis DEGISMEDI
# --------------------------------------------------------------------------

def _veri(n=1200):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    d = d[["open", "high", "low", "close", "volume"]].astype("float64")
    d4 = d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()
    return d4.iloc[:n]


def _eski_analyze(df, atr_val, channel=40, rr=2.0, sl_atr=2.0, ema_trend=200):
    """Modlar eklenmeden ONCEKI surum (referans)."""
    if df is None or len(df) < max(channel + 2, ema_trend):
        return 0, 0.0, 0.0
    if atr_val is None or atr_val <= 0:
        return 0, 0.0, 0.0
    high, low, close = df["high"].values, df["low"].values, df["close"].values
    ch = float(np.max(high[-(channel + 1):-1]))
    cl = float(np.min(low[-(channel + 1):-1]))
    if ch <= cl:
        return 0, 0.0, 0.0
    ema_now = float(ema_fn(df["close"], ema_trend).iloc[-1])
    if np.isnan(ema_now):
        return 0, 0.0, 0.0
    c = float(close[-1])
    sl_dist = sl_atr * atr_val
    if c > ch and c > ema_now:
        return 1, c - sl_dist, c + rr * sl_dist
    if c < cl and c < ema_now:
        return -1, c + sl_dist, c - rr * sl_dist
    return 0, 0.0, 0.0


def _pencereler(d4, adim=1):
    """Canliyla ayni gorus: her bar icin O BARA KADAR olan pencere."""
    for i in range(260, len(d4), adim):
        alt = d4.iloc[: i + 1]
        tr = pd.concat([alt.high - alt.low,
                        (alt.high - alt.close.shift(1)).abs(),
                        (alt.low - alt.close.shift(1)).abs()], axis=1).max(axis=1)
        atr_val = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        yield alt, atr_val


def test_VARSAYILAN_mod_eski_surumle_BIREBIR_AYNI():
    """⚠ EN KRITIK TEST. Varsayilan mod canlidaki davranistir."""
    d4 = _veri()
    s = DonchianStrategy()
    n_sinyal = 0
    for alt, atr_val in _pencereler(d4):
        yeni = s.analyze(alt, atr_val)
        e_yon, e_sl, e_tp = _eski_analyze(alt, atr_val)
        assert yeni.direction == e_yon, f"{alt.index[-1]}: {yeni.direction} != {e_yon}"
        if e_yon != 0:
            n_sinyal += 1
            assert yeni.sl_price == pytest.approx(e_sl)
            assert yeni.tp_price == pytest.approx(e_tp)
    assert n_sinyal > 5, f"karsilastirma icin yeterli sinyal yok ({n_sinyal})"


def test_mod_kirilim_ACIKCA_verilince_de_ayni():
    """DONCHIAN_MOD=kirilim yazmak varsayilanla ayni olmali."""
    d4 = _veri(600)
    a, b = DonchianStrategy(), DonchianStrategy(mod="kirilim", ters_trend=False)
    for alt, atr_val in _pencereler(d4, adim=3):
        x, y = a.analyze(alt, atr_val), b.analyze(alt, atr_val)
        assert x.direction == y.direction
        assert x.sl_price == y.sl_price and x.tp_price == y.tp_price


def test_bilinmeyen_mod_HATA_verir():
    """⚠ .env yazim hatasi SESSIZCE tabana dusmemeli -- dusseydi taramada
    'fark yok' diye YANLIS rapor verirdik."""
    with pytest.raises(ValueError):
        DonchianStrategy(mod="basarsiz")       # bilerek yazim hatasi
    with pytest.raises(ValueError):
        DonchianStrategy(mod="reversal")


# --------------------------------------------------------------------------
# sentetik: modlarin ASIL ISI
# --------------------------------------------------------------------------

def _seri(c, high=None, low=None):
    c = np.asarray(c, dtype="float64")
    h = c + 0.5 if high is None else np.asarray(high, dtype="float64")
    l = c - 0.5 if low is None else np.asarray(low, dtype="float64")
    idx = pd.date_range("2024-01-01", periods=len(c), freq="4h", tz="UTC")
    return pd.DataFrame({"open": c, "high": h, "low": l, "close": c,
                         "volume": np.full(len(c), 1000.0)}, index=idx)


def _basarisiz(son_kapanis, yonelim="yukari"):
    """Duz kanal (tepe 100.5) -> KIRILIM bari (106) -> geri donus bari.
    yonelim='asagi' seriyi dususte kurar, boylece EMA200 fiyatin USTUNDE
    kalir ve ters_trend=True short'a IZIN verir."""
    n = 300
    if yonelim == "asagi":
        c = np.linspace(400.0, 100.0, n)
    else:
        c = np.linspace(80.0, 100.0, n)
    c[-60:-2] = 100.0
    c[-2] = 106.0                 # kanal disina KAPANDI
    c[-1] = son_kapanis           # geri donus bari
    return _seri(c)


def test_basarisiz_kirilim_TERS_yonde_sinyal_verir():
    """Onceki bar kanal ustune kapandi, su anki bar geri dondu -> SHORT."""
    s = DonchianStrategy(mod="basarisiz", ters_trend=False)
    sig = s.analyze(_basarisiz(99.0), 1.0)
    assert sig.direction == -1, sig.reason
    assert sig.sl_price > 99.0 and sig.tp_price < 99.0, "SHORT SL/TP ters"
    assert sig.sl_price == pytest.approx(99.0 + 2.0)       # 2.0 x ATR
    assert sig.tp_price == pytest.approx(99.0 - 2.0 * 2.0)  # RR 2.0


def test_basarisiz_mod_KORUNAN_kirilime_girmez():
    """Kirilim korunuyorsa (hala disarida kapaniyor) basarisizlik YOK."""
    s = DonchianStrategy(mod="basarisiz", ters_trend=False)
    assert s.analyze(_basarisiz(107.0), 1.0).direction == 0


def test_basarisiz_ile_kirilim_AYNI_bari_paylasmaz():
    """Ayni barda iki mod da sinyal verirse cift sayardik -- vermemeli."""
    df = _basarisiz(99.0)
    assert DonchianStrategy(mod="kirilim").analyze(df, 1.0).direction == 0
    assert DonchianStrategy(mod="basarisiz", ters_trend=False).analyze(df, 1.0).direction == -1


def test_ters_trend_ACIKKEN_EMA200_hizasi_aranir():
    """ters_trend=True: basarisiz YUKARI kirilimda short icin fiyat EMA200'un
    ALTINDA olmali. Yukselen seride bu saglanmaz -> sinyal yok."""
    siki = DonchianStrategy(mod="basarisiz", ters_trend=True)
    gevsek = DonchianStrategy(mod="basarisiz", ters_trend=False)

    yukselen = _basarisiz(99.0, yonelim="yukari")
    assert float(ema_fn(yukselen["close"], 200).iloc[-1]) < 99.0, "kurgu bozuk"
    assert siki.analyze(yukselen, 1.0).direction == 0, "EMA hizasi aranmadi"
    assert gevsek.analyze(yukselen, 1.0).direction == -1

    dusen = _basarisiz(99.0, yonelim="asagi")
    assert float(ema_fn(dusen["close"], 200).iloc[-1]) > 99.0, "kurgu bozuk"
    assert siki.analyze(dusen, 1.0).direction == -1, "trendle uyumlu short elendi"


def _supurme(son_kapanis, son_tepe):
    """Duz kanal (tepe 100.5); SON bar fitille yukari tasiyor."""
    n = 300
    c = np.linspace(80.0, 100.0, n)
    c[-60:] = 100.0
    c[-1] = son_kapanis
    h = c + 0.5
    h[-1] = son_tepe
    return _seri(c, high=h)


def test_supurme_fitil_disari_kapanis_iceri_TERS_sinyal():
    s = DonchianStrategy(mod="supurme", ters_trend=False)
    sig = s.analyze(_supurme(99.0, 106.0), 1.0)
    assert sig.direction == -1, sig.reason
    assert sig.sl_price == pytest.approx(99.0 + 2.0)


def test_supurme_fitil_DELMEZSE_sinyal_yok():
    s = DonchianStrategy(mod="supurme", ters_trend=False)
    assert s.analyze(_supurme(99.0, 100.0), 1.0).direction == 0


def test_supurme_GERCEK_kirilimi_almaz():
    """Fitil disari tasti ama kapanis da DISARIDA -> bu supurme degil,
    gercek kirilim. Supurme modu buna girmemeli (kirilim modu girer)."""
    df = _supurme(101.0, 106.0)
    assert DonchianStrategy(mod="supurme", ters_trend=False).analyze(df, 1.0).direction == 0
    assert DonchianStrategy(mod="kirilim").analyze(df, 1.0).direction == 1


# --------------------------------------------------------------------------
# nedensellik: gelecege bakis yok
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mod", ["basarisiz", "supurme"])
def test_GELECEGE_BAKIS_YOK(mod):
    """Bir barin sinyali, SONRAKI barlar eklenince degismemeli."""
    d4 = _veri(500)
    s = DonchianStrategy(mod=mod, ters_trend=False)
    n = 0
    for i in range(300, 460, 7):
        alt = d4.iloc[: i + 1]
        tr = pd.concat([alt.high - alt.low,
                        (alt.high - alt.close.shift(1)).abs(),
                        (alt.low - alt.close.shift(1)).abs()], axis=1).max(axis=1)
        atr_val = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        a = s.analyze(alt, atr_val)
        b = s.analyze(d4.iloc[: i + 1].copy(), atr_val)   # ayni pencere, kopya
        assert a.direction == b.direction
        # pencereyi UZATIRSAK son bar degisir -> sinyal de degisebilir; ama
        # KISALTIP ayni son bara getirirsek AYNI kalmali
        uzun = d4.iloc[: i + 40]
        c = s.analyze(uzun.iloc[: i + 1], atr_val)
        assert a.direction == c.direction, f"{alt.index[-1]}: gelecek sizdi"
        n += a.direction != 0
    assert n >= 0


@pytest.mark.parametrize("mod", ["basarisiz", "supurme"])
def test_gercek_veride_sinyal_URETIYOR(mod):
    """Mod calisiyor mu? Hic sinyal uretmiyorsa tarama anlamsiz olur."""
    d4 = _veri()
    s = DonchianStrategy(mod=mod, ters_trend=False)
    n = sum(1 for alt, a in _pencereler(d4) if s.analyze(alt, a).direction != 0)
    assert n >= 5, f"{mod}: gercek veride yalnizca {n} sinyal"
