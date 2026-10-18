#!/usr/bin/env python3
"""Devam formasyonlari -- FINAL donem tek seferlik dogrulama -- implementation A.

Pre-registration: /home/user/sweep/research/devam_final/ON_KAYIT.md
Definitions/rules: /home/user/sweep/research/mum_formasyon_v1/ON_KAYIT.md, exactly as implemented in the verified
reference scratchpad/mum_final/analiz.py. Detection, indicators, trade loop, costs, R and the bootstrap are COPIED
from that reference unchanged (not imported). Only these change:
  * PERIOD: entry bar open in [2025-08-08, 2026-09-20)  (indicators warm up on all earlier data)
  * UNIVERSE: all 38 coins (every *_4h.csv in the data dir); EOS (data ends 2025-05-21) drops out by itself
  * Patterns: uclu (three white soldiers / black crows) and marubozu, 4h only
  * Bootstrap percentiles reported: 1.25 (one-sided 97.5 %, 2-test Bonferroni), 2.5, 97.5
  * Verdicts: DOGRULANDI / DESTEKLENDI / CURUDU per devam_final/ON_KAYIT.md
Run:  python3 -I analiz.py
Writes only into this script's directory: trades.csv, trades_full.csv, rows.csv, results.json, report.txt

Conventions inherited from the reference (literal readings of the v1 spec):
  * TR needs the previous bar's close -> ATR14 valid from index 14; ATR14 = simple mean of the last 14 TR incl.
    the completion bar; SMA50 = mean of last 50 closes incl. it (SMA unused by uclu/marubozu).
  * Marubozu: R > 0, G >= 0.9 R, R >= 1.5 ATR14, direction = body direction.
  * Uclu: three consecutive bull (bear) bars, strictly higher (lower) closes, each body >= 0.5 of its range.
  * Stop: LONG = lowest low of formation bar(s) - 0.1*ATR14(t); SHORT mirror. Target = entry +/- 2*dist.
  * Entry = open of the bar after the completion bar. Time exit at the close of the 10th bar (entry bar = 1).
    Stop before target inside a bar; gap through stop/target -> exit at the open.
  * One position per coin x pattern: a signal is ignored if its entry bar index <= the exit bar index of the open
    position. Period filter is applied first (a position opened before 2025-08-08 never blocks).
  * Exits may use bars after 2026-09-20 (only the entry must be inside the period).
  * A position still open at the end of the data is dropped (counted).
"""
import glob
import json
import math
import os

import numpy as np
import pandas as pd

DATA = "/home/user/sweep/research_data/h4_kirilim_v6/veri"
OUT = os.path.dirname(os.path.abspath(__file__))

ALL38 = sorted(os.path.basename(p)[:-len("_4h.csv")] for p in glob.glob(f"{DATA}/*_4h.csv"))
UNIVERSES = {"ALL38": ALL38}

