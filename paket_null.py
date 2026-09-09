"""
paket_null.py — kol ağırlığı paketini AY-ETİKETİ KARIŞTIRMA null'una karşı sınar.

NEDEN BU TEST: `kol_agirlik.py` paketin en kötü ayı +4.84 puan iyileştirdiğini
ve bunun 6/6 walk-forward diliminde tekrarlandığını gösterdi. Ama o dilimler
BAĞIMSIZ DEĞİL — hepsi aynı 40 ayı paylaşıyor. Tutarlılık, gerçeklik demek değil.

Çok-ajanlı taramanın (2026-09-09) en önemli bulgusu şuydu: işlemler aylara
RASTGELE dağıtıldığında null 6.9 kötü ay ve en kötü ay %−27.21 üretiyor;
gözlenen 8 ay (p=0.81) ve %−26.38 (p=0.50) null'un TAM ORTASINDA. Yani
"kötü ay" ayırt edilebilir bir nesne DEĞİL, %43.5 isabetli bir trend
sisteminin binom aritmetiği.

Bu doğruysa, "en kötü ayı iyileştirmek" de bir yeniden-etiketleme artefaktı
olabilir. Doğru null: işlemleri (ve dolayısıyla paketin etkisini) aynı
bırakıp AY ETİKETLERİNİ karıştırmak.

⚠ ÇOKLU KARŞILAŞTIRMA: 5 istatistik bakılıyor. Bonferroni eşiği 0.05/5 = 0.01.
   Bir istatistiğin ham p'si 0.05'i geçmesi TEK BAŞINA yeterli değildir.

Kullanım:  py paket_null.py [tekrar]
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
from kol_agirlik import yukle, agirlikli

PAKET = {"donchian": 1.0, "squeeze": 1.5, "bb": 0.5}
TOHUM = 20260909


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    df = yukle()
    R = df["R"].values
    e_t = df["eff"].values
    e_p = agirlikli(df, PAKET)
    ay = df["ay"].values
    rng = np.random.default_rng(TOHUM)

    # ⚠ ÖLÇEK: pnl = R × eff × BAL0, aylık yüzde = pnl / BAL0 × 100 = R × eff × 100.
    # İlk sürümde BAL0 ile çarpmayı unutmuştum; p değerleri (ölçekten bağımsız)
    # doğruydu ama basılan büyüklükler 190 kat küçüktü.
    def aylik(e, ay_k):
        return pd.Series(R * e * 100.0, index=ay_k).groupby(level=0).sum()

    def maxdd(e, idx):
        eq = A.BAL0 + np.cumsum((R * e * A.BAL0)[idx])
        return A.maxdd(np.concatenate([[A.BAL0], eq]))

    sira = np.arange(len(df))
    gt, gp = aylik(e_t, ay), aylik(e_p, ay)
    # yön: +1 = büyük iyi, -1 = küçük iyi
    olcu = {
        "en kötü ay":  (gp.min() - gt.min(), +1),
        "maxDD":       (maxdd(e_p, sira) - maxdd(e_t, sira), -1),
        "aylık std":   (gp.std() - gt.std(), -1),
        "%10 dilim":   (gp.quantile(.10) - gt.quantile(.10), +1),
        "Sharpe":      (gp.mean() / gp.std() - gt.mean() / gt.std(), +1),
    }
    null = {k: [] for k in olcu}
    for _ in range(N):
        perm = rng.permutation(len(df))
        ay_k = ay[perm]
        a_t, a_p = aylik(e_t, ay_k), aylik(e_p, ay_k)
        null["en kötü ay"].append(a_p.min() - a_t.min())
        null["aylık std"].append(a_p.std() - a_t.std())
        null["%10 dilim"].append(a_p.quantile(.10) - a_t.quantile(.10))
        null["Sharpe"].append(a_p.mean() / a_p.std() - a_t.mean() / a_t.std())
        null["maxDD"].append(maxdd(e_p, perm) - maxdd(e_t, perm))

    print(f"\n{'=' * 92}")
    print(f"=== PAKET vs AY-KARIŞTIRMA NULL'U ===  ({N:,} tekrar)")
    print(f"  paket: donchian {PAKET['donchian']} · squeeze {PAKET['squeeze']} · bb {PAKET['bb']}")
    print(f"  Bonferroni eşiği (5 istatistik): p < 0.010\n")
    print(f"  {'istatistik':<13s} {'gerçek':>9s} {'null ort':>9s} {'null %5–95':>19s} "
          f"{'ham p':>7s}  hüküm")
    ham_p = {}
    for k, (v, yon) in olcu.items():
        n = np.array(null[k])
        p = (n >= v).mean() if yon > 0 else (n <= v).mean()
        ham_p[k] = p
        lo, hi = np.percentile(n, [5, 95])
        if p < 0.010: h = "✓✓ Bonferroni'yi de geçti"
        elif p < 0.05: h = "~ ham p<0.05, DÜZELTMEYİ GEÇMEZ"
        elif p < 0.10: h = "~ sınırda"
        else: h = "✗ null da üretiyor"
        print(f"  {k:<13s} {v:>+9.3f} {n.mean():>+9.3f}  [{lo:>+7.3f},{hi:>+7.3f}] "
              f"{p:>7.4f}  {h}")
    gecen = [k for k, p in ham_p.items() if p < 0.010]
    print(f"\n  Bonferroni'yi geçen istatistik: {len(gecen)}/5"
          f"{' — ' + ', '.join(gecen) if gecen else ''}")
    if not gecen:
        print(f"  → Paketin etkisi, ay etiketlerini karıştırmakla ÜRETİLEBİLİYOR.")
        print(f"    Walk-forward tutarlılığı (6/6 dilim) bunu kurtarmıyor: o dilimler")
        print(f"    bağımsız değil, hepsi aynı 40 ayı paylaşıyor.")
    print(f"{'=' * 92}\n")


if __name__ == "__main__":
    main()
