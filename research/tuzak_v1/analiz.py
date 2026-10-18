#!/usr/bin/env python3
"""Tuzak v1 (failed crowd pattern) -- FINAL implementation.

Implements /home/user/sweep/research/tuzak_v1/ON_KAYIT.md exactly (no tuning).
Pattern definitions (yutan, pin bar incl. SMA50 context) = /home/user/sweep/research/mum_formasyon_v1/ON_KAYIT.md;
detection, data loading, 1D building, ATR14/SMA50, cost and bootstrap code are COPIED verbatim from the verified
reference mum_final/analiz.py (not imported).
Run:  python3 -I analiz.py
Writes only into this script's directory: trades.csv, trades_completion_gate.csv, rows.csv, results.json, report.txt

Trap rules (ON_KAYIT):
  * Bullish pattern (crowd LONG) completes at bar c. L_trig = pattern_low - 0.1*ATR14(c). Watch bars c+1..c+3; the
    FIRST bar k with low <= L_trig triggers a SHORT; entry = L_trig, or open[k] if open[k] < L_trig.
    Stop = pattern_high + 0.1*ATR14(c); target = entry - 2*(stop - entry). Mirror for bearish patterns -> LONG
    (H_trig = pattern_high + 0.1*ATR, stop = pattern_low - 0.1*ATR).
    pattern_low/high = min low / max high of the pattern bar(s) (yutan: c-1,c ; pin bar: c).
  * Exits are checked from the entry bar on. Entry bar (its open precedes the entry, so no gap rule): stop level seen
    -> STOP at the stop price; else target level seen -> TARGET at the target price (both seen -> STOP).
    Later bars: open beyond stop -> exit at that open; open beyond target -> exit at that open; else stop level seen
    -> stop; else target seen -> target (both -> stop). Time exit at the close of bar 10 (entry bar = bar 1).
  * No trigger within 3 bars -> no trade. Period filter by ENTRY (trigger) bar open in [2020-01-01, 2025-08-08).
  * R = (exit-entry)*dir/|entry-stop| - cost/|entry-stop|; NORMAL cost = (2*1+15.85)bp*entry + 0.24bp*exit,
    STRESS = (2*1+31.7)bp*entry + 0.48bp*exit.

A/B reconciliation (decided here):
  Every detection, trigger, entry, stop, target, exit and R agreed between A and B (and the reviewer's engine) for
  every trade both took; the ONLY difference is the reading of "Ayni coinde ayni test icin tek pozisyon":
    * A  (entry-gated): a triggered signal is ignored iff its ENTRY bar index <= exit bar index of the open
      position (the reference's verified rule "a signal is ignored if its entry bar index <= the exit bar index of
      the open position", with entry bar = trigger bar). Pending (untriggered) stop orders are not positions.
    * B  (completion-gated): additionally discards a pattern that COMPLETES while a position is open (entry <= c <
      exit), even when its order would first be touched only after that position has closed.
  Decision: A. The pre-registration restricts POSITIONS ("tek pozisyon"), not pending orders; B's extra exclusion
  is a rule the spec does not contain (it never lets two positions overlap either way). A's rule is the reference's
  literal one-position rule transferred to the trap's entry bar. B's convention is reported as a sensitivity
  (verdicts identical).

Other conventions (identical in A, B and the reviewer):
  * Each signal's trigger bar is its FIRST touch in c+1..c+3, independent of position state; if that first touch
    falls while a position is open (or on its exit bar), or outside the period, the signal is consumed (no re-arming).
  * Candidates are processed chronologically by entry bar; same-bar ties -> the older pattern (smaller c) is taken.
  * Out-of-period entries neither trade nor block (period filter applied first, as in the reference).
  * A position with no spec exit before the data end would be dropped (counted) and block later signals (0 occur).
  * Trigger rate = signals with a trigger / signals whose bar c+1 opens in the period (position state ignored).
  * 1D bar = UTC day built from 4h bars; kept only if all six 4h slots exist. ATR14 = simple mean of the last 14 TR
    incl. bar c (TR needs the previous close); SMA50 = mean of the last 50 closes incl. bar c.
"""
import json
import math
import os

