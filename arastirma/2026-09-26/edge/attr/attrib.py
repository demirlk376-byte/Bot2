"""(1) P&L attribution, (2) R-distribution shape, (3) break-even WR, (4) cost drag, (5) concentration.
Null / CI conventions:
  * CI on mean R: cluster bootstrap, clusters = ISO week of entry (trades opened the same week resampled
    together, to respect the simultaneous-trade correlation), 4000 reps, percentile 95%.
  * WR CI: Wilson 95% (iid binomial); binomial one-sided test vs break-even WR.
"""
import sys
import numpy as np
import pandas as pd
from scipy import stats
from load import load

rng = np.random.default_rng(7)
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
path = sys.argv[1] if len(sys.argv) > 1 else "/home/user/Bot2/ikiz_k25_cap25_islemler.csv"
d = load(path)
N = len(d)
TOT_R = d.R_net.sum()
TOT_L = d.logc.sum()
print(f"n={N}  sum R_net={TOT_R:.1f}  mean R_net={d.R_net.mean():+.4f}  "
      f"log growth={TOT_L:.3f} (x{np.exp(TOT_L):.1f})  final equity ${1e4*np.exp(TOT_L):,.0f}")


def cluster_boot_mean(x, cl, reps=4000):
    """95% percentile CI of mean(x) resampling clusters with replacement."""
    x = np.asarray(x, float)
    codes, inv = np.unique(np.asarray(cl), return_inverse=True)
    k = len(codes)
    sums = np.bincount(inv, weights=x, minlength=k)
    cnts = np.bincount(inv, minlength=k).astype(float)
    idx = rng.integers(0, k, size=(reps, k))
    m = sums[idx].sum(1) / cnts[idx].sum(1)
    return np.percentile(m, [2.5, 97.5]), (m <= 0).mean()


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def attrib(by):
    rows = []
    for key, g in d.groupby(by, observed=True):
        ci, p0 = cluster_boot_mean(g.R_net, g.week) if len(g) >= 8 else ((np.nan, np.nan), np.nan)
        rows.append(dict(grp=key, n=len(g), WR=g.win.mean(), meanR=g.R_net.mean(),
                         lo=ci[0], hi=ci[1], p_le0=p0, sumR=g.R_net.sum(),
                         shR=g.R_net.sum() / TOT_R, sumLog=g.logc.sum(), shLog=g.logc.sum() / TOT_L))
    t = pd.DataFrame(rows).set_index("grp")
    return t


fmt = {"WR": "{:.3f}", "meanR": "{:+.3f}", "lo": "{:+.3f}", "hi": "{:+.3f}", "p_le0": "{:.3f}",
       "sumR": "{:+.1f}", "shR": "{:+.1%}", "sumLog": "{:+.3f}", "shLog": "{:+.1%}"}


def show(t, title):
    print(f"\n=== {title} ===")
    print(t.to_string(formatters={k: v.format for k, v in fmt.items()}))


d["hold_b"] = pd.cut(d.hold_h, [0, 6, 24, 48.5, 200], labels=["<=6h", "6-24h", "24-48h", ">48h"])
d["kol_side"] = d.kol + "_" + d.side
for by, title in [("kol", "SLEEVE"), ("side", "SIDE"), ("kol_side", "SLEEVE x SIDE"),
                  ("exit_reason", "EXIT REASON"), (["kol", "exit_reason"], "SLEEVE x EXIT"),
                  ("hold_b", "HOLD BUCKET"), ("coin", "COIN"), ("year", "YEAR (exit)"),
                  ("split", "TRAIN/TEST"), (["split", "kol"], "SPLIT x SLEEVE")]:
    show(attrib(by), title)

# ---------------- (2) shape ----------------
print("\n=== (2) R_net DISTRIBUTION SHAPE ===")


