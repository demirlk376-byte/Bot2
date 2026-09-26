"""What kind of edge? Bar-level re-simulation of each trade's exact bracket geometry on 1h OHLCV.

Simulator (mirrors exchange.check_sl_tp): entry at close of the signal bar (= intended_entry),
bars i0+1..i0+H checked; SL checked before TP inside a bar; else exit at close of bar i0+H.
All R here are GROSS (pre-cost) in units of the trade's own stop distance.

Nulls
 A  timing placebo : same coin, same side, same stop %, same RR, same H, entry at a random bar
                     within +-45 days of the real entry (mean_rev: weekend entries only). K draws/trade.
 B  direction flip : same coin, same entry bar, same geometry, opposite side.
 C  pure null      : random bar (+-45d) and random side.
Under a driftless martingale E[gross R]=0 for A, B, C; A retains local drift of the chosen side.
"""
import numpy as np
import pandas as pd
from load import load

rng = np.random.default_rng(11)
d = load()
RR = {"donchian": 2.5, "squeeze": 2.5, "mean_rev": 1.667}
H = {"donchian": 120, "squeeze": 48, "mean_rev": 48}
OH = {}
for c in d.coin.unique():
    x = pd.read_csv(f"/home/user/Bot2/data/{c}_fut_1h.csv")
    x["ts"] = pd.to_datetime(x.ts, utc=True)
    x = x.set_index("ts").sort_index()
    OH[c] = x[~x.index.duplicated()]


def sim(hi, lo, cl, i0, side, sp, rr, h):
    """vectorised over entry bars i0. returns gross R and reason code (0 sl, 1 tp, 2 max_hold)."""
    n = len(cl)
    i0 = np.asarray(i0)
    side = np.broadcast_to(np.asarray(side), i0.shape)
    e = cl[i0]; stop = sp * e
    sl = e - side * stop; tp = e + side * rr * stop
    idx = np.minimum(i0[:, None] + np.arange(1, h + 1)[None, :], n - 1)
    Hh, Ll = hi[idx], lo[idx]
    s2 = side[:, None]
    slhit = np.where(s2 > 0, Ll <= sl[:, None], Hh >= sl[:, None])
    tphit = np.where(s2 > 0, Hh >= tp[:, None], Ll <= tp[:, None])
    big = h + 5
    fs = np.where(slhit.any(1), slhit.argmax(1), big)
    ft = np.where(tphit.any(1), tphit.argmax(1), big)
    reason = np.where((fs <= ft) & (fs < big), 0, np.where(ft < big, 1, 2))
    last = np.minimum(i0 + h, n - 1)
    R = np.where(reason == 0, -1.0, np.where(reason == 1, rr, side * (cl[last] - e) / stop))
    return R, reason


d["i0"] = [OH[t.coin].index.get_indexer([t.t_in - pd.Timedelta(hours=1)])[0] for t in d.itertuples()]
print("unmatched entry bars:", (d.i0 < 0).sum(),
      "| max |entry-bar close / intended_entry - 1| bp:",
      round(max(abs(OH[c].close.values[i] / ie - 1) * 1e4 for c, i, ie in zip(d.coin, d.i0, d.ie)), 3))

K, WIN = 200, 45 * 24
fwdH = [1, 4, 12, 24, 48, 120]
res = {k: {q: [] for q in ("act", "rs_act", "A", "B", "C", "rsC", "wk", "fa", "fA")} for k in RR}
code = d.exit_reason.map({"sl_hit": 0, "tp_hit": 1, "max_hold": 2})
agree = []
for (c, k), g in d.groupby(["coin", "kol"]):
    x = OH[c]; hi, lo, cl = x.high.values, x.low.values, x.close.values; n = len(cl)
    for j, t in zip(g.index, g.itertuples()):
        sp = t.stop / cl[t.i0]
        Ract, rsa = sim(hi, lo, cl, np.array([t.i0]), t.sg, sp, RR[k], H[k])
        agree.append((rsa[0] == code[j], Ract[0], t.R_gross))
        cand = np.arange(max(0, t.i0 - WIN), min(n - H[k] - 2, t.i0 + WIN))
        if k == "mean_rev":
            cand = cand[np.isin((x.index[cand] + pd.Timedelta(hours=1)).dayofweek, [5, 6])]
        dr = rng.choice(cand, K)
        RA, _ = sim(hi, lo, cl, dr, t.sg, sp, RR[k], H[k])
        RB, _ = sim(hi, lo, cl, np.array([t.i0]), -t.sg, sp, RR[k], H[k])
        RC, rsC = sim(hi, lo, cl, dr, rng.choice([-1, 1], K), sp, RR[k], H[k])
        r = res[k]
        r["act"].append(Ract[0]); r["rs_act"].append(rsa[0]); r["A"].append(RA); r["B"].append(RB[0])
        r["C"].append(RC); r["rsC"].append(rsC); r["wk"].append(str(t.week))
        r["fa"].append([t.sg * (cl[min(t.i0 + h, n - 1)] - cl[t.i0]) / (sp * cl[t.i0]) for h in fwdH])
        r["fA"].append([np.mean(t.sg * (cl[np.minimum(dr + h, n - 1)] - cl[dr]) / (sp * cl[dr])) for h in fwdH])
