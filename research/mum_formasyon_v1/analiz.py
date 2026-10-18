#!/usr/bin/env python3
"""Mum formasyonlari v1 -- FINAL implementation.

Implements /home/user/sweep/research/mum_formasyon_v1/ON_KAYIT.md exactly (no tuning).
Run:  python3 -I analiz.py
Writes only into this script's directory: trades.csv, rows.csv, results.json, report.txt

A/B reconciliation (decided here, see report.txt):
  The two implementations agreed on every detection, stop, exit and R; they differed only at the END OF DATA
  (EOS, whose 4h file stops at 2025-05-21 08:00 UTC, inside the study period):
    * A required the full 10-bar holding window to exist BEFORE simulating, so it dropped EOS 4h pinbar
      (entry 2025-05-20 12:00) although its STOP was hit on bar 6 inside the data -> A bug (the spec has no
      "10 future bars must exist" filter; the trade is fully determined by the spec's exit rules). KEPT here.
    * B closed EOS 1D yutan (entry 2025-05-15, short) at the last daily close ('veri_sonu') after 6 bars with
      neither stop, target nor the 10-bar time exit reached. That exit price is not one of the spec's exit
      rules (stop / target / gaps / close of bar 10), so the trade's R is undefined under the spec -> DROPPED
      and counted (project convention: "a position still open when the data end is dropped (counted)").
      Sensitivity with B's last-close exit is reported (verdicts unchanged).

Conventions (identical in A, B and the reviewer's reference; literal readings of the spec):
  * 1D bar = UTC day built from 4h bars; the day is kept only if all six 4h slots (00,04,...,20) exist.
  * TR needs the previous bar's close (undefined on the first bar) -> ATR14 valid from index 14.
    ATR14 = simple mean of the last 14 TR incl. the completion bar; SMA50 = mean of last 50 closes incl. it.
  * Yutan: body containment inclusive (O_t <= C_{t-1} and C_t >= O_{t-1} for LONG; mirror for SHORT).
  * Pin bar: R > 0 required. Marubozu: direction = body direction.
  * Inside bar: t-2 mother, t-1 inside (H<=, L>= inclusive), t breakout bar (strict close beyond the mother
    high/low); completion bar = t; formation bars for the stop = mother + inside + breakout.
  * Stop: LONG = lowest low of formation bar(s) - 0.1*ATR14(t); SHORT mirror. Target = entry +/- 2*dist.
  * One position per coin x pattern x TF: a signal is ignored if its entry bar index <= the exit bar index of
    the open position. Period filter (entry bar open in [2020-01-01, 2025-08-08)) is applied first.
  * Exits may use bars after 2025-08-08 (only the entry must be inside the period).
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
STOP_ATR = 0.1
TGT_R = 2.0
HOLD = 10  # time exit at the close of the 10th bar, entry bar = bar 1

FEE_BP = 1.0
SLIP_IN_N, SLIP_OUT_N = 15.85, 0.24
SLIP_IN_S, SLIP_OUT_S = 31.7, 0.48

SEED = 20261018
NBOOT = 10_000
BONF_Q = 0.21  # percentile (0.05 / 12 tests, one-sided lower bound)

PATTERNS = ["yutan", "pinbar", "icmum", "yildiz", "uclu", "marubozu"]
TFS = ["4h", "1D"]


# ----------------------------------------------------------------------------- data
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
                    pattern=p, tf=tf, universe=uni, n=int(n),
                    meanR_normal=float(s.R_normal.mean()) if n else float("nan"),
                    meanR_stress=float(s.R_stress.mean()) if n else float("nan"),
                    meanR_gross=float(s.R_gross.mean()) if n else float("nan"),
                    win_rate=float((s.R_normal > 0).mean()) if n else float("nan"),
                    bonf_lo=bs["bonf_lo"], p2_5=bs["p2_5"], p97_5=bs["p97_5"], n_weeks=bs["n_weeks"],
                    stress_bonf_lo=bss["bonf_lo"], stress_p2_5=bss["p2_5"], stress_p97_5=bss["p97_5"]))
    return pd.DataFrame(rows)


def judge(res):
    out = []
    for p in PATTERNS:
        for tf in TFS:
            e = res[(res.pattern == p) & (res.tf == tf) & (res.universe == "ESKI12")].iloc[0]
            y = res[(res.pattern == p) & (res.tf == tf) & (res.universe == "YENI26")].iloc[0]
            c1 = bool(e.meanR_normal > 0)
            c2 = bool(y.meanR_normal > 0 and y.meanR_stress > 0)
            c3 = bool(y.bonf_lo > 0)
            c4 = bool(y.n >= 100)
            out.append(dict(pattern=p, tf=tf, verdict="TUTTU" if (c1 and c2 and c3 and c4) else "TUTMADI",
                            c1_secim_normal_gt0=c1, c2_sinav_normal_stress_gt0=c2, c3_sinav_bonf_gt0=c3,
                            c4_sinav_n_ge100=c4))
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- main
def main():
    all_trades, censored, counters, days_dropped = [], [], {}, {}
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
                    cnt = counters.setdefault(f"{p}|{tf}|{uni}", dict(
                        signals_in_period=0, ignored_open_pos=0, skipped_dist=0, open_at_data_end_dropped=0))
                    all_trades += simulate(coin, uni, p, tf, ot, O, H, L, C, atr, lg, st, lo, hi, cnt, censored)

    tr = pd.DataFrame(all_trades)
    tr["week"] = week_key(tr["entry_time"].values)
    tr["year"] = pd.to_datetime(tr["entry_time"], unit="ms", utc=True).dt.year
    tr.to_csv(f"{OUT}/trades.csv", index=False)

    res = summarize(tr)
    ver = judge(res)
    res.to_csv(f"{OUT}/rows.csv", index=False)

    # sensitivity (decision-free): censored trades closed at the last available close (B's convention)
    sens = None
    if censored:
        extra = []
        for c in censored:
            ex, d, entry, dist = c["last_close"], c["dir"], c["entry"], (c["entry"] - c["stop"]) * c["dir"]
            gross = (ex - entry) * d
            cn = (2 * FEE_BP + SLIP_IN_N) * entry / 1e4 + SLIP_OUT_N * ex / 1e4
            cs = (2 * FEE_BP + SLIP_IN_S) * entry / 1e4 + SLIP_OUT_S * ex / 1e4
            extra.append(dict(coin=c["coin"], universe=c["universe"], pattern=c["pattern"], tf=c["tf"], dir=d,
                              sig_time=c["sig_time"], entry_time=c["entry_time"], exit_time=c["last_time"],
                              entry=entry, stop=c["stop"], target=c["target"], exit=ex, exit_type="data_end",
                              bars=c["bars_available"], dist=dist, R_gross=gross / dist,
                              R_normal=(gross - cn) / dist, R_stress=(gross - cs) / dist))
        tx = pd.DataFrame(extra)
        tx["week"] = week_key(tx["entry_time"].values)
        tx["year"] = pd.to_datetime(tx["entry_time"], unit="ms", utc=True).dt.year
        t2 = pd.concat([tr, tx], ignore_index=True)
        r2 = summarize(t2)
        v2 = judge(r2)
        keys = {(c["pattern"], c["tf"], c["universe"]) for c in censored}
        sens = dict(
            rows=[r for r in r2.to_dict("records") if (r["pattern"], r["tf"], r["universe"]) in keys],
            verdicts_same=bool((v2.verdict.values == ver.verdict.values).all()),
            censored_R_normal_if_closed_at_last_close=[float(x) for x in tx.R_normal])

    diag = {}
    for p in PATTERNS:
        for tf in TFS:
            for uni in UNIVERSES:
                s = tr[(tr.pattern == p) & (tr.tf == tf) & (tr.universe == uni)]
                d = {nm: dict(n=int((s.dir == dd).sum()),
                              meanR_normal=float(s[s.dir == dd].R_normal.mean()) if (s.dir == dd).any() else None)
                     for dd, nm in ((1, "long"), (-1, "short"))}
                d["yearly"] = {int(y): dict(n=int(len(g)), meanR_normal=round(float(g.R_normal.mean()), 4))
                               for y, g in s.groupby("year")}
                d["exit_mix"] = {k: int(v) for k, v in s.exit_type.value_counts().items()}
                d["avg_bars"] = float(s.bars.mean()) if len(s) else None
                d["median_stop_dist_pct"] = float((s.dist / s.entry).median() * 100) if len(s) else None
                d["mean_cost_R_normal"] = float((s.R_gross - s.R_normal).mean()) if len(s) else None
                d["exits_after_period_end"] = int((s.exit_time >= T1).sum())
                d["counters"] = counters[f"{p}|{tf}|{uni}"]
                diag[f"{p}|{tf}|{uni}"] = d

    with open(f"{OUT}/results.json", "w") as fh:
        json.dump(dict(rows=res.to_dict("records"), verdicts=ver.to_dict("records"), diagnostics=diag,
                       censored_dropped=censored, sensitivity_censored_closed_at_last_close=sens,
                       days_dropped_1D=days_dropped), fh, indent=1, default=float)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    lines = []
    cols = ["pattern", "tf", "universe", "n", "meanR_normal", "meanR_stress", "win_rate", "bonf_lo", "p2_5",
            "p97_5", "n_weeks", "stress_bonf_lo"]
    lines.append(res[cols].round(4).to_string(index=False))
    lines.append("")
    lines.append(ver.to_string(index=False))
    lines.append("")
    lines.append(f"censored (open at data end, dropped): {len(censored)}")
    for c in censored:
        lines.append(f"  {c['coin']} {c['pattern']} {c['tf']} dir={c['dir']:+d} entry="
                     f"{pd.to_datetime(c['entry_time'], unit='ms')} bars_available={c['bars_available']}")
    if sens:
        lines.append(f"sensitivity (censored closed at last close): verdicts_same={sens['verdicts_same']}")
        for r in sens["rows"]:
            lines.append(f"  {r['pattern']}|{r['tf']}|{r['universe']} n={r['n']} Rn={r['meanR_normal']:.4f} "
                         f"Rs={r['meanR_stress']:.4f} bonf={r['bonf_lo']:.4f}")
    lines.append(f"1D days dropped (incomplete): {days_dropped}")
    txt = "\n".join(lines)
    print(txt)
    with open(f"{OUT}/report.txt", "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
