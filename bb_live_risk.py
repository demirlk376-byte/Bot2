"""
bb_live_risk.py — İDDİAYI GERÇEK PARAYLA SINA: BB kolu canlıda ne kadar risk alıyor?

KOD OKUMASI ŞUNU SÖYLÜYOR (execution.py:526 → risk.py:185):
  donchian → donchian_risk_pct = %2 × RISK_SCALE = %2.25
  squeeze  → squeeze_risk_pct  = %2 × RISK_SCALE = %2.25
  bb/mean_rev → risk_override = 0.0 → max_risk_per_trade = MAX_RISK_PCT(%8) × 1.125 = **%9**
              (yalnızca POSITION_CAP_FRACTION kesiyor)

AMA ANKOR (deployed_backtest.py) BB'yi de %2.25 ile modelliyor. Yani ankorun "en kötü ay
−%21" tahmini BB'yi EKSİK riskle sayıyor olabilir.

KOD OKUMASI YANILABİLİR. Bu betik iddiayı VERİYLE sınar: kapanmış her gerçek işlem için
    risk$ = miktar × |giriş − stop|
hesaplar (bunlar emrin gönderildiği andaki GERÇEK sayılar, tahmin değil) ve kola göre böler.

BEKLENTİ: donchian/squeeze ≈ %2.25, bb belirgin şekilde YÜKSEK (%3+).
Eğer bb de %2.25 çıkarsa kod okumam YANLIŞ demektir ve CAP kararı ankora göre verilebilir.

Kullanım (VPS'te):  cd /opt/bot2 && python3 bb_live_risk.py
"""
import os
import sqlite3
import sys
from collections import defaultdict

# Kol tespitini TAKLİT ETME, ÇAĞIR. (Bu betiğin ilk sürümü strategy_scores'u
# {ad: skor} sözlüğü sandı ve argmax aldı; gerçek biçim {"strategy": "..."} —
# yani her satıra "strategy" etiketi basıyordu. live_verify.sleeve_of zaten
# doğru ayrıştırıcı; tek kaynak o olsun.)
from live_verify import sleeve_of

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "trades.db")


def main():
    if not os.path.exists(DB):
        print(f"trades.db bulunamadı: {DB}")
        return
    # SALT-OKUNUR: bot canlıda bu dosyaya YAZIYOR. Normal connect() yazma kilidi
    # alabilir ve botun işlem kaydını engelleyebilir. live_verify.py da böyle açıyor.
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, entry_price, sl_price, quantity, entry_time, strategy_scores"
        " FROM trades WHERE is_paper=0 AND quantity>0 AND sl_price>0 AND entry_price>0"
    ).fetchall()
    con.close()

    if not rows:
        print("Gerçek (is_paper=0) işlem yok.")
        return

    grup = defaultdict(list)
    for sym, ep, slp, qty, et, sc in rows:
        risk_usd = qty * abs(ep - slp)
        sl_pct = abs(ep - slp) / ep
        nominal = qty * ep
        grup[sleeve_of(sc)].append((risk_usd, sl_pct, nominal, et, sym))

    # Bakiye: ortalama risk%'i çıkarmak için gerekli. .env'den değil, kullanıcıdan
    # gelen tek sayı — yanlışsa TÜM kollar aynı oranda kayar, KOLLAR ARASI FARK bozulmaz.
    BAL = float(os.environ.get("BB_RISK_BAL", "200"))

    print(f"\n{'=' * 92}")
    print("=== CANLI SIZING: her kol gerçekte ne kadar risk aldı? ===")
    print(f"  {len(rows)} gerçek işlem · varsayılan bakiye ${BAL:.0f} "
          f"(BB_RISK_BAL ile değiştirilebilir)")
    print(f"\n  {'kol':<14s} {'n':>4s} {'ort risk$':>10s} {'ort risk%':>10s} "
          f"{'ort sl%':>8s} {'ort nominal$':>13s} {'nominal/bakiye':>15s}")

    beklenen = {"donchian": 2.25, "squeeze": 2.25}
    ozet = {}
    for k in sorted(grup, key=lambda x: -len(grup[x])):
        v = grup[k]
        n = len(v)
        r_usd = sum(x[0] for x in v) / n
        r_pct = r_usd / BAL * 100
        slp = sum(x[1] for x in v) / n * 100
        nom = sum(x[2] for x in v) / n
        ozet[k] = (n, r_pct, slp, nom)
        print(f"  {k:<14s} {n:>4d} {r_usd:>10.2f} {r_pct:>10.2f} {slp:>8.2f} "
              f"{nom:>13.2f} {nom/BAL:>14.2f}x")

    print(f"\n{'=' * 92}\n=== HÜKÜM ===")
    ref = [ozet[k][1] for k in ("donchian", "squeeze") if k in ozet]
    if not ref:
        print("  donchian/squeeze işlemi yok — karşılaştırma yapılamıyor.")
        return
    taban = sum(ref) / len(ref)
    print(f"  Referans (donchian+squeeze ortalaması): %{taban:.2f}  "
          f"[kod beklentisi %2.25]")

    for k in ("bb", "mean_rev"):
        if k not in ozet:
            continue
        n, rp, slp, nom = ozet[k]
        kat = rp / taban if taban > 0 else 0
        print(f"\n  {k}: n={n} · ort risk %{rp:.2f} · referansın {kat:.2f} KATI")
        if n < 5:
            print(f"    ⚠ n={n} çok az — yön göstergesi, kanıt değil.")
        if kat > 1.25:
            print(f"    → KOD OKUMASI DOĞRULANDI: BB ankorun modellediğinden fazla risk alıyor.")
            print(f"      Ankorun 'en kötü ay −%21' tahmini BB tarafını EKSİK sayıyor.")
        elif kat < 1.10:
            print(f"    → KOD OKUMASI YANLIŞ ÇIKTI: BB de diğerleriyle aynı seviyede.")
            print(f"      Ankor gerçeği doğru modelliyor; CAP kararı ankora göre verilebilir.")
        else:
            print(f"    → belirsiz ({kat:.2f}x). Daha çok BB işlemi gerekiyor.")

    if not any(k in ozet for k in ("bb", "mean_rev")):
        print("\n  BB kolundan KAPANMIŞ GERÇEK İŞLEM YOK.")
        print("  (BB yalnız HAFTA SONU çalışıyor ve tek coin: LTC — az işlem normal.)")
        print("  → İddia canlı veriyle sınanamıyor; karar kod okumasına dayanmak zorunda.")


if __name__ == "__main__":
    main()
