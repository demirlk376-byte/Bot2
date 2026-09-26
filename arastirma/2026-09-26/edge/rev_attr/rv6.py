import numpy as np, pandas as pd, json
from scipy import stats
from rv_load import get, cboot
rng = np.random.default_rng(77)
for path in ["/home/user/Bot2/ikiz_k25_cap25_islemler.csv", "/home/user/Bot2/ikiz_k25_eski_islemler.csv"]:
    d = get(path); print("\n########", path.split("/")[-1], "n", len(d), "meanR %.3f" % d.Rn.mean())
    tot = d.Rn.sum()
    for key in ["coin", "mo"]:
        s = d.groupby(key).Rn.sum().sort_values(ascending=False); pos = s[s > 0]; hhi = ((pos/pos.sum())**2).sum()
        print(f"{key}: groups {len(s)} positive {len(pos)} HHI {hhi:.3f} effN {1/hhi:.1f} top3 {s.iloc[:3].sum()/tot:.3f} top5 {s.iloc[:5].sum()/tot:.3f} rm_top3 {s.iloc[3:].sum():+.1f}")
    # month permutation (exit month), and also a null where each trade's R is resampled within sleeve (keeps sleeve mix per month)
    u, inv = np.unique(d.mo.values, return_inverse=True); r = d.Rn.values
    kol = d.kol.values
    def stats_(x):
        ms = np.bincount(inv, weights=x); srt = np.sort(ms)[::-1]
        return srt[:5].sum()/x.sum(), (ms > 0).mean(), ms.std()
    o = stats_(r); N1 = np.array([stats_(rng.permutation(r)) for _ in range(5000)])
    # within-sleeve permutation
    def perm_within(x):
        y = x.copy()
        for k in np.unique(kol):
            m = kol == k; y[m] = rng.permutation(x[m])
        return y
    N2 = np.array([stats_(perm_within(r)) for _ in range(5000)])
    print(f"months n={len(u)} obs top5 {o[0]:.3f} pos {o[1]:.3f} sd {o[2]:.2f}")
    for lab, N in [("perm-all", N1), ("perm-within-sleeve", N2)]:
        print(f"  {lab}: top5 med {np.median(N[:,0]):.3f} p={np.mean(N[:,0]>=o[0]):.3f} | pos med {np.median(N[:,1]):.3f} p(<=)={np.mean(N[:,1]<=o[1]):.3f} | sd med {np.median(N[:,2]):.2f} p={np.mean(N[:,2]>=o[2]):.3f}")
    # overdispersion of monthly mean R: F-like stat, between-month variance of mean
    cnt = np.bincount(inv)
    st = lambda x: (cnt*(np.bincount(inv, weights=x)/cnt - x.mean())**2).sum()
    ob = st(r); nb = np.array([st(rng.permutation(r)) for _ in range(5000)])
    print(f"  between-month variance of mean R: p={np.mean(nb>=ob):.3f}")
    # years
    uy, iy = np.unique(d.yr.values, return_inverse=True); cy = np.bincount(iy)
    sty = lambda x: (cy*(np.bincount(iy, weights=x)/cy - x.mean())**2).sum()
    print(f"  year heterogeneity perm p={np.mean(np.array([sty(rng.permutation(r)) for _ in range(5000)])>=sty(r)):.3f}  yearly means", d.groupby('yr').Rn.mean().round(3).to_dict())
    # coins within sleeve
    for k, g in d.groupby("kol"):
        if g.coin.nunique() < 2: continue
        uc, ic = np.unique(g.coin.values, return_inverse=True); cc = np.bincount(ic); x = g.Rn.values
        stc = lambda z: (cc*(np.bincount(ic, weights=z)/cc - z.mean())**2).sum()
        print(f"  coin heterogeneity {k}: p={np.mean(np.array([stc(rng.permutation(x)) for _ in range(5000)])>=stc(x)):.3f}")
    print("  by split x kol mean R:", d.groupby(["split", "kol"]).Rn.agg(["size", "mean"]).round(3).to_dict())
    xm = d.exit_price/(1-d.s*0.24e-4); Rg = d.s*(xm-d.ie)/d.stop
    print("  cost share by kol:", ((Rg - d.Rn).groupby(d.kol).mean()/Rg.groupby(d.kol).mean()).round(3).to_dict(), " gross:", Rg.groupby(d.kol).mean().round(3).to_dict())
