"""Part 2: is the filter's portfolio-level pass (lower DD / higher MAR) better
than RANDOM THINNING of the donchian stream?  Book = filtered run's squeeze +
mean_rev trades (fixed) + a donchian stream.  Per-trade equity return =
Rnet * min(0.035, 2.5*stop_pct) (live risk/CAP for every variant), applied at
exit time, compounded.  Realized (exit-order) drawdown."""
import numpy as np, pandas as pd
import importlib.util, sys

OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge"
ROOT = "/home/user/Bot2"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
RNG = np.random.default_rng(7)

do = pd.read_csv(f"{OUT}/unfiltered_donchian_with_vr.csv", parse_dates=["et", "xt"])
dn = pd.read_csv(f"{OUT}/filtered_donchian_with_vr.csv", parse_dates=["et", "xt"])

# non-donchian legs of the live run
spec = importlib.util.spec_from_file_location("a", f"{OUT}/volfilter_audit.py")
import json
def load(fn):
    d = pd.read_csv(f"{ROOT}/{fn}")
    s = d.strategy_scores.apply(json.loads)
    d["ie"] = s.apply(lambda x: x["intended_entry"]); d["sl0"] = s.apply(lambda x: x["sl0"])
    d["xt"] = pd.to_datetime(d.exit_time, utc=True)
    rp = (d.ie - d.sl0).abs(); d["stop_pct"] = rp / d.ie
    d["Rnet"] = d.pnl_usdt / (d.quantity * rp)
    return d
live = load("ikiz_k25_cap25_islemler.csv")

# --- sanity: does Rnet*min(.035, 2.5*stop) reproduce pnl/equity_before? -----
lv = live.sort_values(["xt", "entry_time"]).reset_index(drop=True)
eq = 10000 + lv.pnl_usdt.cumsum().shift(1).fillna(0)
act = lv.pnl_usdt / eq
apx = lv.Rnet * np.minimum(0.035, 2.5 * lv.stop_pct)
print(f"approx check: corr={np.corrcoef(act, apx)[0,1]:.4f}  median|diff|={np.median(np.abs(act-apx))*1e4:.1f}bp  "
      f"actual final eq={10000+lv.pnl_usdt.sum():,.0f}  approx final eq={10000*np.prod(1+apx):,.0f}")

live["et"] = pd.to_datetime(live.entry_time, utc=True)
other = live[live.kol != "donchian"][["et", "xt", "Rnet", "stop_pct"]]

def _sim(g, risk=0.035, cap=2.5, E0=10000.0):
    """entry-sized event sim: size = E(realized, at entry)*min(risk, cap*stop);
    pnl booked at exit.  Returns realized equity path at exits."""
    et = g.et.values.astype("datetime64[ns]").astype("int64"); xt = g.xt.values.astype("datetime64[ns]").astype("int64")
    n = len(g); order = np.lexsort((np.r_[np.ones(n), np.zeros(n)], np.r_[et, xt]))
    R = g.Rnet.values; f = np.minimum(risk, cap * g.stop_pct.values)
    E = E0; size = np.zeros(n); path = []
    for k in order:
        if k < n: size[k] = E * f[k]
        else:
            i = k - n; E += R[i] * size[i]; path.append(E)
    return np.array(path)

def book_metrics(don):
    b = pd.concat([other, don[["et", "xt", "Rnet", "stop_pct"]]])
    out = {}
    for h, g in (("TRAIN", b[b.xt < SPLIT]), ("TEST", b[b.xt >= SPLIT])):
        p = _sim(g)
        le = np.log(np.r_[10000.0, p] / 10000.0)
        dd = 1 - np.exp(np.min(le - np.maximum.accumulate(le)))
        yrs = (g.xt.max() - g.xt.min()).days / 365.25
        cagr = np.exp(le[-1] / yrs) - 1
        out[h] = dict(logret=le[-1], maxDD=dd, CAGR=cagr, MAR=cagr / dd)
    return out

rows = []
for lab, d in [("unfiltered donchian", do), ("filtered run donchian (live)", dn),
               ("unfiltered minus removed (no re-occupancy)", do[do.vr >= 2.5])]:
    m = book_metrics(d)
    for h in m: rows.append(dict(variant=lab, half=h, **m[h]))
R = pd.DataFrame(rows)
print(R.round(3).to_string(index=False))

# --- random-thinning null: keep a random subset of the unfiltered donchian of
# the same size per half as the vr>=2.5 set (179 TRAIN / 127 TEST) -----------
kt = do[do.vr >= 2.5]
nk = {h: (kt.half == h).sum() for h in ("TRAIN", "TEST")}
act = book_metrics(kt)
sims = {h: [] for h in nk}
NS = 2000
for _ in range(NS):
    parts = [do[do.half == h].sample(nk[h], random_state=int(RNG.integers(1 << 31))) for h in nk]
    m = book_metrics(pd.concat(parts))
    for h in nk: sims[h].append(m[h])
print("\n=== filter vs random thinning (same n per half), null = filter keeps a random subset ===")
for h in nk:
    s = pd.DataFrame(sims[h])
    a = act[h]
    print(f"{h}: filter logret={a['logret']:.3f} (null median {s.logret.median():.3f}, "
          f"P(null>=filter)={(s.logret >= a['logret']).mean():.3f}) | "
          f"maxDD={a['maxDD']:.3f} (null median {s.maxDD.median():.3f}, P(null<=filter)={(s.maxDD <= a['maxDD']).mean():.3f}) | "
          f"MAR={a['MAR']:.2f} (null median {s.MAR.median():.2f}, P(null>=filter)={(s.MAR >= a['MAR']).mean():.3f})")
    full = [r for r in rows if r['variant'] == 'unfiltered donchian' and r['half'] == h][0]
    print(f"      unfiltered book: logret={full['logret']:.3f} maxDD={full['maxDD']:.3f} MAR={full['MAR']:.2f}; "
          f"P(random thinning MAR >= unfiltered MAR)={(s.MAR >= full['MAR']).mean():.3f}; "
          f"P(random thinning maxDD < unfiltered maxDD)={(s.maxDD < full['maxDD']).mean():.3f}")
