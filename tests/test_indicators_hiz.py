"""
Hizlandirilmis indikatorler ESKISIYLE BIREBIR AYNI sayiyi uretmeli.

NEDEN BU TEST: indicators.py'deki rsi/atr/adx profilde kosunun %50'sini
yiyordu, ama harcanan sure MATEMATIK degil pandas nesne yuku (Series.__init__
332 bin cagri). Elemanlar arasi islemleri numpy'a tasiyip `ewm`'i (asil hesap,
C'de kosuyor) AYNEN birakirsak sonuc degismemeli.

"Degismemeli" yetmez -- bu projede olculmeyen hiz iddiasi bugun iki kez
curudu. Test TAM ESITLIK ariyor: NaN'lar ayni yerde, sayilar son bite kadar
ayni. Tek bit sapsa optimizasyon copa gider.
"""
import numpy as np
import pandas as pd
import pytest

import indicators as I


# --- ESKI SURUMLER (referans; commit 6a7d83d'deki hali) ---
def ref_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    out = out.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return out


def ref_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def ref_adx(high, low, close, period=14):
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm_s = pd.Series(plus_dm, index=high.index)
    minus_dm_s = pd.Series(minus_dm, index=high.index)
    atr_s = ref_atr(high, low, close, period)
    plus_di = 100 * plus_dm_s.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm_s.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def _veri():
    """GERCEK mum verisi. Uydurma rassal seri, ozel durumlari (duz pencere,
    kesintisiz yukselis, sifir hacim) ISKALAR -- rsi'daki 100/50 telafileri
    tam oralarda devreye giriyor."""
    import os
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "BTC_fut_1h.csv")
    d = pd.read_csv(yol)
    d.index = pd.to_datetime(d["ts"], utc=True)
    return (d["high"].astype("float64"), d["low"].astype("float64"),
            d["close"].astype("float64"))


def _ayni(a, b, ad):
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    assert a.shape == b.shape, f"{ad}: uzunluk farkli"
    na, nb = np.isnan(a), np.isnan(b)
    assert np.array_equal(na, nb), f"{ad}: NaN konumlari farkli"
    fark = a[~na] != b[~nb]
    assert not fark.any(), (
        f"{ad}: {fark.sum()} deger farkli, en buyuk sapma "
        f"{np.nanmax(np.abs(a[~na][fark] - b[~nb][fark])) if fark.any() else 0}")


@pytest.mark.parametrize("period", [7, 14, 20, 26])
@pytest.mark.parametrize("n", [60, 260, 2000])
def test_ayni_sonuc(period, n):
    h, l, c = _veri()
    h, l, c = h.iloc[:n], l.iloc[:n], c.iloc[:n]
    _ayni(I.rsi(c, period), ref_rsi(c, period), f"rsi p={period} n={n}")
    _ayni(I.atr(h, l, c, period), ref_atr(h, l, c, period), f"atr p={period} n={n}")
    _ayni(I.adx(h, l, c, period), ref_adx(h, l, c, period), f"adx p={period} n={n}")


def test_indeks_ve_tip_korunur():
    h, l, c = _veri()
    h, l, c = h.iloc[:300], l.iloc[:300], c.iloc[:300]
    for ad, out in (("rsi", I.rsi(c)), ("atr", I.atr(h, l, c)), ("adx", I.adx(h, l, c))):
        assert isinstance(out, pd.Series), f"{ad}: Series donmeli"
        assert out.index.equals(c.index), f"{ad}: indeks degismis"
        assert out.dtype == np.float64, f"{ad}: dtype {out.dtype}"


def test_duz_pencere_ozel_durumlari():
    """rsi'nin 100 ve 50 telafileri: kesintisiz yukselis ve tamamen duz seri."""
    yukari = pd.Series(np.arange(100.0, 160.0), index=pd.RangeIndex(60))
    duz = pd.Series(np.full(60, 100.0), index=pd.RangeIndex(60))
    _ayni(I.rsi(yukari), ref_rsi(yukari), "rsi kesintisiz yukselis")
    _ayni(I.rsi(duz), ref_rsi(duz), "rsi duz seri")
