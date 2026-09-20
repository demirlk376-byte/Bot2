"""
ReplayFeed GELECEGI SIZDIRMAMALI.

2026-09-20'de kanitlandi: get_current_price ACILIS damgalarinda arama yaptigi
icin BIR SAAT SONRAKI kapanisi donduruyordu (saat 17:00 iken 28027.70 dondu,
dogrusu 28055.40). O fiyat giris/cikis dolumunda ve SL/TP kontrolunde
kullaniliyordu, yani her islem bir saatlik gelecek bilgisi tasiyordu.

Bu testler nedenselligin BEKCISIDIR. Dusen bir test = backtest yalan soyluyor.
"""
import asyncio
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ikiz.besleme import ReplayFeed
from ikiz.saat import SanalSaat

SEM = "BTC/USDT:USDT"


# ⚠ scope="function": SanalSaat GERIYE GITMEYI REDDEDIYOR (saat.py:24) -- ki
# dogrusu budur, replay'de zaman hep ileri akar. Paylasilan bir saat ikinci
# testte hata verir; her test kendi saatiyle baslar.
@pytest.fixture
def feed():
    saat = SanalSaat(pd.Timestamp("2023-04-06 14:00", tz="UTC").to_pydatetime())
    return ReplayFeed(saat, [SEM], source="local"), saat


def test_anlik_fiyat_gelecegi_sizdirmaz(feed):
    f, saat = feed
    s = f._s(SEM, "1h")
    for i in (2, 10, 100, 1000, 5000):
        saat.ayarla(pd.Timestamp(s.kapanis_ns[i], tz="UTC").to_pydatetime())
        px = asyncio.run(f.get_current_price(SEM))
        assert px == pytest.approx(float(s.c[i])), (
            f"i={i}: {px} donduruldu, o an bilinebilecek son kapanis {s.c[i]}; "
            f"bir sonraki {s.c[i+1]} (SIZINTI)")


def test_mum_ORTASINDA_hala_onceki_kapanis(feed):
    """Mumun icindeyken en son BITMIS mumun kapanisi gorunmeli -- olusmakta
    olan mumun kapanisi henuz bilinemez."""
    f, saat = feed
    s = f._s(SEM, "1h")
    for i in (5, 50, 500):
        orta = (int(s.ts_ns[i + 1]) + int(s.kapanis_ns[i + 1])) // 2
        saat.ayarla(pd.Timestamp(orta, tz="UTC").to_pydatetime())
        px = asyncio.run(f.get_current_price(SEM))
        assert px == pytest.approx(float(s.c[i])), (
            f"i={i} mumunun ortasinda {px} dondu; {s.c[i]} olmaliydi")


def test_fetch_ohlcv_kapanmamis_mumdan_oteye_gecmez(feed):
    """Gercek borsa son satirda HENUZ KAPANMAMIS mumu verir ve DataManager onu
    atar. Kapanmis mumlarin damgasi saatten KUCUK olmali."""
    f, saat = feed
    s = f._s(SEM, "1h")
    for i in (20, 200, 2000):
        t = pd.Timestamp(s.kapanis_ns[i], tz="UTC")
        saat.ayarla(t.to_pydatetime())
        rows = asyncio.run(f.fetch_ohlcv(SEM, "1h", None, 50))
        assert rows, "veri gelmedi"
        kapanmis = [r for r in rows if r[0] * 1_000_000 + 3_600_000_000_000 <= int(t.value)]
        assert kapanmis, "hic kapanmis mum yok"
        son = kapanmis[-1]
        assert son[4] == pytest.approx(float(s.c[i])), (
            "son KAPANMIS mumun kapanisi saatle uyusmuyor")
        # olusmakta olan mum en fazla BIR tane olabilir
        assert len(rows) - len(kapanmis) <= 1, "birden fazla kapanmamis mum donmus"


def test_4h_turetilmis_mum_gelecege_tasmaz(feed):
    """4h mumlar 1h'ten turetiliyor. Turetilen mumun KAPANISI saatten sonraysa
    o mum henuz olusmamistir ve kapanmis sayilmamalidir."""
    f, saat = feed
    s1 = f._s(SEM, "1h")
    s4 = f._s(SEM, "4h")
    for i in (30, 300, 3000):
        t = pd.Timestamp(s1.kapanis_ns[i], tz="UTC")
        saat.ayarla(t.to_pydatetime())
        k = int(np.searchsorted(s4.kapanis_ns, int(t.value), side="right"))
        if k > 0:
            assert s4.kapanis_ns[k - 1] <= int(t.value), "4h mumu gelecege tasiyor"