def shape(g, label):
    r = g.R_net.values
    w, l = r[r > 0], r[r <= 0]
    srt = np.sort(r)[::-1]
    tot = r.sum()
    out = dict(sl=label, n=len(r), WR=len(w) / len(r), mWin=w.mean(), mLoss=l.mean(),
               payoff=w.mean() / -l.mean(), skew=stats.skew(r), sum=tot)
    for q in (0.05, 0.10, 0.20):
        k = int(round(q * len(r)))
        out[f"top{int(q*100)}%sh"] = srt[:k].sum() / tot
    k10 = int(round(0.10 * len(r)))
    out["sum_wo_top10"] = srt[k10:].sum()
    # same in equity-return terms (log contributions)
    lc = np.sort(g.logc.values)[::-1]
    out["top10%sh_log"] = lc[:k10].sum() / lc.sum()
    out["log_wo_top10"] = lc[k10:].sum()
    return out


rows = [shape(d, "ALL")] + [shape(g, k) for k, g in d.groupby("kol")]
print(pd.DataFrame(rows).set_index("sl").round(3).to_string())
print("\nR_net quantiles:", np.round(np.percentile(d.R_net, [0, 5, 25, 50, 75, 90, 95, 99, 100]), 3))
print("share of trades with |R_net - (-1)|<0.02:", ((d.R_net + 1).abs() < 0.02).mean().round(3),
      "; TP-level (>=1.6):", (d.R_net >= 1.6).mean().round(3))
mh = d[d.exit_reason == "max_hold"]
print(f"max_hold trades: n={len(mh)} mean R_net={mh.R_net.mean():+.3f} WR={mh.win.mean():.3f} "
      f"sumR={mh.R_net.sum():+.1f} range [{mh.R_net.min():+.2f},{mh.R_net.max():+.2f}]")

# ---------------- (3) break-even ----------------
print("\n=== (3) BREAK-EVEN WR vs ACTUAL (empirical payoff)  +  martingale null on SL/TP-resolved trades ===")
RR = {"donchian": 2.5, "squeeze": 2.5, "mean_rev": 1.667}
rows = []
for k, g in list(d.groupby("kol")) + [("ALL", d)]:
    r = g.R_net.values
    w, l = r[r > 0], r[r <= 0]
    b = w.mean() / -l.mean()
    pbe = 1 / (1 + b)
    kw, n = len(w), len(r)
    lo, hi = wilson(kw, n)
    pb = stats.binomtest(kw, n, pbe, alternative="greater").pvalue
    # cluster bootstrap of margin WR - p_be (p_be re-estimated each rep)
    codes, inv = np.unique(g.week.values, return_inverse=True)
    reps = []
    for _ in range(3000):
        sel = rng.integers(0, len(codes), len(codes))
        m = np.isin(inv, sel)  # approx: set membership (ignores duplicate weight) -> use weights
        wts = np.bincount(sel, minlength=len(codes))[inv]
        rr = np.repeat(r, wts)
        ww, ll = rr[rr > 0], rr[rr <= 0]
        reps.append((len(ww) / len(rr)) - 1 / (1 + ww.mean() / -ll.mean()))
    mlo, mhi = np.percentile(reps, [2.5, 97.5])
    # martingale null: for SL/TP resolved trades, P(TP first) = 1/(1+RR) for a driftless continuous price
    if k != "ALL":
        st = g[g.exit_reason.isin(["sl_hit", "tp_hit"])]
        ktp, nst = (st.exit_reason == "tp_hit").sum(), len(st)
        p0 = 1 / (1 + RR[k])
        pm = stats.binomtest(ktp, nst, p0, alternative="greater").pvalue
        tl, th = wilson(ktp, nst)
        mart = f"TP|SL/TP {ktp}/{nst}={ktp/nst:.3f} [{tl:.3f},{th:.3f}] vs 1/(1+RR)={p0:.3f} p={pm:.2g}"
    else:
        mart = ""
    rows.append(f"{k:9s} n={n:4d} WR={kw/n:.3f} [{lo:.3f},{hi:.3f}] payoff={b:.2f} "
                f"BE-WR={pbe:.3f} margin={kw/n-pbe:+.3f} [{mlo:+.3f},{mhi:+.3f}] binom p={pb:.2g} | {mart}")
print("\n".join(rows))

