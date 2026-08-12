"""
pw_cap.py — SIZING EKSENİ: en iyi işlemlerimizi SİSTEMATİK OLARAK az mı bahis ediyoruz?

BUGÜN TEST EDİLEN HER ŞEY "hangi işlemi alalım" ya da "nasıl çıkalım"dı. Sizing'e hiç
dokunulmadı — ve orada somut bir şüphe var.

MEKANİZMA (risk.py:64-68):
    quantity = (bakiye × %2.25) / (fiyat × sl_yüzdesi)     ← hedef risk
    max_qty  = (bakiye × CAP=1.25) / fiyat                 ← nominal tavanı
    quantity = min(quantity, max_qty)
Yani **stop DAR olduğunda** hedef risk daha büyük bir nominal ister, CAP kesiyor ve o işlem
hedeflenen %2.25'ten AZ risk alıyor. Ankor çıktısı bunu zaten söylüyordu: işlemlerin bir
kısmı "tavana takılıyor".

ASIL SORU: tavana takılan işlemler (dar stop) diğerlerinden FARKLI kalitede mi?
 · Dar stoplu işlemler DAHA İYİ ise → en iyi işlemlerimize en küçük bahsi koyuyoruz.
   Bu, işlem SEÇMEDEN, yeni coin EKLEMEDEN, eşzamanlı maruziyeti ARTIRMADAN düzeltilebilir
   bir kayıp demektir — bugün çöken altı eksenin hiçbirinin dokunmadığı bir yer.
 · Fark YOKSA CAP zararsızdır ve eksen kapanır.

⚠️ LEDGER UYARISI (sleeve_risk_test.py bu tuzağa DÜŞTÜ): risk değiştiren her testte TOPLAM
RİSKİN sabit tutulduğu SAYIYLA doğrulanmalı; yoksa sadece "daha çok risk = daha çok kâr"
ölçülür ki bu bir bulgu değildir. Bu yüzden CAP taramasında ortalama gerçekleşen risk ve
maxDD/en kötü ay HER SATIRDA raporlanıyor.

ÖN-KAYITLI BAR (bugün YEDİ ekseni reddeden barın AYNISI):
  Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek · maxDD +2 puandan fazla artmayacak ·
  EN KÖTÜ AY KÖTÜLEŞMEYECEK.

Kullanım:  py pw_cap.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A


def havuz(source):
    """Ankorun İŞLEM havuzu (koltuk seçiminden GEÇMİŞ olanlar), sl_pct ile birlikte."""
    trades = []
    for c in A.DONCH: trades += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:   trades += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS: trades += A.gen_bb(fast_bt.load(c, source=source))
    return A.seat_select(trades)


def olc(taken, cap):
    r = np.array([R for _, R, _ in taken]); sp = np.array([s for _, _, s in taken])
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    eff = np.minimum(A.RISKF, cap * sp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    bagli = eff < A.RISKF - 1e-12
    return dict(tot=float(pnl.sum()), dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                ort_risk=float(eff.mean() * 100), bagli=float(bagli.mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    taken = havuz(source)
    r = np.array([R for _, R, _ in taken]); sp = np.array([s for _, _, s in taken])
    taban = olc(taken, A.CAP)
    years = sorted(taban["yr"])
    ok = len(r) == 1579 and abs(taban["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 112}")
    print("=== SIZING EKSENİ: CAP tavanına takılan işlemler farklı kalitede mi? ===")
    print(f"\n  DOĞRULAMA: {len(r)} işlem / ${taban['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return

    # ── 1) TEŞHİS: bağlı vs bağsız işlemlerin R'si ──
    eff = np.minimum(A.RISKF, A.CAP * sp)
    bagli = eff < A.RISKF - 1e-12
    rb, rs = r[bagli], r[~bagli]
    print(f"\n[1] TEŞHİS — tavana takılan işlemler DAHA İYİ mi?")
    print(f"    tavana TAKILAN  n={bagli.sum():>4d} (%{bagli.mean()*100:.0f})  "
          f"ort R {rb.mean():+.4f}  ort sl%% {sp[bagli].mean()*100:.2f}")
    print(f"    takılmayan      n={(~bagli).sum():>4d} (%{(~bagli).mean()*100:.0f})  "
          f"ort R {rs.mean():+.4f}  ort sl%% {sp[~bagli].mean()*100:.2f}")
    se = np.sqrt(rb.var(ddof=1)/len(rb) + rs.var(ddof=1)/len(rs))
    z = (rb.mean() - rs.mean()) / se
    print(f"    fark {rb.mean()-rs.mean():+.4f}R ± {se:.4f} → z = {z:+.2f}  "
          f"{'✓ ANLAMLI' if abs(z) > 1.96 else '✗ anlamsız'}")
    if abs(z) > 1.96 and rb.mean() > rs.mean():
        print(f"    ⚠ TAVANA TAKILANLAR DAHA İYİ → en iyi işlemlere en KÜÇÜK bahis konuyor")
    elif abs(z) > 1.96:
        print(f"    → tavana takılanlar daha KÖTÜ; CAP aslında koruyor")
    else:
        print(f"    → kalite farkı YOK; CAP yalnızca boyut kesiyor, seçim yapmıyor")

    # ── 2) CAP TARAMASI ──
    print(f"\n[2] CAP TARAMASI — tavanı gevşetmek/sıkmak")
    print(f"  {'CAP':>5s} {'toplam$':>8s} {'Δ$':>7s} {'ort risk%':>10s} {'bağlı%':>7s} "
          f"{'maxDD%':>7s} {'kötü ay%':>9s} {'poz-ay':>7s} | " +
          " ".join(f"{y:>7d}" for y in years))
    sonuc = {}
    for cap in (0.75, 1.00, 1.25, 1.50, 2.00, 3.00, 5.00):
        v = olc(taken, cap)
        sonuc[cap] = v
        mark = "  ← CANLI" if abs(cap - A.CAP) < 1e-9 else ""
        print(f"  {cap:>5.2f} {v['tot']:>+8.0f} {v['tot']-taban['tot']:>+7.0f} "
              f"{v['ort_risk']:>10.2f} {v['bagli']:>7.0f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
              f"{v['posm']:>7.0f} | " +
              " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + mark)

    # ── 3) HÜKÜM ──
    print(f"\n[3] HÜKÜM (ön-kayıtlı bar)")
    gecen = []
    for cap, v in sonuc.items():
        if abs(cap - A.CAP) < 1e-9: continue
        w = []
        if v["tot"] - taban["tot"] <= 28: w.append(f"kâr {v['tot']-taban['tot']:+.0f}$")
        for y in years:
            b = taban["yr"].get(y, 0)
            if abs(b) > 1e-9 and (v["yr"].get(y, 0) - b)/abs(b) < -0.10:
                w.append(f"{y} kötü"); break
        if v["dd"] > taban["dd"] + 2: w.append(f"maxDD {v['dd']:.1f}")
        if v["worst"] < taban["worst"] - 0.05: w.append(f"en kötü ay {v['worst']:.1f}")
        if not w:
            gecen.append(cap); print(f"  ★ GEÇTİ  CAP={cap}")
        else:
            print(f"  ✗        CAP={cap:<5.2f} — {'; '.join(w)}")
    print(f"\n  SONUÇ: {'ADAY → CAP=' + str(gecen[0]) if gecen else 'hiçbiri geçmedi.'}")
    print(f"\n  ⚠ CAP artırmak RİSKİ artırır (ort risk sütunu). 'Daha çok kâr' tek başına")
    print(f"  bulgu değildir — maxDD ve en kötü ay sütunları bedeli gösterir.")


if __name__ == "__main__":
    main()
