"""Audit of the live donchian volume filter (DONCHIAN_VOL_MULT 2.5).

Research only. Reads the two twin trade lists, reconstructs each donchian
entry's breakout-bar volume ratio from data/{COIN}_fut_1h.csv exactly the way
the twin does (fast_bt.resample(1h->4h, pandas default origin), breakout bar =
the 4h bar whose close == entry_time, ratio = v[bar] / mean(v[20 bars before])),
and compares R_net of removed vs kept trades.
"""
import json, sys
import numpy as np, pandas as pd
from scipy import stats

ROOT = "/home/user/Bot2"
OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
RNG = np.random.default_rng(12345)
NB = 20000   # bootstrap / permutation reps


def load(fn):
    d = pd.read_csv(f"{ROOT}/{fn}")
    s = d.strategy_scores.apply(json.loads)
    d["ie"] = s.apply(lambda x: x["intended_entry"])
    d["sl0"] = s.apply(lambda x: x["sl0"])
    d["et"] = pd.to_datetime(d.entry_time, utc=True)
    d["xt"] = pd.to_datetime(d.exit_time, utc=True)
    sg = np.where(d.side == "long", 1.0, -1.0)
    rp = (d.ie - d.sl0).abs()
    d["stop_pct"] = rp / d.ie
    d["Rnet"] = d.pnl_usdt / (d.quantity * rp)
    d["slipR"] = sg * (d.entry_price - d.ie) / rp            # entry slippage cost, R
    d["Rgross"] = sg * (d.exit_price - d.ie) / rp             # before entry slip/fees/funding
    d["feefundR"] = d.Rgross - d.slipR - d.Rnet
    d["half"] = np.where(d.xt < SPLIT, "TRAIN", "TEST")
    d["coin"] = d.symbol.str.split("/").str[0]
    d["key"] = d.symbol + "|" + d.side + "|" + d.entry_time
    return d


new = load("ikiz_k25_cap25_islemler.csv")
old = load("ikiz_k25_eski_islemler.csv")

# ---------------- volume ratio reconstruction --------------------------------
_v4 = {}
def v4(coin):
    if coin not in _v4:
        m = pd.read_csv(f"{ROOT}/data/{coin}_fut_1h.csv", index_col=0, parse_dates=True)
        r = m.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()
        _v4[coin] = r["volume"]
    return _v4[coin]

def vratio(row):
    v = v4(row.coin)
    bar_open = row.et - pd.Timedelta(hours=4)
    if bar_open not in v.index:
        return np.nan
    i = v.index.get_loc(bar_open)
    if i < 20:
        return np.nan
    return float(v.iloc[i] / v.iloc[i - 20:i].mean())

for d in (new, old):
    dm = d.kol == "donchian"
    d.loc[dm, "vr"] = d[dm].apply(vratio, axis=1)

dn = new[new.kol == "donchian"].copy()
do = old[old.kol == "donchian"].copy()

print("=== reconstruction check ===")
print(f"filtered run donchian n={len(dn)}; vr>=2.5: {(dn.vr >= 2.5).sum()}  "
      f"vr<2.5: {(dn.vr < 2.5).sum()}  nan: {dn.vr.isna().sum()}  min vr={dn.vr.min():.3f}")
print(f"unfiltered run donchian n={len(do)}; vr>=2.5: {(do.vr >= 2.5).sum()}  "
      f"vr<2.5: {(do.vr < 2.5).sum()}  nan: {do.vr.isna().sum()}")

# ---------------- matching --------------------------------------------------
kn, ko = set(dn.key), set(do.key)
both = kn & ko
do["in_new"] = do.key.isin(kn)
dn["in_old"] = dn.key.isin(ko)
m = do[do.in_new].merge(dn[dn.in_old][["key", "Rnet", "exit_time", "exit_reason"]],
                        on="key", suffixes=("", "_n"))
print("\n=== matching ===")
print(f"common={len(both)}  old-only={len(ko - kn)}  new-only={len(kn - ko)}")
print(f"matched trades with identical exit_time: {(m.exit_time == m.exit_time_n).mean():.3f}; "
      f"max |Rnet diff| = {(m.Rnet - m.Rnet_n).abs().max():.4f}")

do["grp"] = np.select(
    [do.vr < 2.5, do.in_new],
    ["REMOVED(vr<2.5)", "KEPT(common)"],
    "DISPLACED(vr>=2.5, not in filtered run)")