import numpy as np
import pandas as pd

DATA = "/home/user/sweep/research_data/h4_kirilim_v6/veri"
OUT = os.path.dirname(os.path.abspath(__file__))

ESKI12 = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
YENI26 = ("LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV "
          "HBAR VET APT ARB OP INJ SUI").split()
UNIVERSES = {"ESKI12": ESKI12, "YENI26": YENI26}

T0 = int(pd.Timestamp("2020-01-01", tz="UTC").value // 10**6)  # entry bar open >= T0
T1 = int(pd.Timestamp("2025-08-08", tz="UTC").value // 10**6)  # entry bar open <  T1
H4_MS = 14_400_000
DAY_MS = 86_400_000

ATR_N = 14
SMA_N = 50
TRIG_ATR = 0.1   # trigger offset beyond the pattern extreme
STOP_ATR = 0.1   # stop offset beyond the opposite pattern extreme
TGT_R = 2.0
WAIT = 3         # trigger window: bars c+1..c+3
HOLD = 10        # time exit at the close of the 10th bar, entry bar = bar 1

FEE_BP = 1.0
SLIP_IN_N, SLIP_OUT_N = 15.85, 0.24
SLIP_IN_S, SLIP_OUT_S = 31.7, 0.48

SEED = 20261018
NBOOT = 10_000
BONF_Q = 0.625  # percentile (0.05 / 4 tests, one-sided lower bound)

PATTERNS = ["yutan", "pinbar"]
TESTS = {"yutan": "yutan_tuzak", "pinbar": "pinbar_tuzak"}
TFS = ["4h", "1D"]


# ----------------------------------------------------------------------------- data (copied from reference)
def load_4h(coin):
    df = pd.read_csv(f"{DATA}/{coin}_4h.csv")
    df = df.drop_duplicates("open_time", keep="first").sort_values("open_time").reset_index(drop=True)
    return df[["open_time", "open", "high", "low", "close"]]


def to_daily(df4):
    """UTC-day bars; a day is kept only if all six 4h slots 00,04,...,20 are present."""
    day = df4["open_time"].values // DAY_MS
    slot = (df4["open_time"].values - day * DAY_MS) // H4_MS
    tmp = df4.assign(day=day, slot=slot)
    g = tmp.groupby("day", sort=True)
    d = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
              close=("close", "last"), nbar=("open", "size"),
              s0=("slot", "first"), s5=("slot", "last"), snu=("slot", "nunique"))
    keep = (d["nbar"] == 6) & (d["snu"] == 6) & (d["s0"] == 0) & (d["s5"] == 5)
    dropped = int((~keep).sum())
    d = d[keep]
    d = d.assign(open_time=(d.index.values.astype(np.int64) * DAY_MS)).reset_index(drop=True)
    return d[["open_time", "open", "high", "low", "close"]], dropped


# ----------------------------------------------------------------------------- indicators (copied)
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


# ----------------------------------------------------------------------------- patterns (copied: yutan, pinbar)
def detect(pattern, O, H, L, C, atr, sma):
    """(bull, bear, lowbase, highbase) indexed by COMPLETION bar c; base = extreme of the pattern bar(s).
    bull = classic LONG pattern (crowd long), bear = classic SHORT pattern (crowd short)."""
    G = np.abs(C - O)
    R = H - L
    UW = H - np.maximum(O, C)
    LW = np.minimum(O, C) - L
    bull = C > O
    bear = C < O
    O1, H1, L1, C1 = sh(O, 1), sh(H, 1), sh(L, 1), sh(C, 1)
    with np.errstate(invalid="ignore"):
        bull1, bear1 = C1 > O1, C1 < O1
        if pattern == "yutan":
            lg = bear1 & bull & (O <= C1) & (C >= O1) & (C < sma)
            st = bull1 & bear & (O >= C1) & (C <= O1) & (C > sma)
            lo, hi = np.minimum(L, L1), np.maximum(H, H1)
        elif pattern == "pinbar":
            base = (R > 0) & (G >= 0.05 * R)
            lg = base & (LW >= 2 * G) & (UW <= 0.25 * R) & (C < sma)
            st = base & (UW >= 2 * G) & (LW <= 0.25 * R) & (C > sma)
            lo, hi = L, H
        else:
            raise ValueError(pattern)
        valid = np.isfinite(atr)
        lg, st = lg & valid, st & valid
    assert not np.any(lg & st)
    return lg, st, lo, hi


# ----------------------------------------------------------------------------- trigger + exit
def find_trigger(crowd, c, O, H, L, lo, hi, atr, n):
    """crowd=+1 bullish pattern -> SHORT trap; crowd=-1 bearish pattern -> LONG trap.
    Returns (k, dir, entry, stop, trig_level) for the FIRST touch in c+1..c+3, or None."""
    a = atr[c]
    if crowd == 1:
        trig = lo[c] - TRIG_ATR * a
        stop = hi[c] + STOP_ATR * a
        for k in range(c + 1, min(c + WAIT, n - 1) + 1):
            if L[k] <= trig:
                entry = O[k] if O[k] < trig else trig
                return k, -1, entry, stop, trig
    else:
        trig = hi[c] + TRIG_ATR * a
        stop = lo[c] - STOP_ATR * a
        for k in range(c + 1, min(c + WAIT, n - 1) + 1):
            if H[k] >= trig:
                entry = O[k] if O[k] > trig else trig
                return k, 1, entry, stop, trig
    return None


def simulate_exit(d, j, entry, stop, tgt, O, H, L, C, n, eb_mode="spec"):
    """Returns (exit_price, exit_type, exit_bar) or None if the data end first.
    eb_mode (decision-free sensitivity only; 'spec' is the pre-registered rule): 'open_beyond_skip' ignores the
    entry-bar stop check when the entry bar OPENED beyond the stop; 'no_eb_stop' ignores every entry-bar stop check."""
    end = j + HOLD - 1
    for k in range(j, min(end, n - 1) + 1):
        o, h, l, c = O[k], H[k], L[k], C[k]
        ex = typ = None
        if d == 1:
            stop_seen, tgt_seen = l <= stop, h >= tgt
            gap_stop, gap_tgt = o <= stop, o >= tgt
        else:
            stop_seen, tgt_seen = h >= stop, l <= tgt
            gap_stop, gap_tgt = o >= stop, o <= tgt
        if k == j:  # entry bar: levels only, stop priority, no gap rule
            if eb_mode == "no_eb_stop" or (eb_mode == "open_beyond_skip" and gap_stop):
                stop_seen = False
            if stop_seen:
                ex, typ = stop, "stop"
            elif tgt_seen:
                ex, typ = tgt, "target"
        else:
            if gap_stop:
                ex, typ = o, "gap_stop"
            elif gap_tgt:
                ex, typ = o, "gap_target"
            elif stop_seen:
                ex, typ = stop, "stop"
            elif tgt_seen:
                ex, typ = tgt, "target"
        if ex is None and k == end:
            ex, typ = c, "time"
        if ex is not None:
            return ex, typ, k
    return None


def make_trade(base, ex, typ, k, ot):
    entry, d, dist = base["entry"], base["dir"], base["dist"]
    cost_n = (2 * FEE_BP + SLIP_IN_N) * entry / 1e4 + SLIP_OUT_N * ex / 1e4
    cost_s = (2 * FEE_BP + SLIP_IN_S) * entry / 1e4 + SLIP_OUT_S * ex / 1e4
    gross = (ex - entry) * d
    t = dict(base)
    t.update(exit_time=int(ot[k]), exit=ex, exit_type=typ, bars=k - base["_j"] + 1,
             R_gross=gross / dist, R_normal=(gross - cost_n) / dist, R_stress=(gross - cost_s) / dist)
    return t


def take(cands, O, H, L, C, ot, n, gate="entry", eb_mode="spec"):
    """One position per coin x test x TF. cands must be sorted by (entry bar, completion bar).
    gate='entry' (FINAL): ignore iff entry bar <= exit bar of the open position.
    gate='completion' (B, sensitivity): additionally ignore if a taken position was open at the close of the
    pattern's completion bar c (entry <= c < exit)."""
    trades, cens, taken = [], [], []
    last_exit = -1
    ign = 0
    for b in cands:
        if b["_j"] <= last_exit or (gate == "completion" and any(e <= b["_c"] < x for e, x in taken)):
            ign += 1
            continue
        r = simulate_exit(b["dir"], b["_j"], b["entry"], b["stop"], b["target"], O, H, L, C, n, eb_mode)
        if r is None:
            last_exit = n - 1
            taken.append((b["_j"], n))
            cens.append(dict(b, bars_available=n - b["_j"], last_close=float(C[n - 1]), last_time=int(ot[n - 1])))
            continue
        ex, typ, k = r
        last_exit = k
        taken.append((b["_j"], k))
        trades.append(make_trade(b, ex, typ, k, ot))
    return trades, cens, ign


def run_test(coin, universe, pattern, tf, ot, O, H, L, C, atr, lg, st, lo, hi, cnt):
    n = len(C)
    test = TESTS[pattern]
    cands = []
    for c in np.flatnonzero(lg | st):
        crowd = 1 if lg[c] else -1
        in_win = (c + 1 < n) and (T0 <= ot[c + 1] < T1)
        if in_win:
            cnt["signals_in_period"] += 1
            cnt["signals_bull_pattern" if crowd == 1 else "signals_bear_pattern"] += 1
        tg = find_trigger(crowd, c, O, H, L, lo, hi, atr, n)
        if tg is None:
            continue
        k, d, entry, stop, trig = tg
        if in_win:
            cnt["triggered"] += 1
            cnt["triggered_bull_pattern" if crowd == 1 else "triggered_bear_pattern"] += 1
            cnt[f"trig_bar_{k - c}"] += 1
        if not (T0 <= ot[k] < T1):
            continue
        dist = (entry - stop) * d
        if not (dist > 0):
            cnt["skipped_dist"] += 1
            continue
        tgt = entry + d * TGT_R * dist
        cands.append(dict(coin=coin, universe=universe, test=test, pattern=pattern, tf=tf, dir=d,
                          sig_time=int(ot[c]), entry_time=int(ot[k]), wait_bars=int(k - c), trig=trig,
                          entry=entry, stop=stop, target=tgt, dist=dist, gap_entry=bool(entry != trig),
                          _c=int(c), _j=int(k)))
    cands.sort(key=lambda b: (b["_j"], b["_c"]))
    js = [b["_j"] for b in cands]
    cnt["same_entry_bar_ties"] += int(sum(1 for i in range(1, len(js)) if js[i] == js[i - 1]))
    cnt["candidates_in_period"] += len(cands)
    trades, cens, ign = take(cands, O, H, L, C, ot, n, "entry")
    cnt["ignored_open_pos"] += ign
    cnt["open_at_data_end_dropped"] += len(cens)
    comp, comp_cens, _ = take(cands, O, H, L, C, ot, n, "completion")
    sens = {m: take(cands, O, H, L, C, ot, n, "entry", m)[0] for m in ("open_beyond_skip", "no_eb_stop")}
    return trades, cens, comp, comp_cens, sens


# ----------------------------------------------------------------------------- bootstrap (copied, Bonf 0.625)
def week_key(ms):
    iso = pd.to_datetime(pd.Series(ms), unit="ms", utc=True).dt.isocalendar()
    return (iso["year"].astype(np.int64) * 100 + iso["week"].astype(np.int64)).values


def block_bootstrap(R, wk):
    """ISO-week block bootstrap of the ratio-of-sums mean; fresh default_rng(SEED) per test."""
    if len(R) == 0:
        return dict(bonf_lo=float("nan"), p2_5=float("nan"), p97_5=float("nan"), n_weeks=0)
    uw, inv = np.unique(wk, return_inverse=True)
    sR = np.bincount(inv, weights=R)
    sN = np.bincount(inv).astype(float)
    W = len(uw)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, W, size=(NBOOT, W))
    means = sR[idx].sum(axis=1) / sN[idx].sum(axis=1)
    lo, p25, p975 = np.percentile(means, [BONF_Q, 2.5, 97.5])
    return dict(bonf_lo=float(lo), p2_5=float(p25), p97_5=float(p975), n_weeks=int(W))


