"""
bb_live_risk.py — BB kolu canlıda GERÇEKTEN kaç hedef riskle gidiyor?

⚠️ BU BETİĞİN İLK SÜRÜMÜ YANLIŞ ŞEYİ ÖLÇTÜ — hem "doğrulandı" hem "çürütüldü" hükmü geçersizdi.
   `risk$ = miktar × |giriş − stop|` hesaplıyordu. Ama database.py:218:
       UPDATE trades SET sl_price=? WHERE id=? AND exit_time IS NULL
   yani stop giriş SONRASI güncelleniyor (trailing/breakeven). Kapanmış satırdaki sl_price
   GİRİŞTEKİ stop değil, SON stop. Trailing yapan her kol olduğundan düşük risk gösterir —
   ilk çalıştırmada donchian %2.25 yerine %1.86, squeeze %1.02 çıkmasının sebebi buydu.

DOĞRU GÖZLEM: **nominal = miktar × giriş fiyatı**. `quantity` girişten sonra HİÇ
güncellenmiyor (database.py'de "SET quantity" yok), dolayısıyla temiz.

TEST ŞU MANTIĞA DAYANIYOR (risk.py:64-68 ve 185-195, iki yol da aynı):
    nominal = min(hedef_risk / stop_yüzdesi, CAP) × bakiye
BB'nin hedefi %9 İSE ve stopu ~%2 ise  →  0.09/0.02 = 4.5 > CAP(1.25)
→ **BB'nin HER işlemi CAP'e dayanmak ZORUNDA**, yani nominal/bakiye ≈ CAP sabit çıkar.
Dayanmıyorsa BB %9 ile gitmiyordur ve kod okuması yanlıştır.

Bu test tek yönlü ve keskin: "CAP'e yapışık mı?" sorusu stop verisine hiç ihtiyaç duymuyor.

BAKİYE: işlem anındaki bakiye gerekiyor (76 işlem haftalara yayılıyor, hesap büyüdü).
daily_stats.ending_balance tarihe göre eşleştiriliyor; yoksa BB_RISK_BAL'a düşülüyor.

Kullanım (VPS'te):  cd /opt/bot2 && python3 bb_live_risk.py
                    BB_RISK_BAL=215 python3 bb_live_risk.py     # daily_stats yoksa
"""
import os
import sqlite3
import statistics
import sys
from collections import defaultdict

# Kol tespitini TAKLİT ETME, ÇAĞIR. (İlk sürüm strategy_scores'u {ad: skor} sanıp
# argmax aldı; gerçek biçim {"strategy": "..."}.)
from live_verify import sleeve_of

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "trades.db")
CAP = float(os.environ.get("BB_RISK_CAP", "1.25"))     # canlı POSITION_CAP_FRACTION
YEDEK_BAL = float(os.environ.get("BB_RISK_BAL", "215"))


def bakiye_haritasi(con):
    """tarih (YYYY-MM-DD) → o günün kapanış bakiyesi."""
    try:
        rows = con.execute(
            "SELECT date, ending_balance FROM daily_stats WHERE is_paper=0"
            " AND ending_balance > 0").fetchall()
    except sqlite3.Error:
        return {}
    return {str(d)[:10]: float(b) for d, b in rows}


