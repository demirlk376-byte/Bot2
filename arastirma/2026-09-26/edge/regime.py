"""Monthly book R vs BTC monthly return (signed) and |return| / realized vol: is the edge beta or long-volatility?
Also: year heterogeneity and TRAIN-TEST difference."""
import numpy as np, pandas as pd
from scipy import stats
from load import load
rng = np.random.default_rng(3)
d = load()
b = pd.read_csv("/home/user/Bot2/data/BTC_fut_1h.csv"); b["ts"] = pd.to_datetime(b.ts, utc=True)
b = b.set_index("ts").close
bm = b.resample("ME").last()
mret = np.log(bm).diff()
rv = np.log(b).diff().groupby(b.index.to_period("M") if False else b.index.tz_localize(None).to_period("M")).std() * np.sqrt(24 * 30)
mret.index = mret.index.tz_localize(None).to_period("M")
M = pd.DataFrame({"R": d.groupby("month").R_net.sum(), "n": d.groupby("month").size()})
for k in ["donchian", "squeeze", "mean_rev"]:
    M[k] = d[d.kol == k].groupby("month").R_net.sum()
M = M.join(mret.rename("btc")).join(rv.rename("rv")).fillna({"donchian": 0, "squeeze": 0, "mean_rev": 0}).dropna()
M["absbtc"] = M.btc.abs()
print(f"months={len(M)}")
for y in ["R", "donchian", "squeeze", "mean_rev"]:
    out = []
    for x in ["btc", "absbtc", "rv"]:
        r, p = stats.spearmanr(M[x], M[y]); out.append(f"{x}: rho={r:+.2f} p={p:.3f}")
    print(f"  {y:9s} " + " | ".join(out))
# per-trade: side-signed BTC log return over the hold vs R
bt = b.reindex(pd.date_range(b.index.min(), b.index.max(), freq="h")).ffill()
d["btc_hold"] = np.log(bt.reindex(d.t_out.dt.floor("h")).values / bt.reindex(d.t_in.dt.floor("h")).values)
d["btc_signed"] = d.sg * d.btc_hold
for k, g in list(d.groupby("kol")) + [("ALL", d)]:
    r, p = stats.spearmanr(g.btc_signed, g.R_net)
    print(f"  per-trade {k:9s} spearman(R_net, side*BTC ret over hold) = {r:+.2f} p={p:.2g}; "
          f"frac of trades whose side agreed with BTC over hold {(g.btc_signed>0).mean():.2f}")
# net long/short mix by year and BTC yearly ret
by = d.groupby("year").agg(n=("R_net", "size"), long_share=("sg", lambda s: (s > 0).mean()),
                           R_long=("R_net", lambda s: s[d.loc[s.index, 'sg'] > 0].mean()),
                           R_short=("R_net", lambda s: s[d.loc[s.index, 'sg'] < 0].mean()))
yr = np.log(b.resample("YE").last() / b.resample("YE").first()); yr.index = yr.index.year
print(by.join(yr.rename("btc_logret")).round(3).to_string())
# year heterogeneity: permutation of R across trades, stat = weighted between-year variance
u, inv = np.unique(d.year, return_inverse=True); cnt = np.bincount(inv); r = d.R_net.values
st = lambda x: (cnt * (np.bincount(inv, weights=x) / cnt - x.mean()) ** 2).sum()
o = st(r); nul = np.array([st(rng.permutation(r)) for _ in range(5000)])
print(f"year heterogeneity of mean R_net: perm p={(nul >= o).mean():.3f}")
tr, te = d[d.split == "TRAIN"], d[d.split == "TEST"]
# difference TEST-TRAIN with week-cluster bootstrap within each split
def cb(g, reps=4000):
    u, inv = np.unique(g.week.astype(str), return_inverse=True); sm = np.bincount(inv, weights=g.R_net.values); ct = np.bincount(inv).astype(float)
    ii = rng.integers(0, len(u), (reps, len(u))); return sm[ii].sum(1) / ct[ii].sum(1)
dd = cb(te) - cb(tr)
print(f"TEST-TRAIN mean R_net diff {te.R_net.mean()-tr.R_net.mean():+.3f} 95% [{np.percentile(dd,2.5):+.3f},{np.percentile(dd,97.5):+.3f}]")
# squeeze long vs short difference
for k in ["squeeze", "donchian", "mean_rev"]:
    g = d[d.kol == k]; L = g[g.sg > 0]; S = g[g.sg < 0]
    dd = cb(S) - cb(L)
    print(f"{k}: short-long mean R diff {S.R_net.mean()-L.R_net.mean():+.3f} 95% [{np.percentile(dd,2.5):+.3f},{np.percentile(dd,97.5):+.3f}] (nL={len(L)}, nS={len(S)})")