ag = np.array(agree, dtype=float)
print(f"replay validation: exit-reason agreement {ag[:,0].mean():.3f}, mean gross R replay {ag[:,1].mean():+.4f} vs twin {ag[:,2].mean():+.4f}")


def cboot(x, cl, reps=4000):
    u, inv = np.unique(cl, return_inverse=True)
    sm = np.bincount(inv, weights=x); ct = np.bincount(inv).astype(float)
    ii = rng.integers(0, len(u), (reps, len(u))); m = sm[ii].sum(1) / ct[ii].sum(1)
    return np.percentile(m, [2.5, 97.5]), (m <= 0).mean()


print("\n=== PLACEBO (gross R) ===")
cat = lambda q: np.concatenate([np.atleast_1d(np.array(res[k][q])) if np.ndim(res[k][q][0]) == 0 else np.vstack(res[k][q]) for k in RR])
for k in list(RR) + ["ALL"]:
    if k == "ALL":
        act = np.concatenate([np.array(res[q]["act"]) for q in RR]); A = np.vstack([np.vstack(res[q]["A"]) for q in RR])
        B = np.concatenate([np.array(res[q]["B"]) for q in RR]); C = np.vstack([np.vstack(res[q]["C"]) for q in RR])
        wk = np.concatenate([res[q]["wk"] for q in RR])
    else:
        act = np.array(res[k]["act"]); A = np.vstack(res[k]["A"]); B = np.array(res[k]["B"]); C = np.vstack(res[k]["C"]); wk = np.array(res[k]["wk"])
    bookA, bookC = A.mean(0), C.mean(0)
    ciA, pA = cboot(act - A.mean(1), wk); ciB, pB = cboot(act - B, wk)
    print(f"{k:9s} n={len(act):4d} actual {act.mean():+.3f} | A same-side random-time {bookA.mean():+.3f} "
          f"(book 95% {np.percentile(bookA,2.5):+.3f}..{np.percentile(bookA,97.5):+.3f}) | "
          f"C random side+time {bookC.mean():+.3f} (95% {np.percentile(bookC,2.5):+.3f}..{np.percentile(bookC,97.5):+.3f}) | B flipped {B.mean():+.3f}")
    print(f"          excess act-A {np.mean(act-A.mean(1)):+.3f} [{ciA[0]:+.3f},{ciA[1]:+.3f}] p={pA:.4f} (week-cluster boot) | "
          f"act-flipped {np.mean(act-B):+.3f} [{ciB[0]:+.3f},{ciB[1]:+.3f}] p={pB:.4f} | A-C (side/regime alignment) {bookA.mean()-bookC.mean():+.3f}")

print("\n=== EXIT STRUCTURE: actual vs null C (bucket means are not 0 under the null) ===")
for k in RR:
    for lab, R, rs in (("NULL-C", np.concatenate(res[k]["C"]), np.concatenate(res[k]["rsC"])),
                       ("ACTUAL", np.array(res[k]["act"]), np.array(res[k]["rs_act"]))):
        rv = rs < 2
        print(f"{k:9s} {lab}: P(sl) {np.mean(rs==0):.3f} P(tp) {np.mean(rs==1):.3f} P(mh) {np.mean(rs==2):.3f} | "
              f"TP share of SL/TP-resolved {np.mean(rs[rv]==1):.3f} | mean R|mh {R[rs==2].mean():+.3f} | "
              f"per-trade contrib SL/TP {R[rv].sum()/len(R):+.3f}, MH {R[rs==2].sum()/len(R):+.3f}, total {R.mean():+.3f}")

print("\n=== SIGNED FORWARD DRIFT after entry (close-to-close, R units, no bracket); act ±1.96se / placebo A ===")
for k in RR:
    fa = np.array(res[k]["fa"]); fA = np.array(res[k]["fA"]); se = fa.std(0, ddof=1) / np.sqrt(len(fa))
    print(f"{k:9s} " + "  ".join(f"h{h}: {m:+.3f}±{1.96*s:.3f}/{p:+.3f}" for h, m, s, p in zip(fwdH, fa.mean(0), se, fA.mean(0))))
