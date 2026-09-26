import numpy as np, pandas as pd
from scipy import stats
from rv_load import get, cboot, RR
d = get()
rr = d.kol.map(RR)
# independent gross reconstruction: exit market price
xm = d.exit_price / (1 - d.s * 0.24e-4)
Rg_mkt = d.s * (xm - d.ie) / d.stop
tp = d.exit_reason == "tp_hit"; sl = d.exit_reason == "sl_hit"; mh = d.exit_reason == "max_hold"
print("tp gross R vs RR: max abs dev", (Rg_mkt[tp] - rr[tp]).abs().max(), " sl gross vs -1:", (Rg_mkt[sl] + 1).abs().max())
# gaps? any sl exit beyond sl0
# costs
fee = 1e-4
slip_in = d.s * (d.ie - d.entry_price) / d.stop
fees = -fee * (d.entry_price + d.exit_price) / d.stop
slip_out = d.s * (d.exit_price - xm) / d.stop
fund = d.Rn - (Rg_mkt + slip_in + fees + slip_out)
T = pd.DataFrame(dict(kol=d.kol, g=Rg_mkt, si=slip_in, so=slip_out, fe=fees, fu=fund, n=d.Rn))
t = T.groupby("kol").mean(); t.loc["ALL"] = T.drop(columns="kol").mean()
t["cost"] = t.n - t.g; t["share"] = -t.cost / t.g
t["sp_med"] = list(d.groupby("kol").sp.median()) + [d.sp.median()]
print(t.round(4))
# is fund plausible? funding magnitude per trade in bp of notional
fund_bp = fund * d.stop / d.ie * 1e4
print("funding bp of notional by kol:", fund_bp.groupby(d.kol).describe()[["mean","min","max"]].round(2))
# gross CI
for k, g in list(d.groupby("kol")) + [("ALL", d)]:
    m = cboot(Rg_mkt[g.index], g.wk); print(k, "gross %+.3f [%+.3f,%+.3f]" % (Rg_mkt[g.index].mean(), *np.percentile(m, [2.5, 97.5])))
# gross difference donchian - squeeze
a = cboot(Rg_mkt[d.kol=="donchian"], d.wk[d.kol=="donchian"], seed=5); b = cboot(Rg_mkt[d.kol=="squeeze"], d.wk[d.kol=="squeeze"], seed=6)
print("gross don - sq: %+.3f CI [%+.3f,%+.3f]" % (Rg_mkt[d.kol=="donchian"].mean()-Rg_mkt[d.kol=="squeeze"].mean(), *np.percentile(a-b, [2.5, 97.5])))
# slip_in in R = 15.85bp / sp -> mean(1/sp)
print("squeeze mean 15.85bp/sp:", (15.85e-4 / d.sp[d.kol=='squeeze']).mean())
# shape
print("\n== shape")
def shape(r, lab):
    w = r[r > 0]; l = r[r <= 0]; srt = np.sort(r)[::-1]; T = r.sum(); n = len(r)
    k10 = int(round(0.1 * n))
    print(f"{lab:9s} n={n} WR={len(w)/n:.3f} mW={w.mean():+.3f} mL={l.mean():+.3f} payoff={w.mean()/-l.mean():.3f} skew={stats.skew(r):+.3f} "
          f"top5={srt[:int(round(.05*n))].sum()/T:.3f} top10={srt[:k10].sum()/T:.3f} top20={srt[:int(round(.2*n))].sum()/T:.3f} wo_top10={srt[k10:].sum():+.1f} max={r.max():+.3f}")
shape(d.Rn.values, "ALL")
for k, g in d.groupby("kol"): shape(g.Rn.values, k)
lg = np.sort(d.lg.values)[::-1]; print("log wo top10%:", lg[94:].sum())
# what fraction of top 10% are tp hits
top = d.nlargest(94, "Rn"); print("top94 exit reasons", top.exit_reason.value_counts().to_dict(), "min R", top.Rn.min())
# counterfactual: remove top 10% of a symmetric bracket null? Compare: for a zero-edge bracket with same WR structure, top10% removal
# break-even
print("\n== break-even")
def wilson(k, n, z=1.96):
    p = k/n; den = 1+z*z/n; c = (p+z*z/(2*n))/den; h = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den; return c-h, c+h
rng = np.random.default_rng(3)
for k, g in list(d.groupby("kol")) + [("ALL", d)]:
    r = g.Rn.values; w = r > 0; b = r[w].mean() / -r[~w].mean(); be = 1/(1+b)
    # cluster bootstrap on margin with weights
    u, inv = np.unique(g.wk.values, return_inverse=True); reps = []
    for _ in range(3000):
        c = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))[inv].astype(float)
        W = (c * w).sum() / c.sum(); mw = (c*r*w).sum()/(c*w).sum(); ml = -(c*r*~w).sum()/(c*~w).sum()
        reps.append(W - 1/(1+mw/ml))
    p = stats.binomtest(w.sum(), len(r), be, alternative="greater").pvalue
    print(f"{k:9s} WR={w.mean():.3f} W{tuple(np.round(wilson(w.sum(), len(r)),3))} payoff={b:.3f} BE={be:.3f} margin={w.mean()-be:+.3f} CI[{np.percentile(reps,2.5):+.3f},{np.percentile(reps,97.5):+.3f}] binom p={p:.2g} extra wins={(w.mean()-be)*len(r):.1f}")
    if k != "ALL":
        st = g[g.exit_reason.isin(["sl_hit","tp_hit"])]; ktp = (st.exit_reason=="tp_hit").sum(); n = len(st); p0 = 1/(1+RR[k])
        # cluster-robust: bootstrap TP share by week
        x = (st.exit_reason=="tp_hit").astype(float).values
        m = cboot(x, st.wk.values, seed=9)
        print(f"          TP|res {ktp}/{n}={ktp/n:.3f} vs {p0:.3f} binom p={stats.binomtest(ktp,n,p0,alternative='greater').pvalue:.3g}  week-boot CI [{np.percentile(m,2.5):.3f},{np.percentile(m,97.5):.3f}] P(boot<=p0)={np.mean(m<=p0):.3f}")
st = d[d.exit_reason.isin(["sl_hit","tp_hit"])]; print("ALL TP share", (st.exit_reason=="tp_hit").mean(), len(st))
