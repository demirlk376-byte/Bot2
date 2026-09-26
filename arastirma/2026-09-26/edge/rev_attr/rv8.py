import numpy as np, pandas as pd, pickle
from rv_load import cboot
d, OH = pickle.load(open("rv4.pkl", "rb"))
rng = np.random.default_rng(8)
# decay slope: R on exit time (years), cluster bootstrap by entry month
tyr = ((d.tout - d.tout.min()).dt.total_seconds() / (365.25*86400)).values; r = d.Rn.values
b = np.polyfit(tyr, r, 1)[0]
u, inv = np.unique(d.mo_in.values, return_inverse=True); bs = []
for _ in range(4000):
    c = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))[inv].astype(float)
    X = np.vstack([np.ones_like(tyr), tyr]).T * np.sqrt(c)[:, None]; y = r*np.sqrt(c)
    bs.append(np.linalg.lstsq(X, y, rcond=None)[0][1])
print(f"trend in R_net per year: {b:+.3f} month-cluster CI [{np.percentile(bs,2.5):+.3f},{np.percentile(bs,97.5):+.3f}] over {tyr.max():.2f} yrs")
# forward drift after entry, close-to-close in R units, with week-cluster CI, vs future-only placebo (random bar in (i0, i0+45d])
H = [12, 48, 120]; W = 45*24
for k in ["donchian", "squeeze", "mean_rev"]:
    g = d[d.kol == k]
    fa = np.array([[t.s*(OH[t.coin].close.values[min(t.i0+h, len(OH[t.coin])-1)] - t.ie)/t.stop for h in H] for t in g.itertuples()])
    ff = []
    for t in g.itertuples():
        cl = OH[t.coin].close.values; n = len(cl)
        hi_ = min(n-121, t.i0+W)
        if hi_ <= t.i0+24: ff.append([np.nan]*3); continue
        dr = rng.integers(t.i0+1, hi_, 100)
        ff.append([np.mean(t.s*(cl[dr+h]-cl[dr])/(t.sp*cl[dr])) for h in H])
    ff = np.array(ff)
    s = []
    for j, h in enumerate(H):
        m = cboot(fa[:, j], g.wk.values, seed=j)
        s.append(f"h{h}: {fa[:,j].mean():+.3f} [{np.percentile(m,2.5):+.3f},{np.percentile(m,97.5):+.3f}] futnull {np.nanmean(ff[:,j]):+.3f}")
    print(f"{k:9s} " + " | ".join(s))
