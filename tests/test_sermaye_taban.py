"""
test_sermaye_taban.py — yatırılan sermaye BORSADAN kendi kendini güncelliyor mu?

NEDEN VAR: 2026-08-28'de kullanıcı $82.51 ekledi, kimse deposit.py çalıştırmadı,
ve /status o parayı doğrudan "Gerçek kâr" diye gösterdi (+%72 dedi, gerçek
+%22'ydi). Sebep: yatırılan sermaye ELLE tutuluyordu.

Artık bot borsanın SPOT→VADELİ transfer kaydını okuyup `sermaye_taban`
meta'sını kendisi günceller. Bu testler üç tuzağı kilitliyor:
  1. 90 günlük pencere: taban BİRİKİMLİ olmalı, "son 90 günün toplamı" DEĞİL —
     yoksa bot 90 günü geçince eski sermaye silinir ve kâr şişer.
  2. Okunamayan transfer SIFIR sayılmamalı — sıfır saymak sermayeyi siler.
  3. İlk tohumlama geçmiş transferleri TEKRAR eklememeli (çift sayma).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange import LiveExchange


def _lx(kayitlar):
    lx = LiveExchange.__new__(LiveExchange)
    class _C:
        async def fetch_transfers(self, cur, since, limit, params):
            return [k for k in kayitlar if (k.get("timestamp") or 0) >= since]
    lx._exchange = _C()
    return lx


import asyncio


def test_yalniz_usdt_ve_yon_okunur():
    kayit = [
        {"timestamp": 1000, "currency": "USDT", "amount": 100.0},
        {"timestamp": 2000, "currency": "USDT", "amount": 50.0, "type": "OUT"},
        {"timestamp": 3000, "currency": "BTC",  "amount": 1.0},      # USDT değil
    ]
    tot = asyncio.run(_lx(kayit).fetch_transfers_in(0))
    assert abs(tot - 50.0) < 1e-9, f"beklenen 50.0 (100 giriş − 50 çıkış), geldi {tot}"
    print(f"  yön + para birimi doğru okundu: ${tot:.2f} ✓")


def test_since_filtreleniyor():
    """Birikimli taban için ŞART: yalnız damgadan SONRAKİ transferler gelmeli."""
    kayit = [
        {"timestamp": 1000, "currency": "USDT", "amount": 100.0},
        {"timestamp": 5000, "currency": "USDT", "amount": 25.0},
    ]
    tot = asyncio.run(_lx(kayit).fetch_transfers_in(2000))
    assert abs(tot - 25.0) < 1e-9, f"eski transfer tekrar sayıldı: {tot}"
    print("  damgadan öncekiler tekrar sayılmadı (çift sayma yok) ✓")


def test_okunamazsa_None_doner():
    """SIFIR değil None — sıfır saymak sermayeyi siler ve kârı şişirir."""
    class _Patlak:
        async def fetch_transfers(self, *a, **k):
            raise RuntimeError("borsa yok")
    lx = LiveExchange.__new__(LiveExchange); lx._exchange = _Patlak()
    assert asyncio.run(lx.fetch_transfers_in(0)) is None

    class _Yok:
        pass
    lx2 = LiveExchange.__new__(LiveExchange); lx2._exchange = _Yok()
    assert asyncio.run(lx2.fetch_transfers_in(0)) is None
    print("  okunamayınca None (0.0 DEĞİL) ✓")


def test_bos_liste_sifir_ama_None_degil():
    """Gerçekten hiç transfer yoksa 0.0 doğru — None ile karışmamalı."""
    tot = asyncio.run(_lx([]).fetch_transfers_in(0))
    assert tot == 0.0 and tot is not None
    print("  transfer yoksa 0.0 (None değil) ✓")


def test_main_periyodik_cagiriyor():
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    assert "async def sermaye_guncelle" in src, "güncelleyici yok"
    i = src.index("async def heartbeat_loop")
    assert "sermaye_guncelle()" in src[i:i + 4000], \
        "heartbeat sermaye tabanını tazelemiyor"
    # OKUNAMADI != SIFIR koruması
    j = src.index("async def sermaye_guncelle")
    blok = src[j:j + 3000]
    assert "if yeni is None" in blok, "okunamayan transfer sıfır sayılıyor"
    assert "sermaye_taban_ts" in blok, "birikimli damga yok — 90 gün tuzağı açık"
    print("  main.py periyodik güncelliyor + guard'lar yerinde ✓")


def test_status_yeni_tabani_kullaniyor():
    src = (Path(__file__).resolve().parent.parent / "telegram_bot.py").read_text()
    i = src.index("async def _invested")
    blok = src[i:i + 1800]
    assert "sermaye_taban" in blok, "/status hâlâ yalnız elle tutulan değeri okuyor"
    assert "inception_balance" in blok, "yedek yol kaldırılmış — davranış bozulur"
    print("  /status sermaye_taban'ı kullanıyor, yedeği duruyor ✓")


if __name__ == "__main__":
    print("test_sermaye_taban — yatırılan sermaye borsadan kendini güncelliyor mu?\n")
    for fn in (test_yalniz_usdt_ve_yon_okunur,
               test_since_filtreleniyor,
               test_okunamazsa_None_doner,
               test_bos_liste_sifir_ama_None_degil,
               test_main_periyodik_cagiriyor,
               test_status_yeni_tabani_kullaniyor):
        fn()
    print("\n✓ SERMAYE TABANI TESTLERİ GEÇTİ")
