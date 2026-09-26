"""erken_uyari.py'nin KENDI tanimlariyla kalibrasyon: R-CUSUM (k,h) + birim deger -%60, birlesik alarm."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/Bot2")
import erken_uyari as E
d = pd.read_csv("/home/user/Bot2/ikiz_a_taban_islemler.csv")
d = d.sort_values(["exit_time", "entry_time"]).reset_index(drop=True)
rows = d.to_dict("records")
R = np.array([E.r_net(t) for t in rows]); rk = np.array([E.islem_riski(t, 0.035, 1.5) for t in rows])
ay_id = pd.factorize(d.exit_time.str[:7])[0]; AY = ay_id.max() + 1
ay_idx = [np.where(ay_id == a)[0] for a in range(AY)]
print(f"arac R ort {R.mean():.4f} std {R.std():.3f} | tarih boyu CUSUM tepe {max(E.cusum(list(R))):.1f} | birim deger maxDD %{E.dusus(list(R*rk))[1]*100:.1f}")
H = 24; YOL = 3000; rng = np.random.default_rng(2027)
secim = rng.integers(0, AY, size=(YOL, H))
print(f"{'dunya':<14s} {'CUSUM>35 12a/24a/med':>22s} {'NAV-%60 12a/24a/med':>21s} {'BIRLESIK 12a/24a/med':>22s}")
for ad, e in (("edge %100", 1.0), ("edge %75", 0.75), ("edge %50", 0.5), ("edge %0", 0.0), ("edge -0.10R", None)):
    Rw = R - (1 - e) * R.mean() if e is not None else R - R.mean() - 0.10
    a_c, a_n, a_b = [], [], []
    for i in range(YOL):
        idx = np.concatenate([ay_idx[a] for a in secim[i]])
        ay = np.concatenate([np.full(len(ay_idx[a]), m) for m, a in enumerate(secim[i])])
        x = Rw[idx]; g = x * rk[idx]
        S = 0.0; v = tepe = 1.0; ac = an = np.inf
        for j in range(len(x)):
            S = max(0.0, S + E.CUSUM_K - x[j])
            v *= 1 + g[j]; tepe = max(tepe, v)
            if ac == np.inf and S > E.CUSUM_H: ac = ay[j] + 1
            if an == np.inf and v < (1 - E.KIRMIZI_CIZGI) * tepe: an = ay[j] + 1
            if ac < np.inf and an < np.inf: break
        a_c.append(ac); a_n.append(an); a_b.append(min(ac, an))
    def f(v):
        v = np.array(v); med = np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan
        return f"{np.mean(v<=12)*100:5.1f}%/{np.mean(v<=24)*100:5.1f}%/{med:4.0f}"
    print(f"{ad:<14s} {f(a_c):>22s} {f(a_n):>21s} {f(a_b):>22s}")