# ---------------- (4) cost drag ----------------
print("\n=== (4) COST DRAG (mean per trade, R units; risk unit = qty*|intended_entry-sl0|) ===")
cols = ["R_gross", "c_slip_in", "c_slip_out", "c_fee", "c_fund", "R_net"]
cd = d.groupby("kol")[cols].mean()
cd.loc["ALL"] = d[cols].mean()
cd["cost_total"] = cd.R_net - cd.R_gross
cd["cost_share_of_gross"] = -cd.cost_total / cd.R_gross
cd["stop_pct_med"] = list(d.groupby("kol").stop_pct.median()) + [d.stop_pct.median()]
print(cd.round(4).to_string())
for k, g in list(d.groupby("kol")) + [("ALL", d)]:
    ci, _ = cluster_boot_mean(g.R_gross, g.week)
    print(f"  {k:9s} gross mean {g.R_gross.mean():+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}]")

# ---------------- (5) concentration ----------------
print("\n=== (5) CONCENTRATION ===")


def conc(key, lab):
    s = d.groupby(key, observed=True).R_net.sum().sort_values(ascending=False)
    L = d.groupby(key, observed=True).logc.sum().sort_values(ascending=False)
    pos = s[s > 0]
    hhi = ((pos / pos.sum()) ** 2).sum()
    print(f"{lab}: groups={len(s)} positive={len(pos)} ({len(pos)/len(s):.0%})  "
          f"HHI(positive-share)={hhi:.3f} -> effective N={1/hhi:.1f}")
    for k in (1, 3, 5):
        print(f"   top-{k} share of net sumR: {s.iloc[:k].sum()/s.sum():.1%}   of log-growth: {L.iloc[:k].sum()/L.sum():.1%}"
              f"   | remove top-{k}: sumR {s.iloc[k:].sum():+.1f}, log {L.iloc[k:].sum():+.3f}")
    return s


sc = conc("coin", "COINS")
print("   coin sumR:", sc.round(1).to_dict())
sm = conc("month", "MONTHS")
# null for month concentration: permute R_net across trades (keeps each month's trade count);
# statistic = top-5 month share of total and fraction of positive months
mcodes, minv = np.unique(d.month.astype(str).values, return_inverse=True)
obs_top5 = np.sort(np.bincount(minv, weights=d.R_net.values))[::-1][:5].sum() / TOT_R
obs_pos = (np.bincount(minv, weights=d.R_net.values) > 0).mean()
obs_sd = np.bincount(minv, weights=d.R_net.values).std()
nt, npos, nsd = [], [], []
r = d.R_net.values
for _ in range(5000):
    ms = np.bincount(minv, weights=rng.permutation(r))
    nt.append(np.sort(ms)[::-1][:5].sum() / TOT_R); npos.append((ms > 0).mean()); nsd.append(ms.std())
nt, npos, nsd = map(np.array, (nt, npos, nsd))
print(f"   months: top-5 share obs {obs_top5:.1%} vs perm-null median {np.median(nt):.1%} "
      f"(p(null>=obs)={(nt>=obs_top5).mean():.3f}); positive months obs {obs_pos:.1%} vs null median "
      f"{np.median(npos):.1%} (p(null<=obs)={(npos<=obs_pos).mean():.3f}); SD of monthly sumR obs {obs_sd:.2f} "
      f"vs null {np.median(nsd):.2f} (p(null>=obs)={(nsd>=obs_sd).mean():.3f})")
# coin heterogeneity within sleeve: permutation of coin labels within sleeve, stat = between-coin
# weighted variance of mean R (ANOVA-like)
for k, g in d.groupby("kol"):
    if g.coin.nunique() < 2:
        continue
    lab = g.coin.values; rr = g.R_net.values
    u, inv = np.unique(lab, return_inverse=True)
    cnt = np.bincount(inv)

    def stat(x):
        m = np.bincount(inv, weights=x) / cnt
        return (cnt * (m - x.mean()) ** 2).sum()
    o = stat(rr)
    nul = np.array([stat(rng.permutation(rr)) for _ in range(5000)])
    means = dict(zip(u, np.round(np.bincount(inv, weights=rr) / cnt, 3)))
    print(f"   coin heterogeneity within {k}: perm p={(nul>=o).mean():.3f}  mean R by coin {means}  n {dict(zip(u,cnt))}")
