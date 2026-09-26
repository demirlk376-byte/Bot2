import numpy as np, pandas as pd
from rv_load import get, cboot
d = get()
F = {}
for c in d.coin.unique():
    f = pd.read_csv(f"/home/user/Bot2/data/{c}_funding_bnc.csv"); f["dt"] = pd.to_datetime(f.dt, utc=True, format="mixed")
    F[c] = f.sort_values("dt")
fr = []
for t in d.itertuples():
    f = F[t.coin]; m = (f.dt > t.tin) & (f.dt <= t.tout)
    fr.append(f.rate[m].sum())
d["fund_frac"] = fr   # cumulative funding rate over the hold (fraction of notional; longs pay if positive)
d["fund_R"] = -d.s * d.fund_frac / d.sp
print("coverage start per coin:", {c: str(F[c].dt.min())[:10] for c in F})
print(d.groupby("kol").fund_R.agg(["mean", "median", "min", "max"]).round(4))
print("ALL fund_R mean %.4f" % d.fund_R.mean())
print("median |rate| per 8h:", pd.concat([F[c].rate for c in F]).abs().median())
Rf = d.Rn + d.fund_R
for k, g in list(d.groupby("kol")) + [("ALL", d)]:
    m = cboot(Rf[g.index], g.wk); print(k, "net incl funding %+.3f [%+.3f,%+.3f]" % (Rf[g.index].mean(), *np.percentile(m, [2.5, 97.5])))
