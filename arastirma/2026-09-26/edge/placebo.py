"""Placebo tests: does the entry signal carry information beyond payoff geometry + drift?
usage: python3 placebo.py <trades.csv> <tag> [K]
Writes <tag>_draws.npz (per-trade x draw R matrices) and <tag>_trades.pkl.
"""
import sys, time
sys.path.insert(0, "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge")
import numpy as np, pandas as pd
from sim import *

OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/"
path, tag = sys.argv[1], sys.argv[2]
K = int(sys.argv[3]) if len(sys.argv) > 3 else 500
rng = np.random.default_rng(20260926)
SPLIT_TS = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())

d = load_trades(path).reset_index(drop=True)
coins = {c: Coin(c) for c in d.coin.unique()}
N = len(d)
M = {k: np.full((N, K), np.nan) for k in ("a", "b", "b_wk", "b_vol", "b_fwd", "b_bwd", "c", "c_vol", "d")}
d["simR"] = np.nan; d["R_opp"] = np.nan; d["R_nocost"] = np.nan

t0 = time.time()
for (c, kol), g in d.groupby(["coin", "kol"]):
    cn = coins[c]; G = GEOM[kol]; MH = G["MH"]
    G0 = dict(G, slip=0.0, fee_in=0.0)
    ix = g.index.values; n = len(ix)
    t = g.et.values.astype("datetime64[s]").astype(np.int64)
    i0 = cn.idx(t); assert (cn.ts[i0] == t).all()
    dirn = g.dirn.values.astype(float); P = g.ie.values; D = g.D.values; sp = g.stop_pct.values
    volmult = D / cn.atr_open[i0]
    R, _, _ = simulate(cn, i0, dirn, P, D, G); d.loc[ix, "simR"] = R
    Ro, _, _ = simulate(cn, i0, -dirn, P, D, G); d.loc[ix, "R_opp"] = Ro
    # cost-free geometry for the actual trade (no slippage/fees; funding still in -> remove below)
    fund_saved = (cn.F_open, cn.F_close)
    cn.F_open = np.zeros(cn.n); cn.F_close = np.zeros(cn.n)
    Rnc, _, _ = simulate(cn, i0, dirn, P, D, dict(G0))
    d.loc[ix, "R_nocost"] = Rnc
    Rnf, _, _ = simulate(cn, i0, dirn, P, D, G)
    d.loc[ix, "R_nofund"] = Rnf
    cn.F_open, cn.F_close = fund_saved

    # (a) same time, random direction
    s = rng.choice([-1.0, 1.0], size=(n, K))
    M["a"][ix] = np.where(s == dirn[:, None], R[:, None], Ro[:, None])

    lo_ok, hi_ok = 30, cn.n - MH - 1

    def run(inew, dnew, Dmode):
        inew = inew.ravel(); dnew = dnew.ravel()
        Pn = cn.o[inew]
        if Dmode == "pct":
            Dn = np.repeat(sp, K) * Pn
        else:
            Dn = np.repeat(volmult, K) * cn.atr_open[inew]
        r, _, _ = simulate(cn, inew, dnew, Pn, Dn, G)
        return r.reshape(n, K)

    dirK = np.repeat(dirn[:, None], K, 1)
    # (b) same direction, shift uniform in [-720,720]h excluding |s|<24h (avoid overlapping the real trade)
    sh = rng.integers(24, 721, size=(n, K)) * rng.choice([-1, 1], size=(n, K))
    ib = i0[:, None] + sh
    bad = (ib < lo_ok) | (ib > hi_ok); ib[bad] = (i0[:, None] - sh)[bad]
    ib = np.clip(ib, lo_ok, hi_ok)
    M["b"][ix] = run(ib, dirK, "pct")
    M["b_vol"][ix] = run(ib, dirK, "vol")
    # (b_fwd / b_bwd) same direction, shift only LATER (+24..+720h: uses only info known at t -> "late entry")
    # or only EARLIER (-720..-24h: placebo knows the future direction -> hindsight-inflated)
    for key, sgn in (("b_fwd", 1), ("b_bwd", -1)):
        shf = rng.integers(24, 721, size=(n, K)) * sgn
        iff = np.clip(i0[:, None] + shf, lo_ok, hi_ok)
        M[key][ix] = run(iff, dirK, "pct")
    # (b_wk) same direction, shift by whole weeks +-1..4 (keeps hour-of-week, e.g. weekend-only mean_rev)
    wk = rng.integers(1, 5, size=(n, K)) * 168 * rng.choice([-1, 1], size=(n, K))
    ibw = i0[:, None] + wk
    bad = (ibw < lo_ok) | (ibw > hi_ok); ibw[bad] = (i0[:, None] - wk)[bad]
    M["b_wk"][ix] = run(np.clip(ibw, lo_ok, hi_ok), dirK, "pct")
    # random time within the trade's split period on the same coin
    isplit = cn.idx(SPLIT_TS)
    tr = g.split.values == "TRAIN"
    lo = np.where(tr, lo_ok, isplit); hi = np.where(tr, isplit - MH, hi_ok)
    ir = (lo[:, None] + rng.random((n, K)) * (hi - lo)[:, None]).astype(int)
    rdir = rng.choice([-1.0, 1.0], size=(n, K))
    M["c"][ix] = run(ir, rdir, "pct")          # (c) random time + random direction
    M["c_vol"][ix] = run(ir, rdir, "vol")
    M["d"][ix] = run(ir, dirK, "pct")          # (d) random time, SAME direction -> drift
    print(f"  {c:5s} {kol:9s} n={n:4d}  {time.time()-t0:6.1f}s", flush=True)

np.savez_compressed(OUT + f"{tag}_draws.npz", **M)
d.to_pickle(OUT + f"{tag}_trades.pkl")
print("done", time.time() - t0)
