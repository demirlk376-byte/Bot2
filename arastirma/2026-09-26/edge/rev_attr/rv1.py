import numpy as np, pandas as pd
from scipy import stats
from rv_load import get, cboot, RR
d = get()
print("n", len(d), "sumR %.1f meanR %.4f final eq %.0f log %.3f" % (d.Rn.sum(), d.Rn.mean(), 1e4 + d.pnl_usdt.sum(), d.lg.sum()))
# CIs on overall mean: week, month (entry), and 2-week clusters; also HAC on daily series
for lab, cl in [("week", d.wk), ("2week", d.wk // 2), ("month_in", d.mo_in), ("quarter", d.tin.dt.year*10 + d.tin.dt.quarter)]:
    m = cboot(d.Rn, cl)
    print(f"ALL mean CI by {lab:8s} nclust={cl.nunique()}: [{np.percentile(m,2.5):+.3f},{np.percentile(m,97.5):+.3f}] p(<=0)={np.mean(m<=0):.4f}")
# t-test iid
t = stats.ttest_1samp(d.Rn, 0); print("iid t p (2s)=%.2g" % t.pvalue)
# HAC: daily sum of R by entry day, Newey-West on mean per trade
day = d.groupby(d.tin.dt.floor("D")).Rn.agg(["sum", "size"])
alld = pd.date_range(day.index.min(), day.index.max(), freq="D")
day = day.reindex(alld, fill_value=0)
y = day["sum"].values; nn = day["size"].values
mu = y.sum() / nn.sum(); e = y - mu * nn
def nw(e, L):
    g0 = (e*e).sum(); s = g0
    for l in range(1, L+1): s += 2*(1-l/(L+1))*(e[l:]*e[:-l]).sum()
    return s
for L in [0, 7, 14, 30]:
    se = np.sqrt(nw(e, L)) / nn.sum()
    print(f"HAC daily L={L}: mean {mu:+.4f} se {se:.4f} z {mu/se:.2f} p2 {2*stats.norm.sf(mu/se):.2g}")
# by groups
def grp(by):
    out = []
    for k, g in d.groupby(by):
        m = cboot(g.Rn, g.wk)
        out.append((k, len(g), g.Rn.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5), np.mean(m <= 0), g.Rn.sum(), g.Rn.sum()/d.Rn.sum(), g.lg.sum()/d.lg.sum()))
    print(pd.DataFrame(out, columns=["k","n","mean","lo","hi","p<=0","sumR","shR","shLog"]).round(3).to_string(index=False))
d["ks"] = d.kol + "_" + d.side
for by in ["kol", "side", "ks", "exit_reason", "yr", "split", "coin"]:
    print("==", by); grp(by)
d["hb"] = pd.cut(d.hold, [0, 6, 24, 48.5, 1e9], labels=["<=6", "6-24", "24-48", ">48"])
print("== hold"); grp("hb")
print(pd.crosstab(d.hb, d.kol))
