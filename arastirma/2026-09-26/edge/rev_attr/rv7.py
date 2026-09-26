import numpy as np, pandas as pd
from scipy import stats
from rv_load import get
rng = np.random.default_rng(5)
d = get()
L = (d.Rn <= 0).values  # loss (exit order)
def longest(b):
    m = c = 0
    for v in b:
        c = c + 1 if v else 0; m = max(m, c)
    return m
obs = longest(L); print("longest losing run (exit order):", obs, " (entry order):", longest((d.sort_values('tin').Rn <= 0).values))
q = L.mean(); n = len(L)
sims = np.array([longest(rng.random(n) < q) for _ in range(20000)])
print(f"iid q={q:.3f}: E[longest]={sims.mean():.2f} median={np.median(sims)} 95%={np.percentile(sims,95)} P(>=obs)={np.mean(sims>=obs):.3f}")
sh = np.array([longest(rng.permutation(L)) for _ in range(20000)])
print(f"shuffle: median={np.median(sh)} mean={sh.mean():.2f} 95%={np.percentile(sh,95)} P(>=obs)={np.mean(sh>=obs):.3f}")
p = 1-q
print("Schilling log_{1/q}(n p) = %.2f ; + gamma/ln(1/q) - 1/2 = %.2f" % (np.log(n*p)/np.log(1/q), np.log(n*p)/np.log(1/q) + 0.5772/np.log(1/q) - 0.5))
# regime
b = pd.read_csv("/home/user/Bot2/data/BTC_fut_1h.csv"); b["ts"] = pd.to_datetime(b.ts, utc=True); b = b.drop_duplicates("ts").set_index("ts").close
bm = np.log(b).groupby(b.index.strftime("%Y-%m")).agg(["first", "last"])
bret = (bm["last"] - bm["first"])  # within-month log return (first to last hourly close)
M = d.groupby("mo").agg(R=("Rn", "sum"), n=("Rn", "size"))
for k in ["donchian", "squeeze", "mean_rev"]:
    g = d[d.kol == k].groupby("mo").Rn
    M[k] = g.sum(); M[k + "_n"] = g.size(); M[k + "_mean"] = g.mean()
M = M.join(bret.rename("btc")).fillna(0); M["abs"] = M.btc.abs()
print("months:", len(M))
ps = []
for y in ["R", "donchian", "squeeze", "mean_rev"]:
    for x in ["btc", "abs"]:
        r, pv = stats.spearmanr(M[x], M[y]); ps.append(pv); print(f"  {y:9s} vs {x:4s} rho {r:+.2f} p {pv:.3f}")
r, pv = stats.spearmanr(M["abs"], M["donchian_n"]); print(f"  donchian trade count vs |btc| rho {r:+.2f} p {pv:.3f}")
mm = M[M.donchian_n > 0]; r, pv = stats.spearmanr(mm["abs"], mm["donchian_mean"]); print(f"  donchian MEAN R vs |btc| rho {r:+.2f} p {pv:.3f} (n={len(mm)})")
# equity-weighted monthly return vs BTC (beta OLS)
Me = d.groupby("mo").lg.sum()
X = pd.concat([Me.rename("lg"), bret.rename("btc")], axis=1).dropna()
sl = stats.linregress(X.btc, X.lg); print(f"  monthly log-equity vs BTC: beta {sl.slope:+.3f} p {sl.pvalue:.3f} n {len(X)}")
sl = stats.linregress(X.btc.abs(), X.lg); print(f"  monthly log-equity vs |BTC|: slope {sl.slope:+.3f} p {sl.pvalue:.3f}")