T0 = int(pd.Timestamp("2025-08-08", tz="UTC").value // 10**6)  # entry bar open >= T0
T1 = int(pd.Timestamp("2026-09-20", tz="UTC").value // 10**6)  # entry bar open <  T1
H4_MS = 14_400_000

ATR_N = 14
SMA_N = 50
STOP_ATR = 0.1
TGT_R = 2.0
HOLD = 10  # time exit at the close of the 10th bar, entry bar = bar 1

FEE_BP = 1.0
SLIP_IN_N, SLIP_OUT_N = 15.85, 0.24
SLIP_IN_S, SLIP_OUT_S = 31.7, 0.48

SEED = 20261018
NBOOT = 10_000
BONF_Q = 1.25  # percentile (0.05 / 2 tests, one-sided lower bound)

PATTERNS = ["uclu", "marubozu"]
TFS = ["4h"]


# ----------------------------------------------------------------------------- data
def load_4h(coin):
    df = pd.read_csv(f"{DATA}/{coin}_4h.csv")
    df = df.drop_duplicates("open_time", keep="first").sort_values("open_time").reset_index(drop=True)
    return df[["open_time", "open", "high", "low", "close"]]


# ----------------------------------------------------------------------------- indicators
def sh(x, k):
    """y[i] = x[i-k]; NaN where unavailable."""
    y = np.full(len(x), np.nan)
    if k < len(x):
        y[k:] = x[:len(x) - k]
    return y


def exact_rolling_mean(x, n):
    """Mean of x[i-n+1..i] with math.fsum (exact summation); NaN if any element NaN / not enough history."""
    out = np.full(len(x), np.nan)
    xl = x.tolist()
    for i in range(n - 1, len(xl)):
        w = xl[i - n + 1:i + 1]
        if any(v != v for v in w):
            continue
        out[i] = math.fsum(w) / n
    return out


def indicators(O, H, L, C):
    pc = sh(C, 1)
    tr = np.maximum(H - L, np.maximum(np.abs(H - pc), np.abs(L - pc)))  # NaN on bar 0
    return exact_rolling_mean(tr, ATR_N), exact_rolling_mean(C, SMA_N)


# ----------------------------------------------------------------------------- patterns
def detect(pattern, O, H, L, C, atr, sma):
    """(long, short, lowbase, highbase) indexed by COMPLETION bar t; base = extreme of the formation bar(s)."""
    G = np.abs(C - O)
    R = H - L
    UW = H - np.maximum(O, C)
    LW = np.minimum(O, C) - L
    bull = C > O
    bear = C < O
    O1, H1, L1, C1 = sh(O, 1), sh(H, 1), sh(L, 1), sh(C, 1)
    O2, H2, L2, C2 = sh(O, 2), sh(H, 2), sh(L, 2), sh(C, 2)
    G1, R1 = np.abs(C1 - O1), H1 - L1
    G2, R2 = np.abs(C2 - O2), H2 - L2
    with np.errstate(invalid="ignore"):
        bull1, bear1 = C1 > O1, C1 < O1
        bull2, bear2 = C2 > O2, C2 < O2
        if pattern == "yutan":
            lg = bear1 & bull & (O <= C1) & (C >= O1) & (C < sma)
            st = bull1 & bear & (O >= C1) & (C <= O1) & (C > sma)
            lo, hi = np.minimum(L, L1), np.maximum(H, H1)
        elif pattern == "pinbar":
            base = (R > 0) & (G >= 0.05 * R)
            lg = base & (LW >= 2 * G) & (UW <= 0.25 * R) & (C < sma)
            st = base & (UW >= 2 * G) & (LW <= 0.25 * R) & (C > sma)
            lo, hi = L, H
        elif pattern == "icmum":
            inside = (H1 <= H2) & (L1 >= L2)
            lg = inside & (C > H2)
            st = inside & (C < L2)
            lo = np.minimum(np.minimum(L, L1), L2)
            hi = np.maximum(np.maximum(H, H1), H2)
        elif pattern == "yildiz":
            small1 = G1 <= 0.3 * R1
            mid2 = (O2 + C2) / 2.0
            lg = bear2 & (G2 >= 0.6 * R2) & small1 & bull & (C > mid2) & (C < sma)
            st = bull2 & (G2 >= 0.6 * R2) & small1 & bear & (C < mid2) & (C > sma)
            lo = np.minimum(np.minimum(L, L1), L2)
            hi = np.maximum(np.maximum(H, H1), H2)
        elif pattern == "uclu":
            strong = (G >= 0.5 * R) & (G1 >= 0.5 * R1) & (G2 >= 0.5 * R2)
            lg = bull & bull1 & bull2 & (C > C1) & (C1 > C2) & strong
            st = bear & bear1 & bear2 & (C < C1) & (C1 < C2) & strong
            lo = np.minimum(np.minimum(L, L1), L2)
            hi = np.maximum(np.maximum(H, H1), H2)
        elif pattern == "marubozu":
            m = (R > 0) & (G >= 0.9 * R) & (R >= 1.5 * atr)
            lg, st = m & bull, m & bear
            lo, hi = L, H
        else:
            raise ValueError(pattern)
        valid = np.isfinite(atr)
        lg, st = lg & valid, st & valid
    assert not np.any(lg & st)
    return lg, st, lo, hi


# ----------------------------------------------------------------------------- trade loop
def simulate(coin, universe, pattern, tf, ot, O, H, L, C, atr, lg, st, lo, hi, cnt, censored):
    n = len(C)
    trades = []
    last_exit = -1
    for t in np.flatnonzero(lg | st):
        j = t + 1
        if j >= n or not (T0 <= ot[j] < T1):
            continue
        cnt["signals_in_period"] += 1
        if j <= last_exit:
            cnt["ignored_open_pos"] += 1
            continue
        d = 1 if lg[t] else -1
        entry = O[j]
        stop = lo[t] - STOP_ATR * atr[t] if d == 1 else hi[t] + STOP_ATR * atr[t]
        dist = (entry - stop) * d
        if not (dist > 0):
            cnt["skipped_dist"] += 1
            continue
        tgt = entry + d * TGT_R * dist
        end = j + HOLD - 1
        ex, typ, k = None, None, None
        for k in range(j, min(end, n - 1) + 1):
            o, h, l, c = O[k], H[k], L[k], C[k]
            if d == 1:
                if o <= stop:
                    ex, typ = o, "gap_stop"
                elif o >= tgt:
                    ex, typ = o, "gap_target"
                elif l <= stop:
                    ex, typ = stop, "stop"
                elif h >= tgt:
                    ex, typ = tgt, "target"
            else:
                if o >= stop:
                    ex, typ = o, "gap_stop"
                elif o <= tgt:
                    ex, typ = o, "gap_target"
                elif h >= stop:
                    ex, typ = stop, "stop"
                elif l <= tgt:
                    ex, typ = tgt, "target"
            if ex is None and k == end:
                ex, typ = c, "time"
            if ex is not None:
                break
        if ex is None:
            # data ended before any spec exit -> R undefined under the spec: drop (counted); the position stays
            # open to the end of the data, so no later signal of this coin x pattern x TF can be taken.
            cnt["open_at_data_end_dropped"] += 1
            last_exit = n - 1
            censored.append(dict(coin=coin, universe=universe, pattern=pattern, tf=tf, dir=d,
                                 sig_time=int(ot[t]), entry_time=int(ot[j]), entry=entry, stop=stop,
                                 target=tgt, bars_available=n - j, last_close=C[n - 1],
                                 last_time=int(ot[n - 1])))
            continue
        last_exit = k
        cost_n = (2 * FEE_BP + SLIP_IN_N) * entry / 1e4 + SLIP_OUT_N * ex / 1e4
        cost_s = (2 * FEE_BP + SLIP_IN_S) * entry / 1e4 + SLIP_OUT_S * ex / 1e4
        gross = (ex - entry) * d
        trades.append(dict(
            coin=coin, universe=universe, pattern=pattern, tf=tf, dir=d,
            sig_time=int(ot[t]), entry_time=int(ot[j]), exit_time=int(ot[k]),
            entry=entry, stop=stop, target=tgt, exit=ex, exit_type=typ, bars=k - j + 1,
            dist=dist, R_gross=gross / dist, R_normal=(gross - cost_n) / dist, R_stress=(gross - cost_s) / dist,
        ))
    return trades


# ----------------------------------------------------------------------------- bootstrap
def week_key(ms):
    iso = pd.to_datetime(pd.Series(ms), unit="ms", utc=True).dt.isocalendar()
    return (iso["year"].astype(np.int64) * 100 + iso["week"].astype(np.int64)).values


def block_bootstrap(R, wk):
    """ISO-week block bootstrap of the ratio-of-sums mean; fresh default_rng(SEED) per test."""
    if len(R) == 0:
        return dict(p1_25=float("nan"), p2_5=float("nan"), p97_5=float("nan"), n_weeks=0)
    uw, inv = np.unique(wk, return_inverse=True)
    sR = np.bincount(inv, weights=R)
    sN = np.bincount(inv).astype(float)
    W = len(uw)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, W, size=(NBOOT, W))
    means = sR[idx].sum(axis=1) / sN[idx].sum(axis=1)
    lo, p25, p975 = np.percentile(means, [BONF_Q, 2.5, 97.5])
    return dict(p1_25=float(lo), p2_5=float(p25), p97_5=float(p975), n_weeks=int(W))


def summarize(tr):
    rows = []
    for p in PATTERNS:
        for tf in TFS:
            for uni in UNIVERSES:
                s = tr[(tr.pattern == p) & (tr.tf == tf) & (tr.universe == uni)]
                n = len(s)
                bs = block_bootstrap(s["R_normal"].values, s["week"].values)
                bss = block_bootstrap(s["R_stress"].values, s["week"].values)
                rows.append(dict(
                    pattern=p, tf=tf, universe=uni, n=int(n), coins=int(s.coin.nunique()),
                    meanR_normal=float(s.R_normal.mean()) if n else float("nan"),
                    meanR_stress=float(s.R_stress.mean()) if n else float("nan"),
                    meanR_gross=float(s.R_gross.mean()) if n else float("nan"),
                    win_rate=float((s.R_normal > 0).mean()) if n else float("nan"),
                    p1_25=bs["p1_25"], p2_5=bs["p2_5"], p97_5=bs["p97_5"], n_weeks=bs["n_weeks"],
                    stress_p1_25=bss["p1_25"], stress_p2_5=bss["p2_5"], stress_p97_5=bss["p97_5"]))
    return pd.DataFrame(rows)


def judge(res):
    """devam_final/ON_KAYIT.md: DOGRULANDI <=> NORMAL>0 & STRESS>0 & p1.25>0; DESTEKLENDI <=> both >0, p1.25<=0;
    else CURUDU. The lower bound is the NORMAL-R bootstrap (as in the reference's bonf_lo)."""
    out = []
    for p in PATTERNS:
        for tf in TFS:
            y = res[(res.pattern == p) & (res.tf == tf) & (res.universe == "ALL38")].iloc[0]
            pos = bool(y.meanR_normal > 0 and y.meanR_stress > 0)
            lo_ok = bool(y.p1_25 > 0)
            v = "DOGRULANDI" if (pos and lo_ok) else ("DESTEKLENDI" if pos else "CURUDU")
            out.append(dict(pattern=p, tf=tf, verdict=v, normal_stress_gt0=pos, p1_25_gt0=lo_ok))
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- lookahead check
def truncation_check(coin, f, cut_ms):
    """Indicators + detection on data truncated at cut_ms must equal the full-data values on the kept bars."""
    ot = f["open_time"].values.astype(np.int64)
    m = int(np.searchsorted(ot, cut_ms))
    if m < 60:
        return 0, 0
    full = [f[c].values.astype(float) for c in ("open", "high", "low", "close")]
    part = [x[:m] for x in full]
    a_f, s_f = indicators(*full)
    a_p, s_p = indicators(*part)
    diffs = int(np.sum(~np.isclose(a_f[:m], a_p, equal_nan=True, rtol=0, atol=0)))
    for p in PATTERNS:
        rf = detect(p, *full, a_f, s_f)
        rp = detect(p, *part, a_p, s_p)
        diffs += int(np.sum(rf[0][:m] != rp[0])) + int(np.sum(rf[1][:m] != rp[1]))
        diffs += int(np.sum(~np.isclose(rf[2][:m], rp[2], equal_nan=True, rtol=0, atol=0)))
        diffs += int(np.sum(~np.isclose(rf[3][:m], rp[3], equal_nan=True, rtol=0, atol=0)))
    return m, diffs


# ----------------------------------------------------------------------------- main
def main():
    all_trades, censored, counters, data_range = [], [], {}, {}
    trunc_bars, trunc_diffs = 0, 0
    cuts = [int(pd.Timestamp(x, tz="UTC").value // 10**6) for x in ("2025-12-01", "2026-04-15", "2026-08-01")]
    for uni, coins in UNIVERSES.items():
        for coin in coins:
            df4 = load_4h(coin)
            data_range[coin] = [int(df4.open_time.iloc[0]), int(df4.open_time.iloc[-1]), int(len(df4))]
            for tf, f in (("4h", df4),):
                ot = f["open_time"].values.astype(np.int64)
                O, H, L, C = (f[c].values.astype(float) for c in ("open", "high", "low", "close"))
                atr, sma = indicators(O, H, L, C)
                for p in PATTERNS:
                    lg, st, lo, hi = detect(p, O, H, L, C, atr, sma)
                    cnt = counters.setdefault(f"{p}|{tf}|{uni}", dict(
                        signals_in_period=0, ignored_open_pos=0, skipped_dist=0, open_at_data_end_dropped=0))
                    all_trades += simulate(coin, uni, p, tf, ot, O, H, L, C, atr, lg, st, lo, hi, cnt, censored)
                if ot[-1] >= T0:
                    for cm in cuts:
                        mb, dd = truncation_check(coin, f, cm)
                        trunc_bars += mb
                        trunc_diffs += dd

    tr = pd.DataFrame(all_trades)
    tr["week"] = week_key(tr["entry_time"].values)
    tr["month"] = pd.to_datetime(tr["entry_time"], unit="ms", utc=True).dt.strftime("%Y-%m")
    tr.to_csv(f"{OUT}/trades_full.csv", index=False)
    tr.rename(columns={"entry_time": "entry_ms", "exit_time": "exit_ms"})[
        ["coin", "pattern", "dir", "entry_ms", "exit_ms", "entry", "stop", "exit", "R_normal", "R_stress"]
    ].to_csv(f"{OUT}/trades.csv", index=False)

    res = summarize(tr)
    ver = judge(res)
    res.to_csv(f"{OUT}/rows.csv", index=False)

    diag = {}
    for p in PATTERNS:
        for tf in TFS:
            for uni in UNIVERSES:
                s = tr[(tr.pattern == p) & (tr.tf == tf) & (tr.universe == uni)]
                d = {nm: dict(n=int((s.dir == dd).sum()),
                              meanR_normal=float(s[s.dir == dd].R_normal.mean()) if (s.dir == dd).any() else None,
                              meanR_stress=float(s[s.dir == dd].R_stress.mean()) if (s.dir == dd).any() else None,
                              win_rate=float((s[s.dir == dd].R_normal > 0).mean()) if (s.dir == dd).any() else None)
                     for dd, nm in ((1, "long"), (-1, "short"))}
                d["monthly"] = {m: dict(n=int(len(g)), meanR_normal=round(float(g.R_normal.mean()), 4),
                                        meanR_stress=round(float(g.R_stress.mean()), 4))
                                for m, g in s.groupby("month")}
                d["per_coin"] = {c: dict(n=int(len(g)), meanR_normal=round(float(g.R_normal.mean()), 4))
                                 for c, g in s.groupby("coin")}
                d["coins_with_trades"] = int(s.coin.nunique())
                d["exit_mix"] = {k: int(v) for k, v in s.exit_type.value_counts().items()}
                d["exit_mix_meanR_normal"] = {k: round(float(g.R_normal.mean()), 4)
                                              for k, g in s.groupby("exit_type")}
                d["avg_bars"] = float(s.bars.mean()) if len(s) else None
                d["median_stop_dist_pct"] = float((s.dist / s.entry).median() * 100) if len(s) else None
                d["mean_cost_R_normal"] = float((s.R_gross - s.R_normal).mean()) if len(s) else None
                d["meanR_gross"] = float(s.R_gross.mean()) if len(s) else None
                d["sumR_normal"] = float(s.R_normal.sum())
                d["exits_after_period_end"] = int((s.exit_time >= T1).sum())
                d["first_entry"] = str(pd.to_datetime(s.entry_time.min(), unit="ms")) if len(s) else None
                d["last_entry"] = str(pd.to_datetime(s.entry_time.max(), unit="ms")) if len(s) else None
                d["counters"] = counters[f"{p}|{tf}|{uni}"]
                diag[f"{p}|{tf}|{uni}"] = d

    coins_no_period = [c for c, (a, b, n) in data_range.items() if b < T0]
    with open(f"{OUT}/results.json", "w") as fh:
        json.dump(dict(rows=res.to_dict("records"), verdicts=ver.to_dict("records"), diagnostics=diag,
                       censored_dropped=censored, data_range=data_range, coins_no_period_data=coins_no_period,
                       truncation_check=dict(bars_compared=trunc_bars, diffs=trunc_diffs),
                       period=["2025-08-08", "2026-09-20"]), fh, indent=1, default=float)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    lines = []
    cols = ["pattern", "tf", "universe", "n", "coins", "meanR_normal", "meanR_stress", "win_rate", "p1_25",
            "p2_5", "p97_5", "n_weeks", "stress_p1_25", "stress_p2_5", "stress_p97_5"]
    lines.append(res[cols].round(4).to_string(index=False))
    lines.append("")
    lines.append(ver.to_string(index=False))
    lines.append("")
    for key, d in diag.items():
        lines.append(f"== {key}")
        lines.append(f"  long : {d['long']}")
        lines.append(f"  short: {d['short']}")
        lines.append(f"  exit_mix: {d['exit_mix']}  meanR by exit: {d['exit_mix_meanR_normal']}")
        lines.append(f"  avg_bars={d['avg_bars']:.2f} median_stop_dist%={d['median_stop_dist_pct']:.3f} "
                     f"mean_cost_R={d['mean_cost_R_normal']:.4f} gross={d['meanR_gross']:.4f} "
                     f"exits_after_T1={d['exits_after_period_end']} first={d['first_entry']} last={d['last_entry']}")
        lines.append(f"  counters: {d['counters']}")
        lines.append("  monthly: " + " ".join(f"{m}:{v['n']}/{v['meanR_normal']:+.3f}"
                                              for m, v in d["monthly"].items()))
        lines.append("  per_coin: " + " ".join(f"{c}:{v['n']}/{v['meanR_normal']:+.2f}"
                                               for c, v in d["per_coin"].items()))
    lines.append("")
    lines.append(f"censored (open at data end, dropped): {len(censored)}")
    lines.append(f"coins without period data: {coins_no_period}")
    lines.append(f"truncation (lookahead) check: bars_compared={trunc_bars} diffs={trunc_diffs}")
    txt = "\n".join(lines)
    print(txt)
    with open(f"{OUT}/report.txt", "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