def summarize(tr, counters):
    rows = []
    for p in PATTERNS:
        for tf in TFS:
            for uni in UNIVERSES:
                s = tr[(tr.pattern == p) & (tr.tf == tf) & (tr.universe == uni)]
                n = len(s)
                bs = block_bootstrap(s["R_normal"].values, s["week"].values)
                bss = block_bootstrap(s["R_stress"].values, s["week"].values)
                cn = counters[f"{p}|{tf}|{uni}"]
                rows.append(dict(
                    test=TESTS[p], tf=tf, universe=uni, n=int(n),
                    meanR_normal=float(s.R_normal.mean()) if n else float("nan"),
                    meanR_stress=float(s.R_stress.mean()) if n else float("nan"),
                    meanR_gross=float(s.R_gross.mean()) if n else float("nan"),
                    win_rate=float((s.R_normal > 0).mean()) if n else float("nan"),
                    bonf_lo=bs["bonf_lo"], p2_5=bs["p2_5"], p97_5=bs["p97_5"], n_weeks=bs["n_weeks"],
                    stress_bonf_lo=bss["bonf_lo"], stress_p2_5=bss["p2_5"], stress_p97_5=bss["p97_5"],
                    trigger_rate=cn["triggered"] / cn["signals_in_period"] if cn["signals_in_period"] else float("nan"),
                    signals=cn["signals_in_period"]))
    return pd.DataFrame(rows)


