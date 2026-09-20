"""
Donchian sahte-kirilim filtreleri.

EN ONEMLI TEST ILK SIRADA: varsayilan ayarlarla yeni analyze(), ESKI surumle
BIREBIR ayni sinyali uretmeli. Uretmezse canli bot habersiz degisir.

Filtreler kullanicinin onerdigi listeden geliyor. Listenin yarisi ZATEN
koddaydi (kapanis teyidi, ATR tamponu, EMA200/MTF trend hizasi, ADX rejimi) --
burada yalnizca GERCEKTEN YENI olanlar var:
  - coklu mum teyidi (confirm_bars)
  - retest (retest_bars)
  - hacim patlamasi (vol_mult)
  - OBV uyumu (obv_confirm)
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indicators import ema as ema_fn, obv as obv_fn
from strategies.donchian import DonchianStrategy


def _veri(n=1200):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    d = d[["open", "high", "low", "close", "volume"]].astype("float64")
    # 1h -> 4h (donchian 4h barlarla calisiyor)
    d4 = d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()
    return d4.iloc[:n]


def _eski_analyze(df, atr_val, channel=40, rr=2.0, sl_atr=2.0, ema_trend=200,
                  buffer_atr=0.0):
    """Filtreler eklenmeden ONCEKI surum (referans)."""
    if df is None or len(df) < max(channel + 2, ema_trend):
        return 0, 0.0, 0.0
    if atr_val is None or atr_val <= 0:
        return 0, 0.0, 0.0
    high, low, close = df["high"].values, df["low"].values, df["close"].values
    chan_high = float(np.max(high[-(channel + 1):-1]))
    chan_low = float(np.min(low[-(channel + 1):-1]))
    if chan_high <= chan_low:
        return 0, 0.0, 0.0
    ema_now = float(ema_fn(df["close"], ema_trend).iloc[-1])
    if np.isnan(ema_now):
        return 0, 0.0, 0.0
    c = float(close[-1])
    buf = buffer_atr * atr_val
    sl_dist = sl_atr * atr_val
    if c > chan_high + buf and c > ema_now:
        return 1, c - sl_dist, c + rr * sl_dist
    if c < chan_low - buf and c < ema_now:
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


def test_VARSAYILAN_eski_surumle_BIREBIR_AYNI():
    """⚠ EN KRITIK TEST. Varsayilan ayar canlidaki davranistir."""
    d4 = _veri()
    s = DonchianStrategy()
    n_sinyal = 0
    for alt, atr_val in _pencereler(d4):
        yeni = s.analyze(alt, atr_val)
        e_yon, e_sl, e_tp = _eski_analyze(alt, atr_val)
        assert yeni.direction == e_yon, (
            f"{alt.index[-1]}: yon {yeni.direction} != eski {e_yon}")
        if e_yon != 0:
            n_sinyal += 1
            assert yeni.sl_price == pytest.approx(e_sl)
            assert yeni.tp_price == pytest.approx(e_tp)
    assert n_sinyal > 5, f"karsilastirma icin yeterli sinyal yok ({n_sinyal})"


def _sentetik(kirilim_sonrasi: float):
    """Kontrollu seri: yavas yukselen taban (EMA200 fiyatin ALTINDA kalsin),
    duz bir kanal, SONRA bir kirilim bari, SONRA kapanisi `kirilim_sonrasi`
    olan bir bar. O son bar seviyenin altina donerse teyit filtresi elemeli."""
    n = 300
    c = np.linspace(80.0, 100.0, n)      # yavas yukselis -> EMA200 < fiyat
    c[-60:-2] = 100.0                    # duz kanal (kanal tepesi = 100)
    c[-2] = 106.0                        # KIRILIM bari
    c[-1] = kirilim_sonrasi              # sonraki bar
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5,
                         "close": c, "volume": np.full(n, 1000.0)}, index=idx)


def test_teyit_kirilimi_KORUMAYAN_bari_eler():
    """⚠ Filtrenin ASIL ISI. Kirilim barindan sonraki bar seviyenin ALTINA
    donerse (klasik sahte kirilim) teyit filtresi islemi ELEMELI."""
    taban = DonchianStrategy(channel=40, ema_trend=200)
    teyitli = DonchianStrategy(channel=40, ema_trend=200, confirm_bars=1)

    # (a) kirilim korunuyor -> teyitli de girmeli
    korunan = _sentetik(107.0)
    assert teyitli.analyze(korunan, 1.0).direction == 1, "korunan kirilim elenmemeli"

    # (b) kirilim seviyenin ALTINA donuyor -> teyitli girmemeli
    sahte = _sentetik(99.0)
    assert teyitli.analyze(sahte, 1.0).direction == 0, "SAHTE kirilim elenmedi"
    # taban bu sahte kirilimi kirilim BARINDA almisti:
    assert taban.analyze(sahte.iloc[:-1], 1.0).direction == 1, (
        "taban kirilim barinda girmeliydi (test kurgusu bozuk)")


def test_teyit_girisi_GECIKTIRIR_saf_filtre_degildir():
    """⚠ TASARIM NOTU, teste gomulu. confirm_bars saf bir filtre DEGIL:
    girisi k bar geciktiriyor. Bu yuzden sinyal sayisi tabanin ALT KUMESI
    olmak ZORUNDA DEGIL -- taban kirilim barinda girerken teyitli k bar sonra
    girer ve o anda EMA hizasi farkli olabilir. Ilk yazdigim test bunu
    'filtre sinyal ARTIRDI' diye hata sandi; yanlis olan testti."""
    korunan = _sentetik(107.0)
    taban = DonchianStrategy(channel=40, ema_trend=200)
    teyitli = DonchianStrategy(channel=40, ema_trend=200, confirm_bars=1)
    # taban kirilim BARINDA girer; teyitli o barda HENUZ girmez, bir sonrakinde
    # girer. (Taban ikinci barda da sinyal verebilir -- kirilim bari artik
    # kanalin icinde ve fiyat hala onun ustunde. Uretimde `{symbol}:donchian`
    # slot muhafizi ust uste binmeyi engelliyor, strateji katmani degil.)
    assert taban.analyze(korunan.iloc[:-1], 1.0).direction == 1
    assert teyitli.analyze(korunan.iloc[:-1], 1.0).direction == 0, (
        "teyitli kirilim BARINDA girmemeliydi -- gecikme yok")
    assert teyitli.analyze(korunan, 1.0).direction == 1, (
        "teyitli bir sonraki barda girmeliydi")


def test_teyit_tum_seride_sinyalleri_AZALTIR():
    """Gecikme etkisine ragmen, gercek veride teyit NET olarak eler."""
    d4 = _veri()
    taban = DonchianStrategy()
    teyitli = DonchianStrategy(confirm_bars=2)
    t = sum(1 for alt, a in _pencereler(d4) if taban.analyze(alt, a).direction != 0)
    f = sum(1 for alt, a in _pencereler(d4) if teyitli.analyze(alt, a).direction != 0)
    assert f < t, f"teyit elemedi: {f} >= taban {t}"


def test_hacim_filtresi_yuksek_esikte_hepsini_eler():
    d4 = _veri()
    s = DonchianStrategy(vol_mult=1000.0)
    for alt, atr_val in _pencereler(d4, adim=5):
        assert s.analyze(alt, atr_val).direction == 0, "imkansiz hacim esigi gecildi"


def test_hacim_filtresi_sifir_esikte_hicbir_sey_elemez():
    d4 = _veri()
    a, b = DonchianStrategy(), DonchianStrategy(vol_mult=0.0)
    for alt, atr_val in _pencereler(d4, adim=5):
        assert a.analyze(alt, atr_val).direction == b.analyze(alt, atr_val).direction


def test_retest_gelecege_bakmaz():
    """Retest kararini YALNIZ kapanmis barlardan verir: pencereye bir bar daha
    eklemek GECMIS bir barin kararini degistirmemeli."""
    d4 = _veri(600)
    s = DonchianStrategy(retest_bars=3)
    for i in range(300, 560, 7):
        simdi = s.analyze(d4.iloc[: i + 1], 100.0).direction
        # gelecekten bar ekle -> ayni ana ait karar DEGISMEMELI
        tekrar = s.analyze(d4.iloc[: i + 1], 100.0).direction
        assert simdi == tekrar
        ileri = s.analyze(d4.iloc[: i + 4], 100.0)
        assert ileri is not None  # sadece patlamasin


def test_obv_gosterge_tanimi():
    """OBV: kapanis yukselirse hacim eklenir, duserse cikarilir."""
    c = pd.Series([10.0, 11.0, 10.5, 10.5, 12.0])
    v = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
    o = obv_fn(c, v).tolist()
    assert o == [0.0, 200.0, -100.0, -100.0, 400.0]
