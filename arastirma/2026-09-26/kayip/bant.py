"""Normal kayip bantlari: IKIZ taban islemlerinden ay-blok bootstrap (ay ici sira/eszamanlilik korunur)."""
import numpy as np, pandas as pd
d = pd.read_pickle("islemler3.pkl").sort_values("cikis").reset_index(drop=True)
R_net = (d.ret / d.risk_pct).values
cap_bag = d.risk_pct.values < 0.0345                      # tavana takilmis olanlar (hedef %3.5)
def risk_cap(cap):
    # tavana takilan islemin riski cap ile orantili buyur, hedef %3.5'i gecemez
    return np.where(cap_bag, np.minimum(0.035, d.risk_pct.values * cap / 1.5), d.risk_pct.values)
aylar = d.ay.unique(); rng = np.random.default_rng(2026)
def yol(r):
    secim = rng.choice(len(aylar), 12, replace=True)
    gun_r, ay_r, seri, eq = [], [], [], [1.0]
    for a in secim:
        m = (d.ay == aylar[a]).values
        x = r[m]; gunler = d.cikis[m].dt.floor("D").values
        ay_r.append(np.prod(1 + x) - 1)
        for gnn in np.unique(gunler): gun_r.append(np.prod(1 + x[gunler == gnn]) - 1)
        seri.extend((x < 0).astype(int)); eq.extend(eq[-1] * np.cumprod(1 + x))
    eq = np.array(eq); dd = (1 - eq / np.maximum.accumulate(eq)).max()
    s = b = 0
    for v in seri: s = s + 1 if v else 0; b = max(b, s)
    return min(gun_r), min(ay_r), dd, b, eq[-1] - 1, sum(1 for v in ay_r if v < 0)
for ad, cap, kes in (("CAP 1.5 (bugunku), IKIZ aynen", 1.5, 0.0), ("CAP 2.5, IKIZ aynen", 2.5, 0.0),
                     ("CAP 1.5, edge %75", 1.5, 0.25), ("CAP 2.5, edge %75", 2.5, 0.25)):
    r = (R_net - kes * R_net.mean()) * risk_cap(cap)
    S = np.array([yol(r) for _ in range(4000)])
    print(f"\n=== {ad}: 12 aylik 'NORMAL' kayip bantlari (4000 yol, IKIZ islemleri) ===")
    for i, ad2 in enumerate(["en kotu GUN", "en kotu AY", "yil ici maxDD", "en uzun kayip serisi", "yil sonu getiri (katkisiz)", "zararli ay sayisi (12'de)"]):
        p = np.percentile(S[:, i], [50, 80, 95]) if i not in (0, 1, 4) else np.percentile(S[:, i], [50, 20, 5])
        f = (lambda v: f"%{v*100:+.1f}") if i in (0, 1, 2, 4) else (lambda v: f"{v:.0f}")
        print(f"  {ad2:<28s} tipik {f(p[0]):>8s} | 5 yilda 1 {f(p[1]):>8s} | 20 yilda 1 {f(p[2]):>8s}")
    print(f"  yili ZARARLA bitirme olasiligi (katkisiz): %{(S[:, 4] < 0).mean()*100:.1f}")