def main():
    if not os.path.exists(DB):
        print(f"trades.db bulunamadı: {DB}")
        return
    # SALT-OKUNUR: bot canlıda bu dosyaya YAZIYOR.
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    bal_map = bakiye_haritasi(con)
    rows = con.execute(
        "SELECT symbol, entry_price, quantity, entry_time, strategy_scores"
        " FROM trades WHERE is_paper=0 AND quantity>0 AND entry_price>0"
    ).fetchall()
    con.close()
    if not rows:
        print("Gerçek (is_paper=0) işlem yok.")
        return

    grup = defaultdict(list)
    eslesen = 0
    for sym, ep, qty, et, sc in rows:
        gun = str(et)[:10]
        bal = bal_map.get(gun)
        if bal:
            eslesen += 1
        else:
            bal = YEDEK_BAL
        grup[sleeve_of(sc)].append((qty * ep / bal, gun, sym, qty * ep))

    print(f"\n{'=' * 96}")
    print("=== BB kolu CAP'e yapışık mı? (nominal/bakiye testi) ===")
    print(f"  {len(rows)} gerçek işlem · CAP={CAP} · bakiye kaynağı: "
          f"daily_stats {eslesen}/{len(rows)} işlemde eşleşti"
          f"{'' if eslesen == len(rows) else f', kalanı ${YEDEK_BAL:.0f} varsayıldı'}")
    if eslesen == 0:
        print(f"  ⚠ daily_stats hiç eşleşmedi — TÜM oranlar tek bir bakiye varsayımına dayanıyor.")

    print(f"\n  {'kol':<12s} {'n':>4s} {'ilk işlem':>11s} {'son işlem':>11s} "
          f"{'ort nom/bak':>12s} {'medyan':>8s} {'CAPe yapışık':>14s}")
    ozet = {}
    for k in sorted(grup, key=lambda x: -len(grup[x])):
        v = grup[k]
        oran = [x[0] for x in v]
        gunler = sorted(x[1] for x in v)
        # CAP'e yapışık = oran CAP'in %5 yakınında (floor + fiyat yuvarlaması payı)
        yapisik = sum(1 for o in oran if o >= CAP * 0.95)
        ozet[k] = (len(v), statistics.mean(oran), statistics.median(oran), yapisik)
        print(f"  {k:<12s} {len(v):>4d} {gunler[0]:>11s} {gunler[-1]:>11s} "
              f"{statistics.mean(oran):>12.2f} {statistics.median(oran):>8.2f} "
              f"{yapisik:>8d}/{len(v):<5d}")

    print(f"\n{'=' * 96}\n=== HÜKÜM ===")
    bbk = next((k for k in ("bb", "mean_rev") if k in ozet), None)
    if bbk is None:
        print("  BB kolundan gerçek işlem YOK — iddia canlı veriyle sınanamıyor.")
        print("  (BB yalnız hafta sonu ve tek coin: LTC.)")
        return
    n, ort, med, yap = ozet[bbk]
    print(f"  BB: n={n} · ortalama nominal/bakiye {ort:.2f} · medyan {med:.2f} · "
          f"CAP'e yapışık {yap}/{n}")
    print(f"\n  BEKLENTİ, EĞER BB %9 hedefle gidiyorsa:")
    print(f"    BB stopu ~%2 → 0.09/0.02 = 4.5 > CAP({CAP}) → HER işlem CAP'e dayanır")
    print(f"    yani yapışık oranı ~{n}/{n} ve medyan ≈ {CAP:.2f} olmalı.")
    if yap >= 0.8 * n and med >= CAP * 0.95:
        print(f"\n  → KOD OKUMASI DOĞRULANDI. BB CAP'e yapışık; hedefi CAP'ten büyük.")
        print(f"    MAX_RISK_PCT'yi düşürmek BB'yi ankora hizalar.")
    elif yap <= 0.2 * n:
        print(f"\n  → KOD OKUMASI ÇÜRÜTÜLDÜ. BB CAP'e dayanmıyor; %9 hedefiyle bu imkânsız.")
        print(f"    Boyutu başka bir şey belirliyor. MAX_RISK_PCT DEĞİŞTİRİLMEMELİ —")
        print(f"    önce gerçek mekanizma bulunmalı.")
    else:
        print(f"\n  → KARARSIZ ({yap}/{n} yapışık). n küçük ya da bakiye eşleşmesi zayıf.")
    if n < 10:
        print(f"\n  ⚠ n={n} — yön göstergesi, kanıt değil.")


if __name__ == "__main__":
    main()
