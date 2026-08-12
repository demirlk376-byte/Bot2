"""
pw_bb_risk.py — ANKOR ile CANLI KOD arasında SIZING UYUŞMAZLIĞI: BB kolu.

BULUNAN (2026-08-10, CAP araştırması sırasında tesadüfen):
`execution.py:526` — BB/mean_rev kolu `risk_override = 0.0` ile gidiyor ve
`risk.py:185` bunu `max_risk_per_trade`'e düşürüyor = MAX_RISK_PCT(%8) × RISK_SCALE(1.125)
= **%9 hedef risk**. Yalnızca CAP kesiyor.

AMA ANKOR (deployed_backtest.py) TÜM kollar için `eff = min(RISKF=0.0225, CAP×slp)` kullanıyor.
BB'nin stop mesafesi medyan %2.17 olduğu için:
```
CAP=1.25 → ankor %2.14  ·  CANLI %3.24   (1.51×)
CAP=1.50 → ankor %2.21  ·  CANLI %3.86   (1.75×)
```
**Yani BB canlıda ankorun modellediğinden ~1.5 kat fazla risk alıyor.**

BU NEDEN ÖNEMLİ — iki ayrı sonucu var:
 1. Ankorun "en kötü ay −%21" tahmini BB'yi eksik riskle modelliyor → GERÇEK kuyruk daha ağır
    olabilir. Kullanıcı bir ay uzakta olacak; kuyruk tahmini yanlışsa bu doğrudan önemli.
 2. Bugün önerilen CAP 1.25→1.5 değişikliği, ankorda BB'yi neredeyse hiç etkilemiyor
    (RISKF bağlıyor) ama CANLIDA BB'nin riskini %19 artırıyor (3.24→3.86). Yani ankorda
    ölçtüğüm +$55, canlıda BB tarafında MODELLENMEMİŞ ek risk taşıyor.

BU BETİK: ankoru CANLI sizing'e uydurup farkı ölçer. Üç senaryo:
  A) ANKOR MODELİ      — BB de %2.25 (bugüne kadar varsayılan)
  B) CANLI GERÇEĞİ     — BB %9 hedef, CAP kesiyor  ← muhtemelen ŞU AN olan
  C) BB HİZALANMIŞ     — BB açıkça %2 (diğer kollarla aynı) → ankor gerçeğe uyar
Her biri CAP=1.25 ve 1.5 için.

HÜKÜM SORUSU: (B) senaryosunda kuyruk ne kadar ağırlaşıyor? Ve (C) hizalama, CAP değişikliğini
güvenli kılıyor mu?

Kullanım:  py pw_bb_risk.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

MAXR_LIVE = 0.08 * 1.125      # canlı .env: MAX_RISK_PCT × RISK_SCALE = %9
BB_ALIGNED = 0.02 * 1.125     # hizalanmış: diğer kollarla aynı (%2.25)


def havuz(source):
    """Ankorun aldığı işlemler + hangi koldan geldiği (BB'yi ayırt edebilmek için)."""
    import heapq
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            tagged.append(("trend",) + t)
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            tagged.append(("trend",) + t)
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            tagged.append(("bb",) + t)
    ev = sorted(tagged, key=lambda t: t[1])
    openh = []; ctr = 0; out = []
    for kol, entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            out.append((kol, exit_ts, R, slp))
    return out


def olc(taken, cap, bb_risk):
    """bb_risk: BB kolunun HEDEF risk oranı. Trend kolları her zaman RISKF."""
    r = np.array([t[2] for t in taken]); sp = np.array([t[3] for t in taken])
    isbb = np.array([t[0] == "bb" for t in taken])
    hedef = np.where(isbb, bb_risk, A.RISKF)
    eff = np.minimum(hedef, cap * sp)
    ex = [pd.Timestamp(t[1]) for t in taken]
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    return dict(tot=float(pnl.sum()), dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                bb_risk=float(eff[isbb].mean() * 100), bb_pay=float(pnl[isbb].sum()),
                yr={int(k): float(v) for k, v in yr.items()})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    taken = havuz(source)
    nbb = sum(1 for t in taken if t[0] == "bb")
    print(f"\n{'=' * 108}")
    print("=== ANKOR ile CANLI KOD arasında BB SIZING UYUŞMAZLIĞI ===")
    print(f"  {len(taken)} işlem ({nbb} tanesi BB) · CAP × BB hedef riski matrisi")

    ank = olc(taken, A.CAP, A.RISKF)
    ok = len(taken) == 1579 and abs(ank["tot"] - 1420.66) < 0.01
    print(f"  DOĞRULAMA (A senaryosu = ankor): ${ank['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    years = sorted(ank["yr"])

    senaryolar = [
        ("A) ANKOR MODELİ  (BB %2.25)", A.RISKF),
        ("B) CANLI GERÇEĞİ (BB %9)", MAXR_LIVE),
        ("C) BB HİZALANMIŞ (BB %2.25)", BB_ALIGNED),
    ]
    print(f"\n  {'senaryo':<28s} {'CAP':>5s} {'toplam$':>8s} {'Δ$':>7s} {'BB ort risk%':>13s} "
          f"{'BB payı$':>9s} {'maxDD%':>7s} {'en kötü ay%':>12s}")
    sonuc = {}
    for ad, br in senaryolar:
        for cap in (1.25, 1.50):
            v = olc(taken, cap, br)
            sonuc[(ad[0], cap)] = v
            mark = "  ← ŞU AN" if (ad[0] == "B" and cap == 1.25) else ""
            print(f"  {ad:<28s} {cap:>5.2f} {v['tot']:>+8.0f} {v['tot']-ank['tot']:>+7.0f} "
                  f"{v['bb_risk']:>13.2f} {v['bb_pay']:>+9.0f} {v['dd']:>7.1f} "
                  f"{v['worst']:>+12.1f}{mark}")

    print(f"\n  --- YIL KIRILIMI ---")
    print(f"  {'senaryo':<28s} {'CAP':>5s} | " + " ".join(f"{y:>7d}" for y in years))
    for (s, cap), v in sonuc.items():
        ad = [a for a, _ in senaryolar if a[0] == s][0]
        print(f"  {ad:<28s} {cap:>5.2f} | " +
              " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years))

    # ── HÜKÜM ──
    b125 = sonuc[("B", 1.25)]; b150 = sonuc[("B", 1.50)]
    c150 = sonuc[("C", 1.50)]
    print(f"\n{'=' * 108}\n=== HÜKÜM ===")
    print(f"\n  1) ŞU ANKİ GERÇEK (B, CAP=1.25) vs ANKORUN SANDIĞI (A, CAP=1.25):")
    print(f"     kâr ${ank['tot']:+.0f} → ${b125['tot']:+.0f} ({b125['tot']-ank['tot']:+.0f})")
    print(f"     en kötü ay {ank['worst']:+.1f} → {b125['worst']:+.1f} "
          f"({b125['worst']-ank['worst']:+.1f} puan)")
    print(f"     maxDD {ank['dd']:.1f} → {b125['dd']:.1f}")
    print(f"     → Ankorun kuyruk tahmini {'DOĞRU' if abs(b125['worst']-ank['worst'])<1 else 'EKSİK'}")
    print(f"\n  2) CAP 1.25→1.5, CANLI gerçeğinde (B):")
    print(f"     kâr {b150['tot']-b125['tot']:+.0f}$ · en kötü ay "
          f"{b125['worst']:+.1f} → {b150['worst']:+.1f} ({b150['worst']-b125['worst']:+.1f}p)")
    print(f"\n  3) BB HİZALANIP CAP 1.5 yapılırsa (C):")
    print(f"     kâr ${c150['tot']:+.0f} ({c150['tot']-b125['tot']:+.0f} bugüne göre) · "
          f"en kötü ay {c150['worst']:+.1f} · maxDD {c150['dd']:.1f}")


if __name__ == "__main__":
    main()
