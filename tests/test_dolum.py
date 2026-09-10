"""MEXC dolum ayrıştırıcıları — CANLI VERİYLE kilitlendi (2026-09-10).

Bu iki fonksiyon, fetch_close_fill'in 30 gün boyunca sessizce başarısız
olmasının sebebiydi. Rakamlar VPS'ten alınan gerçek dolumlardan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange import _mexc_yon, _mexc_miktar


def _es(a, b, tol=1e-4):
    assert abs(a - b) <= tol, f"{a} != {b}"


def test_yon_ham_kodlar():
    # MEXC: 1=long aç, 2=short kapat, 3=short aç, 4=long kapat
    assert _mexc_yon({"side": "4"}) == "sell", "long KAPAT sell olmalı"
    assert _mexc_yon({"side": "3"}) == "sell"
    assert _mexc_yon({"side": "1"}) == "buy"
    assert _mexc_yon({"side": "2"}) == "buy", "short KAPAT buy olmalı"


def test_yon_normalize_edilmis():
    assert _mexc_yon({"side": "buy"}) == "buy"
    assert _mexc_yon({"side": "SELL"}) == "sell"


def test_yon_info_yedegi():
    assert _mexc_yon({"side": None, "info": {"side": "4"}}) == "sell"


def test_yon_bilinmeyen_none():
    assert _mexc_yon({"side": "9"}) is None
    assert _mexc_yon({}) is None


def test_miktar_gercek_dolumlar():
    """cost/price defterdeki COIN miktarını vermeli. amount KONTRAT."""
    # NEAR: kontrat boyutu 1.0 → amount == coin
    _es(_mexc_miktar({"cost": 90.0980, "amount": 38.0}, 2.371), 38.0)
    # BNB: kontrat boyutu 0.01 → amount 100x fazla
    _es(_mexc_miktar({"cost": 236.7750, "amount": 33.0}, 717.5), 0.33)
    # BCH: kontrat boyutu 0.01
    _es(_mexc_miktar({"cost": 155.4712, "amount": 62.0}, 250.76), 0.62)


def test_miktar_amount_a_DUSMEZ():
    """cost yoksa None — amount'a düşmek sessizce yanlış BİRİM kullanmaktır."""
    assert _mexc_miktar({"amount": 33.0}, 717.5) is None
    assert _mexc_miktar({"cost": 0, "amount": 33.0}, 717.5) is None
    assert _mexc_miktar({"cost": "abc", "amount": 33.0}, 717.5) is None


def test_miktar_gecersiz_fiyat():
    assert _mexc_miktar({"cost": 100.0}, 0) is None
    assert _mexc_miktar({"cost": 100.0}, -5) is None


def test_eski_hata_yeniden_uretilemez():
    """Regresyon: eski süzgeç 'buy'/'sell' dışını eliyordu.

    Ölçülen gerçek dağılımda NEAR'ın 13 dolumunun 6'sı ham kodluydu ('3':1,'4':5).
    Kapanış yönü 'sell' arandığında eski kod 2, yenisi 6 dolum bulmalı.
    """
    fills = ([{"side": "4"}] * 5 + [{"side": "3"}] * 1
             + [{"side": "buy"}] * 5 + [{"side": "sell"}] * 2)
    eski = sum(1 for f in fills if (f.get("side") or "").lower() == "sell")
    yeni = sum(1 for f in fills if _mexc_yon(f) == "sell")
    assert eski == 2, eski
    assert yeni == 8, yeni          # 5 (kod 4) + 1 (kod 3) + 2 ('sell')
    assert yeni > eski


if __name__ == "__main__":
    n = 0
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn(); n += 1; print(f"  ✓ {ad}")
    print(f"\n✓ test_dolum: {n}/{n} geçti")
