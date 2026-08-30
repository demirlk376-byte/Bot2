"""
test_sermaye.py — sermaye denklemi aritmetiği, GERÇEK veriyle kilitli.

NEDEN VAR: para_ekle.py --tespit bu rakamı ÜST ÜSTE İKİ KEZ yanlış verdi.
  1) "$26.32 kayıt eksiği" — inception_balance'ın köken öncesi transferleri
     karşıladığını varsaydı. Karşılamıyordu ($104.65 transfer vs $48.47 kayıt).
  2) "$456.09 gerçek sermaye / −$114.72 kâr" — deposits + transfers +
     withdrawals TOPLANDI. Ama aynı para iki kez görünüyor: önce 'deposit'
     (dışarıdan MEXC'e), sonra 'transfer' (spot→vadeli). Çift sayma.

Doğru kural: sermaye YALNIZ 'transfers' ile ölçülür — bota para ancak VADELİ
cüzdana geçince girer; spotta duran deposit'i bot görmez.

Aşağıdaki kayıtlar 2026-08-29'da VPS'ten okunan GERÇEK MEXC verisi.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from para_ekle import sermaye_denklemi

# VPS'ten okunan gerçek kayıtlar (89 günlük pencere)
GERCEK = [
    ("2026-06-09 15:47",   9.98, "transfers"),
    ("2026-06-09 16:34",   1.00, "transfers"),
    ("2026-06-15 22:30",  48.43, "transfers"),
    ("2026-06-17 14:39",  45.24, "transfers"),
    ("2026-07-12 00:32", 104.40, "deposits"),     # ← transfers ile AYNI para
    ("2026-07-12 00:37", 104.40, "transfers"),
    ("2026-08-28 08:35",  71.32, "deposits"),     # ← transfers ile AYNI para
    ("2026-08-28 10:59",  71.32, "transfers"),
]
ILK = "2026-06-18T00:01"
INC, DEP, EQ = 48.47, 149.39, 341.36


def test_deposit_transfer_cifti_bir_kez_sayilir():
    r = sermaye_denklemi(GERCEK, ILK, INC, DEP, EQ)
    assert abs(r["tum"] - 280.37) < 0.01, \
        f"sermaye {r['tum']:.2f}, beklenen 280.37 (456.09 = ÇİFT SAYMA)"
    assert r["tum"] < 400, "deposits tekrar toplanmış — çift sayma geri geldi"
    print(f"  toplam sermaye ${r['tum']:.2f} (çift sayma yok) ✓")


def test_koken_oncesi_sonrasi_ayrimi():
    r = sermaye_denklemi(GERCEK, ILK, INC, DEP, EQ)
    assert abs(r["oncesi"] - 104.65) < 0.01, r["oncesi"]
    assert abs(r["sonrasi"] - 175.72) < 0.01, r["sonrasi"]
    print(f"  köken öncesi ${r['oncesi']:.2f} / sonrası ${r['sonrasi']:.2f} ✓")


def test_inception_celiskisi_yakalanir():
    """Bot başlamadan $104.65 girmiş ama inception $48.47 — fark bildirilmeli."""
    r = sermaye_denklemi(GERCEK, ILK, INC, DEP, EQ)
    assert abs(r["inception_farki"] - 56.18) < 0.01, r["inception_farki"]
    assert r["inception_farki"] > 2.0, "çelişki eşiğin altında kalıyor"
    print(f"  inception çelişkisi ${r['inception_farki']:+.2f} yakalandı ✓")


def test_gercek_kar_defterden_dusuk():
    """Defter $+143.49 diyor; borsa kaydına göre gerçek çok daha düşük."""
    r = sermaye_denklemi(GERCEK, ILK, INC, DEP, EQ)
    assert abs(r["defter_kar"] - 143.49) < 0.01, r["defter_kar"]
    assert abs(r["gercek_kar"] - 60.99) < 0.01, \
        f"gerçek kâr {r['gercek_kar']:.2f}, beklenen 60.99"
    assert r["gercek_kar"] > 0, "kâr negatife düştü — muhtemelen çift sayma"
    print(f"  defter ${r['defter_kar']:+.2f} vs gerçek ${r['gercek_kar']:+.2f} ✓")


def test_duzeltme_tutari():
    """total_deposits $149.39 → $231.90 olmalı, yani +$82.51."""
    r = sermaye_denklemi(GERCEK, ILK, INC, DEP, EQ)
    assert abs(r["gereken_dep"] - 231.90) < 0.01, r["gereken_dep"]
    assert abs(r["duzeltme"] - 82.51) < 0.01, \
        f"düzeltme {r['duzeltme']:.2f}, beklenen 82.51 (258.22 = çift sayma)"
    print(f"  düzeltme +${r['duzeltme']:.2f} (258.22 DEĞİL) ✓")


def test_transfer_yoksa_hukum_yok():
    """Hiç transfer okunamazsa 'gerçek kâr' üretilmemeli."""
    r = sermaye_denklemi([("2026-07-12 00:32", 104.40, "deposits")],
                         ILK, INC, DEP, EQ)
    assert r["tum"] == 0
    assert r["gercek_kar"] is None, "transfer yokken kâr uydurulmuş"
    print("  transfer yokken hüküm üretilmedi ✓")


if __name__ == "__main__":
    print("test_sermaye — sermaye denklemi, gerçek MEXC verisiyle kilitli\n")
    for fn in (test_deposit_transfer_cifti_bir_kez_sayilir,
               test_koken_oncesi_sonrasi_ayrimi,
               test_inception_celiskisi_yakalanir,
               test_gercek_kar_defterden_dusuk,
               test_duzeltme_tutari,
               test_transfer_yoksa_hukum_yok):
        fn()
    print("\n✓ SERMAYE DENKLEMİ TESTLERİ GEÇTİ")