dn["grp"] = np.where(dn.in_old, "KEPT(common)", "NEW-ONLY(filtered run)")
print(pd.crosstab(do.grp, do.half, margins=True))
print(pd.crosstab(dn.grp, dn.half, margins=True))
# removed trades that the filtered run nonetheless has? (should be 0)
print("old vr<2.5 but present in new run:", int(((do.vr < 2.5) & do.in_new).sum()))


# ---------------- stats helpers ---------------------------------------------
def boot_ci(x, f=np.mean, nb=NB):
    x = np.asarray(x)
    idx = RNG.integers(0, len(x), (nb, len(x)))
    b = f(x[idx], axis=1) if f in (np.mean,) else np.array([f(x[i]) for i in idx])
    return np.percentile(b, [2.5, 97.5])

def wilson(k, n, z=1.96):
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h

def summ(x, label):
    x = np.asarray(x); n = len(x)
    lo, hi = boot_ci(x)
    k = (x > 0).sum(); wl, wh = wilson(k, n)
    t = stats.ttest_1samp(x, 0.0)
    return dict(group=label, n=n, meanR=x.mean(), ci_lo=lo, ci_hi=hi,
                p_mean_le0=t.pvalue / 2 if t.statistic > 0 else 1 - t.pvalue / 2,
                p_mean_ge0=t.pvalue / 2 if t.statistic < 0 else 1 - t.pvalue / 2,
                WR=k / n, WR_lo=wl, WR_hi=wh, sumR=x.sum())

def perm_diff(a, b, nb=NB):
    """one-sided H1: mean(a) < mean(b); null: labels exchangeable."""
    a = np.asarray(a); b = np.asarray(b); x = np.concatenate([a, b]); na = len(a)
    obs = a.mean() - b.mean()
    cnt = 0
    for _ in range(nb):
        p = RNG.permutation(x)
        cnt += (p[:na].mean() - p[na:].mean()) <= obs
    return obs, (cnt + 1) / (nb + 1)

def cluster_boot_diff(da, db, col="Rnet", nb=5000):
    """95% CI of mean(a)-mean(b) resampling ISO-weeks of entry (keeps
    simultaneous/correlated entries together)."""
    wa = da.et.dt.strftime("%G-%V"); wb = db.et.dt.strftime("%G-%V")
    weeks = np.array(sorted(set(wa) | set(wb)))
    ga = {w: da[col].values[(wa == w).values] for w in weeks}
    gb = {w: db[col].values[(wb == w).values] for w in weeks}
    out = []
    for _ in range(nb):
        s = RNG.choice(weeks, len(weeks), replace=True)
        xa = np.concatenate([ga[w] for w in s]); xb = np.concatenate([gb[w] for w in s])
        if len(xa) and len(xb):
            out.append(xa.mean() - xb.mean())
    return np.percentile(out, [2.5, 97.5]), np.mean(np.array(out) >= 0)


