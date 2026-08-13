"""
ucret_olc.py — ANKORUN ÜCRET VARSAYIMI DOĞRU MU? (defterden ölç, tahmin etme)

live_verify [5] bunu işaret etmişti ama üstünde durulmadı:
    "ortalama fark $+0.0333 · fark ÜCRET ÖLÇEĞİNDE (ücretin 0.6 katı)
     → büyük ihtimalle TAKER_FEE varsayımı hafif yanlış"

deployed_backtest.py FEE = 0.0001 (taraf başına 1bp) varsayıyor ve her işlemin R'sinden
`2 * FEE * entry / sl_dist` düşüyor. 1579 işlemde bu sistematik bir sapmadır: varsayım
gerçekten küçükse ankor OLDUĞUNDAN İYİ görünür, büyükse olduğundan kötü.

MEXC'e sormaya gerek yok — trades.db'de `fees_usdt` sütunu var. Gerçek oran:
    oran = fees_usdt / (nominal × taraf sayısı)
Giriş ve çıkış ayrı ücretlendirilir, yani iki taraf. Nominal = miktar × giriş fiyatı.

⚠️ KARIŞTIRILMAMASI GEREKEN İKİ ŞEY:
 · MAKER ücreti (limit emir, kuyruğa yazan)  — MEXC'te genelde daha düşük ya da 0
 · TAKER ücreti (piyasa emri, kuyruktan alan)
MAKER_ENTRY=true ve execution.py'ye göre yalnız BB/MR kolu maker limit yolunu kullanıyor;
donchian/squeeze force_market ile geliyor. Yani kol bazında oran FARKLI çıkabilir ve
bu normaldir — ankor hepsine aynı FEE'yi uyguluyor, asıl soru bu.

ÇIKTI: gerçek ücret oranı (kol bazında ve toplam), ankor varsayımıyla farkı, ve o farkın
1579 işleme yayıldığında ankoru kaç dolar yanlış gösterdiği.

Kullanım (VPS'te):  cd /opt/bot2 && python3 ucret_olc.py
"""
import os
import sqlite3
import sys
from collections import defaultdict

from live_verify import sleeve_of

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))
ANK_FEE = 0.0001          # deployed_backtest.FEE — taraf başına
ANK_N = 1579              # ankor işlem sayısı
ANK_TOT = 1420.66         # ankor net kâr (CAP=1.25 tabanı)


def main():
    if not os.path.exists(DB):
        print(f"trades.db bulunamadı: {DB}")
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, entry_price, exit_price, quantity, fees_usdt, strategy_scores,"
        " exit_time FROM trades WHERE is_paper=0 AND quantity>0 AND entry_price>0"
    ).fetchall()
    con.close()
    if not rows:
        print("Gerçek işlem yok.")
        return

    grp = defaultdict(lambda: {"n": 0, "fee": 0.0, "nom": 0.0, "kapali": 0})
    for sym, ep, xp, qty, fee, sc, xt in rows:
        if fee is None:
            continue
        k = sleeve_of(sc)
        g = grp[k]
        g["n"] += 1
        g["fee"] += float(fee)
        # Kapanmışsa iki taraf ücretlendirilmiştir, açıksa yalnız giriş.
        taraf = 2 if xt else 1
        g["nom"] += float(qty) * float(ep) * taraf
        g["kapali"] += 1 if xt else 0

    print(f"\n{'=' * 88}")
    print("=== ÜCRET ÖLÇÜMÜ — ankorun varsayımı gerçeği tutuyor mu? ===")
    print(f"  ankor varsayımı: taraf başına {ANK_FEE*10000:.2f} bp")
    print(f"\n  {'kol':<12s} {'n':>5s} {'kapalı':>7s} {'toplam ücret$':>14s} "
          f"{'nominal$ (taraflı)':>19s} {'gerçek bp':>10s} {'ankor bp':>9s} {'fark':>8s}")
    top_fee = top_nom = 0.0
    for k in sorted(grp, key=lambda x: -grp[x]["n"]):
        g = grp[k]
        if g["nom"] <= 0:
            continue
        bp = g["fee"] / g["nom"] * 10000
        top_fee += g["fee"]; top_nom += g["nom"]
        print(f"  {k:<12s} {g['n']:>5d} {g['kapali']:>7d} {g['fee']:>14.4f} "
              f"{g['nom']:>19.2f} {bp:>10.3f} {ANK_FEE*10000:>9.2f} "
              f"{bp - ANK_FEE*10000:>+8.3f}")
    if top_nom <= 0:
        print("\n  Nominal hesaplanamadı — ücret verisi eksik.")
        return
    genel = top_fee / top_nom * 10000
    print(f"  {'TOPLAM':<12s} {sum(g['n'] for g in grp.values()):>5d} "
          f"{sum(g['kapali'] for g in grp.values()):>7d} {top_fee:>14.4f} "
          f"{top_nom:>19.2f} {genel:>10.3f} {ANK_FEE*10000:>9.2f} "
          f"{genel - ANK_FEE*10000:>+8.3f}")

    print(f"\n{'=' * 88}\n=== HÜKÜM ===")
    fark_bp = genel - ANK_FEE * 10000
    if abs(fark_bp) < 0.15:
        print(f"  Gerçek {genel:.3f} bp vs ankor {ANK_FEE*10000:.2f} bp — fark {fark_bp:+.3f} bp.")
        print(f"  ✓ Ankorun ücret varsayımı DOĞRU. Bu kalem kapandı.")
        return
    # Farkın ankora etkisi: her işlemde iki taraf, R'den düşülen kısım nominal orantılı.
    # Ankorun ortalama nominali ≈ risk$/sl% ; basit üst sınır olarak canlı ortalama
    # nominal/işlem kullanılıyor ve 1579 işleme yayılıyor.
    ort_nom_islem = top_nom / max(sum(g["n"] for g in grp.values()), 1)
    etki = fark_bp / 10000 * ort_nom_islem * ANK_N
    print(f"  Gerçek {genel:.3f} bp vs ankor {ANK_FEE*10000:.2f} bp → fark {fark_bp:+.3f} bp")
    print(f"  Ortalama nominal (taraflı) ${ort_nom_islem:.2f}/işlem · {ANK_N} işlem")
    print(f"  → Ankor bu kalemde ${etki:+.2f} {'FAZLA' if fark_bp > 0 else 'AZ'} gösteriyor")
    print(f"    (ankor toplamı ${ANK_TOT:.2f}; etki %{abs(etki)/ANK_TOT*100:.2f})")
    if abs(etki) / ANK_TOT < 0.02:
        print(f"  → Etki %2'nin altında: kayda değer AMA aksiyon gerektirmiyor.")
    else:
        print(f"  ⚠ Etki %2'nin ÜSTÜNDE: deployed_backtest.FEE düzeltilmeli ve")
        print(f"    ankor yeniden üretilmeli. Bütün geçmiş karşılaştırmalar bu tabana dayanıyor.")
    print(f"\n  NOT: kol bazında oranların farklı olması NORMALDİR — MAKER_ENTRY=true ve")
    print(f"  yalnız BB/MR maker limit yolunu kullanıyor (donchian/squeeze force_market).")
    print(f"  Asıl soru ankorun HEPSİNE uyguladığı tek oranın doğru olup olmadığı.")


if __name__ == "__main__":
    main()
