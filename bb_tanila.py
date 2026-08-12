"""
bb_tanila.py — KOD ile VERİ ÇELİŞİYOR. Hangisi yanılıyor?

DURUM:
 · Üretim sınıfı canlı config'le doğrudan çalıştırıldı (RiskManager.calculate_position_size,
   MAX_RISK_PCT=0.08 × RISK_SCALE=1.125 = %9, CAP=1.25). Sonuç: stop %7.2'nin ALTINDAKİ
   HER değerde nominal CAP'e yapışıyor. BB'nin stopu 3×ATR, yani ~%2 — dolayısıyla BB'nin
   11 işleminin 11'i de CAP'e yapışık olmalıydı.
 · Gerçek veri: 3/11 yapışık, medyan nominal/bakiye 1.03.
 · MeanReversionSignal sl_price taşımıyor → ATR yolu kesin → %9 kesin.

Kod tarafı üç ayrı yerden doğrulandı. O hâlde hata ÖLÇÜMDE. Üç aday var ve bu betik
üçünü de aynı anda ayırt eder:

 A) SINIFLANDIRMA — "bb" diye saydığım 11 işlem gerçekten BB kolu mu? sleeve_of "mean"
    ya da "bb" içeren HER dizgiyi bb sayıyor. Eski/kapalı bir kol karışmış olabilir.
    → ham strategy_scores dizgileri ve sembol dağılımı yazdırılıyor.
    (BB canlıda YALNIZ LTC ve YALNIZ hafta sonu. LTC dışı sembol varsa o işlem BB değildir.)

 B) BAKİYE — daily_stats.ending_balance GÜN SONU bakiyesi; işlem gün İÇİNDE açıldı ve
    boyut o andaki öz sermayeye göre belirlendi. Hesap büyüdüyse payda şişer, oran küçülür.
    → her işlem için kullanılan bakiye ve oranı tek tek yazdırılıyor; gün içi büyüme
      varsa bu tabloda görünür.

 C) KISMİ DOLUM — MAKER_ENTRY=true. execution.py'nin notuna göre donchian/squeeze
    force_market ile gelir ve limit yolunu HİÇ kullanmaz; "ATR-anchored (BB/MR)" ise
    maker limit + market yedeği kullanır. Yani KISMİ DOLUM RİSKİ OLAN TEK KOL BB.
    Kısmi dolduysa defterdeki quantity hedeflenenden küçüktür ve nominal CAP'in altına düşer.
    → beklenen CAP miktarı ile gerçekleşen miktar yan yana; oran %100'ün altındaysa dolum eksik.

Hiçbir şey değiştirmez, salt-okunur.

Kullanım (VPS'te):  cd /opt/bot2 && python3 bb_tanila.py
"""
import os
import sqlite3
import sys
from collections import Counter

from live_verify import sleeve_of

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "trades.db")
CAP = float(os.environ.get("BB_RISK_CAP", "1.25"))
YEDEK_BAL = float(os.environ.get("BB_RISK_BAL", "215"))


def main():
    if not os.path.exists(DB):
        print(f"trades.db bulunamadı: {DB}")
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    try:
        bal_map = {str(d)[:10]: float(b) for d, b in con.execute(
            "SELECT date, ending_balance FROM daily_stats WHERE is_paper=0"
            " AND ending_balance > 0")}
    except sqlite3.Error:
        bal_map = {}
    rows = con.execute(
        "SELECT symbol, entry_price, quantity, entry_time, strategy_scores, exit_reason"
        " FROM trades WHERE is_paper=0 AND quantity>0 AND entry_price>0"
        " ORDER BY entry_time").fetchall()
    con.close()

    # ── A) SINIFLANDIRMA ──
    print(f"\n{'=' * 100}\n[A] SINIFLANDIRMA — ham strategy_scores dizgileri")
    ham = Counter()
    for r in rows:
        ham[(str(r[4])[:70], sleeve_of(r[4]))] += 1
    print(f"  {'ham strategy_scores':<52s} {'→ kol':>10s} {'n':>5s}")
    for (s, k), n in ham.most_common():
        print(f"  {s:<52s} {k:>10s} {n:>5d}")

    bb = [r for r in rows if sleeve_of(r[4]) == "bb"]
    if not bb:
        print("\n  BB olarak sınıflanan işlem yok.")
        return
    print(f"\n  BB sayılan {len(bb)} işlemin SEMBOL dağılımı "
          f"(BB canlıda YALNIZ LTC olmalı):")
    for sym, n in Counter(r[0] for r in bb).most_common():
        bayrak = "" if "LTC" in sym.upper() else "   ⚠ LTC DEĞİL → bu işlem BB kolu OLAMAZ"
        print(f"    {sym:<22s} {n:>3d}{bayrak}")

    # ── B + C) İŞLEM İŞLEM ──
    print(f"\n{'=' * 100}\n[B+C] BB sayılan işlemler tek tek")
    print(f"  {'tarih':<11s} {'sembol':<18s} {'bakiye$':>9s} {'kaynak':>7s} {'miktar':>10s} "
          f"{'CAP miktarı':>11s} {'dolum%':>7s} {'nominal$':>9s} {'nom/bak':>8s}")
    for sym, ep, qty, et, sc, xr in bb:
        gun = str(et)[:10]
        bal = bal_map.get(gun)
        kaynak = "günlük" if bal else "yedek"
        if not bal:
            bal = YEDEK_BAL
        cap_qty = bal * CAP / ep                 # CAP'e yapışsaydı olması gereken miktar
        dolum = qty / cap_qty * 100 if cap_qty else 0
        nom = qty * ep
        print(f"  {gun:<11s} {sym:<18s} {bal:>9.2f} {kaynak:>7s} {qty:>10.3f} "
              f"{cap_qty:>11.3f} {dolum:>6.1f}% {nom:>9.2f} {nom/bal:>8.2f}")

    print(f"\n{'=' * 100}\n=== NASIL OKUNUR ===")
    print(f"  · 'dolum%' ≈ 100  → işlem CAP'e yapıştı. Kod okuması (BB %9) DOĞRU.")
    print(f"  · 'dolum%' belirgin < 100 ve LTC ise → ya kısmi maker dolumu (C) ya da")
    print(f"    boyutu başka bir mekanizma belirliyor. .env'e DOKUNULMAZ, önce o bulunur.")
    print(f"  · LTC olmayan satırlar BB kolu DEĞİLDİR; ortalamayı kirletiyorlar (A).")
    print(f"  · 'bakiye' sütunu gün sonu değeri; işlem gün içinde açıldığı için gerçek")
    print(f"    öz sermaye daha KÜÇÜK olabilir → oran olduğundan küçük görünür (B).")


if __name__ == "__main__":
    main()