rows = []
tests = []
for h in ["TRAIN", "TEST", "ALL"]:
    so = do if h == "ALL" else do[do.half == h]
    sn = dn if h == "ALL" else dn[dn.half == h]
    rem = so[so.grp == "REMOVED(vr<2.5)"]
    passed = so[so.vr >= 2.5]            # the filter's own complement in the unfiltered stream
    kept = so[so.grp == "KEPT(common)"]
    disp = so[so.grp.str.startswith("DISPLACED")]
    newo = sn[sn.grp == "NEW-ONLY(filtered run)"]
    for lab, g in [("removed vr<2.5", rem), ("passed vr>=2.5 (unfilt. run)", passed),
                   ("kept (common)", kept), ("displaced vr>=2.5", disp),
                   ("new-only (filt. run)", newo), ("ALL unfiltered", so), ("ALL filtered", sn)]:
        r = summ(g.Rnet, lab); r["half"] = h
        r["slipR"] = g.slipR.mean(); r["feefundR"] = g.feefundR.mean(); r["Rgross"] = g.Rgross.mean()
        r["slip_share_gross"] = g.slipR.sum() / g.Rgross.sum() if g.Rgross.sum() > 0 else np.nan
        r["med_stop_pct"] = g.stop_pct.median() * 100
        r["tp%"] = (g.exit_reason == "tp_hit").mean() * 100
        r["sl%"] = (g.exit_reason == "sl_hit").mean() * 100
        r["mh%"] = (g.exit_reason == "max_hold").mean() * 100
        rows.append(r)
    obs, p = perm_diff(rem.Rnet, passed.Rnet)
    ci, pc = cluster_boot_diff(rem, passed)
    obs2, p2 = perm_diff(rem.Rnet, kept.Rnet)
    wt = stats.ttest_ind(rem.Rnet, passed.Rnet, equal_var=False)
    mw = stats.mannwhitneyu(rem.Rnet, passed.Rnet, alternative="less")
    rho = stats.spearmanr(so.vr, so.Rnet)
    # slippage difference (gross-of-slip) test
    obs_s, p_s = perm_diff(-rem.slipR, -passed.slipR)   # H1: removed pay MORE slip (in R)
    obs_g, p_g = perm_diff(rem.Rgross, passed.Rgross)
    # win-rate diff: Fisher
    tab = [[(rem.Rnet > 0).sum(), (rem.Rnet <= 0).sum()],
           [(passed.Rnet > 0).sum(), (passed.Rnet <= 0).sum()]]
    fe = stats.fisher_exact(tab, alternative="less")
    tests.append(dict(half=h, n_rem=len(rem), n_pass=len(passed),
                      diff_rem_minus_pass=obs, perm_p_one_sided=p,
                      weekclusterCI_lo=ci[0], weekclusterCI_hi=ci[1], clusterboot_P_diff_ge0=pc,
                      welch_p_two=wt.pvalue, MWU_p_less=mw.pvalue,
                      diff_rem_minus_kept=obs2, perm_p_vs_kept=p2,
                      WR_fisher_p_less=fe.pvalue,
                      spearman_vr_R=rho.statistic, spearman_p=rho.pvalue,
                      slipR_rem_minus_pass=-obs_s, perm_p_slip=p_s,
                      Rgross_rem_minus_pass=obs_g, perm_p_gross=p_g))

S = pd.DataFrame(rows)
T = pd.DataFrame(tests)
pd.set_option("display.width", 250, "display.max_columns", 40)
print("\n=== group stats (Rnet = pnl / (qty*|intended_entry - sl0|)) ===")
print(S[["half", "group", "n", "meanR", "ci_lo", "ci_hi", "p_mean_le0", "WR", "WR_lo", "WR_hi",
         "sumR", "Rgross", "slipR", "feefundR", "slip_share_gross", "med_stop_pct",
         "tp%", "sl%", "mh%"]].round(3).to_string(index=False))
print("\n=== tests: removed vs passed (unfiltered stream) ===")
print(T.round(4).T.to_string())
S.to_csv(f"{OUT}/volfilter_groups.csv", index=False)
T.to_csv(f"{OUT}/volfilter_tests.csv", index=False)

# vol-ratio buckets (description only)
do["vb"] = pd.cut(do.vr, [0, 1, 1.5, 2, 2.5, 3.5, 5, 1e9])
print("\n=== Rnet by breakout vol-ratio bucket (unfiltered donchian) ===")
print(do.groupby(["vb", "half"], observed=True).Rnet.agg(["size", "mean"]).unstack().round(3))

# ---------------- R accounting: where does the filtered run's R come from? ---
print("\n=== R accounting (sum Rnet, donchian) ===")
for h in ["TRAIN", "TEST"]:
    so = do[do.half == h]; sn = dn[dn.half == h]
    print(h, f"unfiltered={so.Rnet.sum():+.1f} (n={len(so)})  filtered={sn.Rnet.sum():+.1f} (n={len(sn)})  "
          f"-removed={-so[so.grp=='REMOVED(vr<2.5)'].Rnet.sum():+.1f}  "
          f"-displaced={-so[so.grp.str.startswith('DISPLACED')].Rnet.sum():+.1f}  "
          f"+new-only={sn[sn.grp=='NEW-ONLY(filtered run)'].Rnet.sum():+.1f}  "
          f"(common old={so[so.grp=='KEPT(common)'].Rnet.sum():+.1f} / new={sn[sn.grp=='KEPT(common)'].Rnet.sum():+.1f})")

do.to_csv(f"{OUT}/unfiltered_donchian_with_vr.csv", index=False)
dn.to_csv(f"{OUT}/filtered_donchian_with_vr.csv", index=False)
