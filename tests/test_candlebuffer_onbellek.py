"""
Onbellekli to_dataframe ESKISIYLE birebir ayni tabloyu uretmeli.

Profilde get_candles->to_dataframe kosunun %15'iydi: tampon degismedigi halde
her cagride 260 satirlik sozluk listesinden DataFrame kuruluyordu. Onbellek
ekledim; bu test sonucun degismedigini gosteriyor -- sutun sirasi, dtype'lar,
indeks degerleri VE indeks ADI dahil (eski surum indekse "timestamp" adini
veriyordu; dusurulse indekse ada gore bakan yerler sessizce degisirdi).
"""
import asyncio
import numpy as np
import pandas as pd

from data import Candle, CandleBuffer


def _eski_to_dataframe(buf):
    rows = [
        {"timestamp": c.timestamp, "open": c.open, "high": c.high,
         "low": c.low, "close": c.close, "volume": c.volume}
        for c in buf._buf
    ]
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["timestamp"], unit="ms")
    df.drop(columns=["timestamp"], inplace=True)
    return df


def _mumlar(n, t0=1_680_000_000_000):
    return [Candle(timestamp=t0 + i * 3_600_000, open=100.0 + i, high=101.0 + i,
                   low=99.0 + i, close=100.5 + i, volume=1000.0 + i)
            for i in range(n)]


def _kur(n, maxlen=260):
    b = CandleBuffer("BTC/USDT:USDT", "1h", maxlen=maxlen)
    for m in _mumlar(n):
        asyncio.run(b.update(m))
    return b


def test_ayni_tablo():
    for n in (1, 5, 260, 400):          # 400 -> maxlen tasmasi da sinaniyor
        b = _kur(n)
        yeni, eski = b.to_dataframe(), _eski_to_dataframe(b)
        pd.testing.assert_frame_equal(yeni, eski, check_names=True, check_exact=True)
        assert yeni.index.name == "timestamp"
        assert list(yeni.columns) == ["open", "high", "low", "close", "volume"]


def test_onbellek_guncellemede_gecersiz_olur():
    b = _kur(10)
    ilk = b.to_dataframe()
    # ⚠ "ayni nesne" BEKLENMEZ: to_dataframe yuzeysel kopya donduruyor (cagiran
    # yazarsa onbellek bozulmasin diye). Onbellegin calistiginin kaniti,
    # VERININ ayni blogu paylasmasi: yeniden kurulsa degerler yeni dizilerde
    # olurdu. Icerik esitligi + ucuzluk yeterli gostergedir.
    assert b.to_dataframe().equals(ilk)
    assert b._df is not None, "onbellek dolmaliydi"
    asyncio.run(b.update(_mumlar(11)[10]))
    yeni = b.to_dataframe()
    assert yeni is not ilk, "tampon degisti, onbellek gecersiz olmaliydi"
    pd.testing.assert_frame_equal(yeni, _eski_to_dataframe(b), check_exact=True)


def test_son_mum_uzerine_yazilinca_da_gecersiz_olur():
    """Ayni damgali mum geldiginde tampon son satiri DEGISTIRIYOR ama
    update() False donuyor -- onbellek yine de gecersiz kilinmali."""
    b = _kur(5)
    once = b.to_dataframe().copy()
    son = b._buf[-1]
    asyncio.run(b.update(Candle(timestamp=son.timestamp, open=1.0, high=2.0,
                                low=0.5, close=1.5, volume=9.0)))
    sonra = b.to_dataframe()
    assert sonra["close"].iloc[-1] == 1.5, "onbellek bayat kaldi"
    assert not sonra.equals(once)
    pd.testing.assert_frame_equal(sonra, _eski_to_dataframe(b), check_exact=True)


def test_bos_tampon():
    b = CandleBuffer("BTC/USDT:USDT", "1h")
    df = b.to_dataframe()
    assert len(df) == 0 and list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_cagiran_degistirse_bile_onbellek_bozulmaz():
    """⚠ ONBELLEGIN TEK GERCEK RISKI BU. Eskiden her cagri YENI bir tablo
    donduruyordu, yani cagiranin uzerinde oynamasi kimseyi etkilemiyordu.
    Artik ayni nesne paylasiliyor. Uretimde get_candles'i cagiran bes yer var
    (hepsi main.py) ve hicbiri yazmiyor; pandas 3'te Copy-on-Write de zaten
    engelliyor. Bu test o dayanagi KAYIT ALTINA ALIR: bir gun biri yazmaya
    baslarsa ya da pandas davranisi degisirse burada duser."""
    b = _kur(50)
    referans = _eski_to_dataframe(b)

    d1 = b.to_dataframe()
    try:
        d1["close"] = 0.0            # cagiran uzerinde oynuyor
        d1.iloc[0, 0] = -999.0
    except Exception:
        pass                          # yazmaya izin verilmemesi de kabul

    pd.testing.assert_frame_equal(b.to_dataframe(), referans, check_exact=True)


def test_tail_dilimi_uzerinden_yazma_da_bozmaz():
    """get_candles df.tail(n) donduruyor -- dilim uzerinden yazma da
    onbellege sizmamali."""
    b = _kur(50)
    referans = _eski_to_dataframe(b)
    dilim = b.to_dataframe().tail(10)
    try:
        dilim["high"] = 1.0
    except Exception:
        pass
    pd.testing.assert_frame_equal(b.to_dataframe(), referans, check_exact=True)
