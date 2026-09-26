import sys
import numpy as np, pandas as pd
OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/"
tag = sys.argv[1]
d = pd.read_pickle(OUT + f"{tag}_trades.pkl")
M = dict(np.load(OUT + f"{tag}_draws.npz"))
K = M["a"].shape[1]
rng = np.random.default_rng(1)
d["month"] = d.et.dt.strftime("%Y-%m")
B = 4000

def cluster_boot(x, cl, B=B):
    """month-cluster bootstrap of the mean of x; returns (lo, hi, p_le0 one-sided)."""
    u, inv = np.unique(cl, return_inverse=True)
    s = np.bincount(inv, weights=x); c = np.bincount(inv)
    idx = rng.integers(0, len(u), size=(B, len(u)))
    bm = s[idx].sum(1) / c[idx].sum(1)
    return np.percentile(bm, 2.5), np.percentile(bm, 97.5), (1 + (bm <= 0).sum()) / (B + 1)

groups = [("ALL", d.index)]
for sp in ("TRAIN", "TEST"):
    groups.append((f"ALL/{sp}", d.index[d.split == sp]))
for k in ("donchian", "squeeze", "mean_rev"):
    groups.append((k, d.index[d.kol == k]))
    for sp in ("TRAIN", "TEST"):
        groups.append((f"{k}/{sp}", d.index[(d.kol == k) & (d.split == sp)]))

PL = [("a", "same time, random dir"), ("b", "same dir, t±30d"), ("b_wk", "same dir, ±1-4 wk"),
      ("b_vol", "b, ATR-scaled stop"), ("b_fwd", "same dir, t+1..30d (late)"), ("b_bwd", "same dir, t-30..-1d (hindsight)"), ("d", "same dir, random t"), ("c", "random t+dir"),
      ("c_vol", "c, ATR-scaled stop")]
rows = []
for gname, ix in groups:
    x = d.loc[ix, "simR"].values; cl = d.loc[ix, "month"].values
    lo, hi, _ = cluster_boot(x, cl)
    row = dict(group=gname, n=len(ix), twinR=d.loc[ix, "R_net"].mean(), act=x.mean(), act_lo=lo, act_hi=hi,
               nocost=d.loc[ix, "R_nocost"].mean())
    for p, _ in PL:
        m = M[p][ix]
        dm = m.mean(0)                      # K draw means
        row[p] = dm.mean(); row[p + "_sd"] = dm.std(ddof=1)
        row[p + "_q"] = (np.percentile(dm, 2.5), np.percentile(dm, 97.5))
        row[p + "_pdraw"] = (1 + (dm >= x.mean()).sum()) / (K + 1)
        diff = x - m.mean(1)                # paired per-trade difference vs placebo expectation
        l2, h2, pb = cluster_boot(diff, cl)
        row[p + "_diff"] = diff.mean(); row[p + "_dlo"] = l2; row[p + "_dhi"] = h2; row[p + "_pboot"] = pb
    rows.append(row)
T = pd.DataFrame(rows).set_index("group")
T.to_pickle(OUT + f"{tag}_table.pkl")

print(f"K={K} draws per placebo; CIs = month-cluster bootstrap (B={B}); p_draw one-sided = P(placebo mean >= actual)")
print(f"{'group':16s} {'n':>4s} {'twinR':>7s} {'simR':>7s} {'95%CI':>17s} {'no-cost':>7s}")
for g, r in T.iterrows():
    print(f"{g:16s} {r.n:4d} {r.twinR:+.3f} {r.act:+.3f} [{r.act_lo:+.3f},{r.act_hi:+.3f}] {r.nocost:+.3f}")
for p, desc in PL:
    print(f"\n--- placebo {p}: {desc}")
    print(f"{'group':16s} {'plac mean':>9s} {'draw 95%':>17s} {'act-plac':>8s} {'clusterCI':>17s} {'p_draw':>7s} {'p_boot':>7s}")
    for g, r in T.iterrows():
        q = r[p + "_q"]
        print(f"{g:16s} {r[p]:+9.3f} [{q[0]:+.3f},{q[1]:+.3f}] {r[p+'_diff']:+8.3f} [{r[p+'_dlo']:+.3f},{r[p+'_dhi']:+.3f}] {r[p+'_pdraw']:7.4f} {r[p+'_pboot']:7.4f}")

print("\n=== DECOMPOSITION (mean R per trade, sim) ===")
print("path 1: geometry+cost (c) | +drift (d-c) | +regime-direction (b-d) | +precise timing (act-b) = act")
print("path 2: geometry+cost (c) | +entry-time w/o direction (a-c) | +direction given time (act-a)")
for g, r in T.iterrows():
    print(f"{g:16s} n={r.n:4d}  c={r.c:+.3f} | drift={r.d-r.c:+.3f} | regime={r.b-r.d:+.3f} | timing={r.act-r.b:+.3f} "
          f"|| a-c={r.a-r.c:+.3f} | dir={r.act-r.a:+.3f} || act={r.act:+.3f}")

# weighted (equity-relevant: CAP clips tight-stop trades)
w = d.w.values
print("\n=== equity-weighted (w=min(3.5%,2.5*stop)/3.5%) pooled ===")
for gname, ix in groups[:3]:
    ww = w[ix]
    f = lambda v: (v * ww).sum() / ww.sum()
    act = f(d.loc[ix, "simR"].values)
    pl = {p: f(M[p][ix].mean(1)) for p, _ in PL}
    print(f"{gname:10s} act={act:+.3f} c={pl['c']:+.3f} d={pl['d']:+.3f} b={pl['b']:+.3f} a={pl['a']:+.3f}")

# funding and cost share
print("\nmean cost in R (nocost - simR):", (d.R_nocost - d.simR).groupby(d.kol).mean().round(3).to_dict(),
      " funding in R (nofund - simR):", (d.R_nofund - d.simR).groupby(d.kol).mean().round(4).to_dict())

print("\n=== component CIs (paired per-trade, month-cluster bootstrap 95%) ===")
E = {p: M[p].mean(1) for p, _ in PL}; E["act"] = d.simR.values
E["a"] = (d.simR.values + d.R_opp.values) / 2   # exact expectation of random-direction placebo
comps = [("drift d-c", "d", "c"), ("regime b-d", "b", "d"), ("timing act-b", "act", "b"), ("late b_fwd-d", "b_fwd", "d"),
         ("late-entry act-b_fwd", "act", "b_fwd"), ("time-no-dir a-c", "a", "c"), ("direction act-a", "act", "a")]
for gname, ix in groups:
    cl = d.loc[ix, "month"].values
    out = []
    for nm, x1, x0 in comps:
        v = E[x1][ix] - E[x0][ix]; lo, hi, p = cluster_boot(v, cl)
        out.append(f"{nm}={v.mean():+.3f}[{lo:+.3f},{hi:+.3f}]p{min(p,1-p)*2:.3f}")
    print(f"{gname:15s} " + "  ".join(out))