def judge(res):
    out = []
    for p in PATTERNS:
        for tf in TFS:
            e = res[(res.test == TESTS[p]) & (res.tf == tf) & (res.universe == "ESKI12")].iloc[0]
            y = res[(res.test == TESTS[p]) & (res.tf == tf) & (res.universe == "YENI26")].iloc[0]
            c1 = bool(e.meanR_normal > 0)
            c2 = bool(y.meanR_normal > 0 and y.meanR_stress > 0)
            c3 = bool(y.bonf_lo > 0)
            c4 = bool(y.n >= 100)
            out.append(dict(test=TESTS[p], tf=tf, verdict="TUTTU" if (c1 and c2 and c3 and c4) else "TUTMADI",
                            c1_secim_normal_gt0=c1, c2_sinav_normal_stress_gt0=c2, c3_sinav_bonf_gt0=c3,
                            c4_sinav_n_ge100=c4))
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- main
def main():
    all_trades, comp_all, censored, comp_censored, counters, days_dropped = [], [], [], [], {}, {}
    eb_sens = {"open_beyond_skip": [], "no_eb_stop": []}
    keys = ["signals_in_period", "signals_bull_pattern", "signals_bear_pattern", "triggered",
            "triggered_bull_pattern", "triggered_bear_pattern", "trig_bar_1", "trig_bar_2", "trig_bar_3",
            "candidates_in_period", "ignored_open_pos", "skipped_dist", "open_at_data_end_dropped",
            "same_entry_bar_ties"]
    for uni, coins in UNIVERSES.items():
        for coin in coins:
            df4 = load_4h(coin)
            d1, ndrop = to_daily(df4)
            days_dropped[coin] = ndrop
            for tf, f in (("4h", df4), ("1D", d1)):
                ot = f["open_time"].values.astype(np.int64)
                O, H, L, C = (f[c].values.astype(float) for c in ("open", "high", "low", "close"))
                atr, sma = indicators(O, H, L, C)
                for p in PATTERNS:
                    lg, st, lo, hi = detect(p, O, H, L, C, atr, sma)
                    cnt = counters.setdefault(f"{p}|{tf}|{uni}", {k: 0 for k in keys})
                    tr, cens, comp, comp_cens, sens = run_test(coin, uni, p, tf, ot, O, H, L, C, atr, lg, st,
                                                               lo, hi, cnt)
                    all_trades += tr
                    censored += cens
                    comp_all += comp
                    comp_censored += comp_cens
                    for m in eb_sens:
                        eb_sens[m] += sens[m]

    def frame(lst):
        t = pd.DataFrame(lst).drop(columns=["_c", "_j"])
        t["week"] = week_key(t["entry_time"].values)
        t["year"] = pd.to_datetime(t["entry_time"], unit="ms", utc=True).dt.year
        return t

    tr = frame(all_trades)
    tr.to_csv(f"{OUT}/trades.csv", index=False)
    res = summarize(tr, counters)
    ver = judge(res)
    res.to_csv(f"{OUT}/rows.csv", index=False)

    # sensitivity 1: B's completion-gated one-position convention
    tc = frame(comp_all)
    tc.to_csv(f"{OUT}/trades_completion_gate.csv", index=False)
    res_c = summarize(tc, counters)
    ver_c = judge(res_c)
    kcols = ["coin", "test", "tf", "sig_time", "entry_time"]
    mk = tr[kcols + ["R_normal"]].merge(tc[kcols + ["R_normal"]], on=kcols, how="outer", indicator=True,
                                         suffixes=("_final", "_comp"))
    both = mk[mk._merge == "both"]
    conv_cmp = dict(final_only=int((mk._merge == "left_only").sum()),
                    completion_only=int((mk._merge == "right_only").sum()), both=int(len(both)),
                    both_max_abs_dR=float((both.R_normal_final - both.R_normal_comp).abs().max()))

    # sensitivity 2 (decision-free, not pre-registered): entry-bar stop conventions
    eb_rows = []
    for m, lst in eb_sens.items():
        t = frame(lst)
        for p in PATTERNS:
            for tf in TFS:
                for uni in UNIVERSES:
                    s = t[(t.pattern == p) & (t.tf == tf) & (t.universe == uni)]
                    bs = block_bootstrap(s["R_normal"].values, s["week"].values)
                    eb_rows.append(dict(variant=m, test=TESTS[p], tf=tf, universe=uni, n=int(len(s)),
                                        meanR_normal=float(s.R_normal.mean()), meanR_stress=float(s.R_stress.mean()),
                                        bonf_lo=bs["bonf_lo"]))

    diag = {}
    for p in PATTERNS:
        for tf in TFS:
            for uni in UNIVERSES:
                s = tr[(tr.pattern == p) & (tr.tf == tf) & (tr.universe == uni)]
                cn = counters[f"{p}|{tf}|{uni}"]
                d = {nm: dict(n=int((s.dir == dd).sum()),
                              meanR_normal=float(s[s.dir == dd].R_normal.mean()) if (s.dir == dd).any() else None,
                              meanR_stress=float(s[s.dir == dd].R_stress.mean()) if (s.dir == dd).any() else None)
                     for dd, nm in ((1, "long_trade_after_bear_pattern"), (-1, "short_trade_after_bull_pattern"))}
                d["yearly"] = {int(y): dict(n=int(len(g)), meanR_normal=round(float(g.R_normal.mean()), 4),
                                            meanR_stress=round(float(g.R_stress.mean()), 4))
                               for y, g in s.groupby("year")}
                d["exit_mix"] = {k: int(v) for k, v in s.exit_type.value_counts().items()}
                d["exit_on_entry_bar"] = int((s.bars == 1).sum())
                d["avg_bars"] = float(s.bars.mean()) if len(s) else None
                d["median_stop_dist_pct"] = float((s.dist / s.entry).median() * 100) if len(s) else None
                d["mean_cost_R_normal"] = float((s.R_gross - s.R_normal).mean()) if len(s) else None
                d["gap_entries"] = int(s.gap_entry.sum())
                d["exits_after_period_end"] = int((s.exit_time >= T1).sum())
                d["trigger_rate"] = dict(
                    all=cn["triggered"] / cn["signals_in_period"] if cn["signals_in_period"] else None,
                    bull_pattern_to_short=(cn["triggered_bull_pattern"] / cn["signals_bull_pattern"]
                                           if cn["signals_bull_pattern"] else None),
                    bear_pattern_to_long=(cn["triggered_bear_pattern"] / cn["signals_bear_pattern"]
                                          if cn["signals_bear_pattern"] else None))
                d["counters"] = cn
                diag[f"{TESTS[p]}|{tf}|{uni}"] = d

    with open(f"{OUT}/results.json", "w") as fh:
        json.dump(dict(rows=res.to_dict("records"), verdicts=ver.to_dict("records"), diagnostics=diag,
                       sensitivity_completion_gate=dict(rows=res_c.to_dict("records"),
                                                        verdicts=ver_c.to_dict("records"),
                                                        verdicts_same=bool((ver_c.verdict.values ==
                                                                            ver.verdict.values).all()),
                                                        trade_comparison=conv_cmp,
                                                        censored=len(comp_censored)),
                       sensitivity_entry_bar_stop=eb_rows,
                       censored_dropped=[{k: v for k, v in c.items() if not k.startswith("_")} for c in censored],
                       days_dropped_1D=days_dropped), fh, indent=1, default=float)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    lines = []
    cols = ["test", "tf", "universe", "n", "meanR_normal", "meanR_stress", "meanR_gross", "win_rate", "bonf_lo",
            "p2_5", "p97_5", "n_weeks", "stress_bonf_lo", "trigger_rate", "signals"]
    lines.append("FINAL (entry-gated one-position rule)")
    lines.append(res[cols].round(4).to_string(index=False))
    lines.append("")
    lines.append(ver.to_string(index=False))
    lines.append("")
    lines.append("SENSITIVITY: completion-gated one-position rule (implementation B's convention)")
    lines.append(res_c[cols[:-2]].round(4).to_string(index=False))
    lines.append(f"verdicts_same={bool((ver_c.verdict.values == ver.verdict.values).all())}  trades: {conv_cmp}")
    lines.append("")
    lines.append("SENSITIVITY (decision-free, not pre-registered): entry-bar stop conventions")
    lines.append(pd.DataFrame(eb_rows).round(4).to_string(index=False))
    lines.append("")
    for kk, d in diag.items():
        lines.append(f"{kk}: L={d['long_trade_after_bear_pattern']} S={d['short_trade_after_bull_pattern']}")
        lines.append(f"   exit_mix={d['exit_mix']} entry_bar_exits={d['exit_on_entry_bar']} avg_bars={d['avg_bars']:.2f}"
                     f" stopdist%={d['median_stop_dist_pct']:.3f} costR={d['mean_cost_R_normal']:.4f}"
                     f" gap_entries={d['gap_entries']}")
        lines.append(f"   trigger_rate={ {k: round(v, 4) for k, v in d['trigger_rate'].items()} }")
        lines.append(f"   yearly={ {y: v['meanR_normal'] for y, v in d['yearly'].items()} }")
        lines.append(f"   counters={d['counters']}")
    lines.append(f"censored (open at data end, dropped): final={len(censored)} completion_gate={len(comp_censored)}")
    lines.append(f"1D days dropped (incomplete): {days_dropped}")
    txt = "\n".join(lines)
    print(txt)
    with open(f"{OUT}/report.txt", "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
