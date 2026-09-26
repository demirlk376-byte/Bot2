import numpy as np, pandas as pd, pickle
from rv_load import cboot, RR
from rv4 import sim, H
d, OH = pickle.load(open("rv4.pkl", "rb"))
rng = np.random.default_rng(2024)
K = 150; W = 45*24
out = {q: [] for q in ["act", "A", "Ap", "Af", "V", "VC", "Cs", "whyA", "whyV", "whyVC", "whyC", "RVC", "RC", "B"]}
for t in d.itertuples():
    x = OH[t.coin]; hi, lo, cl, at = x.high.values, x.low.values, x.close.values, x.atr.values; n = len(cl); k = t.kol; h = H[k]; rr = RR[k]
    def cands(a, b):
        c = np.arange(max(20, a), min(n-h-1, b))
        if k == "mean_rev":
            c = c[np.isin((x.index[c] + pd.Timedelta(hours=1)).dayofweek, [5, 6])]
        return c
    call = cands(t.i0-W, t.i0+W); cp = cands(t.i0-W, t.i0-h); cf = cands(t.i0+1, t.i0+W)
    R0, _ = sim(hi, lo, cl, [t.i0], t.s, t.sp, rr, h); out["act"].append(R0[0])
    RB, _ = sim(hi, lo, cl, [t.i0], -t.s, t.sp, rr, h); out["B"].append(RB[0])
    dr = rng.choice(call, K)
    RA, wA = sim(hi, lo, cl, dr, t.s, t.sp, rr, h); out["A"].append(RA.mean()); out["whyA"].append(wA)
    sides = rng.choice([-1, 1], K)
    RC, wC = sim(hi, lo, cl, dr, sides, t.sp, rr, h); out["Cs"].append(RC.mean()); out["whyC"].append(wC); out["RC"].append(RC)
    out["Ap"].append(sim(hi, lo, cl, rng.choice(cp, K), t.s, t.sp, rr, h)[0].mean() if len(cp) > 10 else np.nan)
    out["Af"].append(sim(hi, lo, cl, rng.choice(cf, K), t.s, t.sp, rr, h)[0].mean() if len(cf) > 10 else np.nan)
    spv = t.ratio_atr * at[dr] / cl[dr]
    RV, wV = sim(hi, lo, cl, dr, t.s, spv, rr, h); out["V"].append(RV.mean()); out["whyV"].append(wV)
    RVC, wVC = sim(hi, lo, cl, dr, sides, spv, rr, h); out["VC"].append(RVC.mean()); out["whyVC"].append(wVC); out["RVC"].append(RVC)
for q in ["act", "A", "Ap", "Af", "V", "VC", "Cs", "B"]: d[q] = out[q]
pickle.dump(out, open("rv5_out.pkl", "wb"))
code = d.exit_reason.map({"sl_hit": 0, "tp_hit": 1, "max_hold": 2}).values
print("gross actual (replay) mean by kol:"); 
for k in ["donchian", "squeeze", "mean_rev", "ALL"]:
    g = d if k == "ALL" else d[d.kol == k]
    s = f"{k:9s} n={len(g)} act {g.act.mean():+.3f} | A {g.A.mean():+.3f} Apast {g.Ap.mean():+.3f} Afut {g.Af.mean():+.3f} | V(volmatch) {g.V.mean():+.3f} | C {g.Cs.mean():+.3f} VC {g.VC.mean():+.3f} | flip {g.B.mean():+.3f}"
    print(s)
    for nm in ["A", "Ap", "Af", "V", "B"]:
        ok = g[nm].notna()
        dd = (g.act - g[nm])[ok]
        m = cboot(dd.values, g.wk[ok].values, seed=11)
        mm = cboot(dd.values, g.mo_in[ok].values, seed=12)
        print(f"      act-{nm:3s} {dd.mean():+.3f} week-CI [{np.percentile(m,2.5):+.3f},{np.percentile(m,97.5):+.3f}] p1={np.mean(m<=0):.4f} | month-CI [{np.percentile(mm,2.5):+.3f},{np.percentile(mm,97.5):+.3f}] p1={np.mean(mm<=0):.4f}")
# exit structure and TP share under nulls
idx = {k: np.where(d.kol.values == k)[0] for k in RR}
for k in RR:
    ii = idx[k]
    for nm in ["whyC", "whyVC", "whyA", "whyV"]:
        w = np.concatenate([out[nm][i] for i in ii])
        res = w < 2
        print(f"{k:9s} {nm:6s} P(sl) {np.mean(w==0):.3f} P(tp) {np.mean(w==1):.3f} P(mh) {np.mean(w==2):.3f} TPshare|res {np.mean(w[res]==1):.3f}")
    ca = code[ii]; print(f"{k:9s} ACTUAL P(sl) {np.mean(ca==0):.3f} P(tp) {np.mean(ca==1):.3f} P(mh) {np.mean(ca==2):.3f} TPshare|res {np.mean(ca[ca<2]==1):.3f} (n_res={np.sum(ca<2)})")
    Rn = np.concatenate([out["RVC"][i] for i in ii]); w = np.concatenate([out["whyVC"][i] for i in ii])
    print(f"          VC mean R|mh {Rn[w==2].mean():+.3f}  contrib SL/TP {Rn[w<2].sum()/len(Rn):+.3f} MH {Rn[w==2].sum()/len(Rn):+.3f}")
