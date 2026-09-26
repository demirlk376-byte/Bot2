"""Canli-birebir ikiz (RR 2.5, CAP 2.5, risk %3.5) ile: alarm kalibrasyonu + 12 aylik normal bantlar."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/Bot2")
import erken_uyari as E
DB = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/ikiz_rr/ikiz_k25_cap25.db"
rows = [t for t in E.islemleri_oku(DB, paper=True) if E.kol_adi(t["strategy_scores"]) in E.AKTIF_KOLLAR]
R = np.array([E.r_net(t) for t in rows]); rk = np.array([E.islem_riski(t, 0.035, 2.5) for t in rows])
ay = pd.Series([t["exit_time"][:7] for t in rows]); gun = pd.Series([t["exit_time"][:10] for t in rows])
ay_id = pd.factorize(ay)[0]; AY = ay_id.max() + 1; ay_idx = [np.where(ay_id == a)[0] for a in range(AY)]
print(f"n={len(R)} ortR {R.mean():.4f} std {R.std():.3f} | tarih CUSUM tepe {max(E.cusum(list(R))):.1f} | NAV maxDD %{E.dusus(list(R*rk))[1]*100:.1f} | negatif ay {sum(1 for a in range(AY) if np.prod(1+R[ay_idx[a]]*rk[ay_idx[a]])<1)}/{AY}")
rng = np.random.default_rng(2028); YOL = 3000
# --- alarm kalibrasyonu (24 ay) ---
H = 24; secim = rng.integers(0, AY, size=(YOL, H))
print(f"{'dunya':<13s} {'CUSUM 12a/24a/med':>20s} {'NAV-%60 12a/24a/med':>21s} {'BIRLESIK 12a/24a/med':>22s} {'3 ay neg 12a/24a':>17s}")
for ad, e in (("edge %100", 1.0), ("edge %75", 0.75), ("edge %50", 0.5), ("edge %0", 0.0), ("edge -0.10R", None)):
    Rw = R - (1 - e) * R.mean() if e is not None else R - R.mean() - 0.10
    a_c, a_n, a_b, a_3 = [], [], [], []
    for i in range(YOL):
        idx = np.concatenate([ay_idx[a] for a in secim[i]]); am = np.concatenate([np.full(len(ay_idx[a]), m) for m, a in enumerate(secim[i])])
        x = Rw[idx]; g = x * rk[idx]
        S = 0.0; v = tepe = 1.0; ac = an = np.inf
        for j in range(len(x)):
            S = max(0.0, S + E.CUSUM_K - x[j]); v *= 1 + g[j]; tepe = max(tepe, v)
            if ac == np.inf and S > E.CUSUM_H: ac = am[j] + 1
            if an == np.inf and v < (1 - E.KIRMIZI_CIZGI) * tepe: an = am[j] + 1
        neg = [np.prod(1 + g[am == m]) < 1 for m in range(H)]
        a3 = next((m + 1 for m in range(2, H) if all(neg[m-2:m+1])), np.inf)
        a_c.append(ac); a_n.append(an); a_b.append(min(ac, an)); a_3.append(a3)
    def f(v):
        v = np.array(v); med = np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan
        return f"{np.mean(v<=12)*100:4.1f}%/{np.mean(v<=24)*100:5.1f}%/{med:3.0f}"
    g3 = np.array(a_3)
    print(f"{ad:<13s} {f(a_c):>20s} {f(a_n):>21s} {f(a_b):>22s} {np.mean(g3<=12)*100:7.1f}%/{np.mean(g3<=24)*100:5.1f}%")
# --- 12 aylik normal bantlar ---
S = []
for _ in range(4000):
    sec = rng.integers(0, AY, 12); gunr, ayr, seri, eq = [], [], [], [1.0]
    for a in sec:
        ix = ay_idx[a]; g = R[ix] * rk[ix]; gg = gun.values[ix]
        ayr.append(np.prod(1 + g) - 1)
        for d_ in np.unique(gg): gunr.append(np.prod(1 + g[gg == d_]) - 1)
        seri.extend((R[ix] < 0).astype(int)); eq.extend(eq[-1] * np.cumprod(1 + g))
    eq = np.array(eq); dd = (1 - eq / np.maximum.accumulate(eq)).max()
    b = c = 0
    for s_ in seri: c = c + 1 if s_ else 0; b = max(b, c)
    S.append((min(gunr), min(ayr), dd, b, eq[-1] - 1, sum(1 for x in ayr if x < 0)))
S = np.array(S)
print("\n12 aylik NORMAL bant (tipik | 5 yilda bir | 20 yilda bir):")
for i, ad in enumerate(["en kotu gun", "en kotu ay", "maxDD", "kayip serisi", "yil getirisi", "negatif ay"]):
    p = np.percentile(S[:, i], [50, 20, 5]) if i in (0, 1, 4) else np.percentile(S[:, i], [50, 80, 95])
    print(f"  {ad:<14s} " + " | ".join((f"%{v*100:+.1f}" if i in (0, 1, 2, 4) else f"{v:.0f}") for v in p))
print(f"  yili zararla bitirme %{(S[:,4]<0).mean()*100:.1f}")
