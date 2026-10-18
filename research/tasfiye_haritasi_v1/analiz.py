#!/usr/bin/env python3
"""Tasfiye haritasi v1 (liquidation magnet) -- implementation B.

Implements research/tasfiye_haritasi_v1/ON_KAYIT.md exactly (no tuning).
Style: plain Python list-of-clusters per coin, literal loop per 4h bar.

Run:  python3 -I analiz.py [--zero-oi-raw]
Outputs (only into this script's directory):
  trades_B.csv, sonuc_B.json   (or *_zeroraw.* with --zero-oi-raw sensitivity flag)
"""
import os
import sys
import json
import math
from multiprocessing import Pool

import numpy as np
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
PRICE_DIR = "/home/user/sweep/research_data/h4_kirilim_v6/veri"
MET_DIR = "/home/user/sweep/research_data/kalabalik/veri"

ESKI12 = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
YENI26 = ("LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV "
          "HBAR VET APT ARB OP INJ SUI").split()

H1 = 3600 * 1000
H4 = 4 * H1
DAY = 24 * H1

# --- frozen model constants (ON_KAYIT) ---
TIERS = [(10.0, 0.40), (25.0, 0.40), (50.0, 0.20)]
BAND_LO, BAND_HI = 0.02, 0.10
IMB = 0.5
GATE_Q = 80.0
GATE_WIN = 90 * DAY
GATE_MIN_HIST = 60 * DAY
MAX_AGE = 30 * DAY
ATR_N = 14
STOP_ATR = 1.5
MIN_RR = 1.0
HOLD_BARS = 18

PERIOD_START = int(pd.Timestamp("2022-03-01", tz="UTC").value // 10**6)
PERIOD_END = int(pd.Timestamp("2025-08-08", tz="UTC").value // 10**6)

FEE_BP = 1.0
SLIP_IN_N, SLIP_OUT_N = 15.85, 0.24
SLIP_IN_S, SLIP_OUT_S = 31.7, 0.48

NBOOT = 10000
SEED = 20261018

ZERO_OI_RAW = "--zero-oi-raw" in sys.argv   # sensitivity only: keep OI==0 rows as real values


# ----------------------------------------------------------------------------- data
def load_price(coin):
    p = pd.read_csv(os.path.join(PRICE_DIR, f"{coin}_4h.csv"))
    p = p.drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
    return (p.open_time.astype(np.int64).tolist(), p.open.astype(float).tolist(), p.high.astype(float).tolist(),
            p.low.astype(float).tolist(), p.close.astype(float).tolist())


def load_metrics(coin):
    path = os.path.join(MET_DIR, f"{coin}_metrics_1h.csv.gz")
    if not os.path.exists(path):
        return None
    m = pd.read_csv(path)
    m = m.drop_duplicates("t_kapanis", keep="last").sort_values("t_kapanis")
    oi = {}
    tk = {}
    n_zero = 0
    for t, v, r in zip(m.t_kapanis.astype(np.int64).tolist(), m.sum_open_interest.tolist(),
                       m.sum_taker_long_short_vol_ratio.tolist()):
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            if v > 0 or ZERO_OI_RAW:
                oi[t] = float(v)
            else:
                n_zero += 1          # OI == 0 is a Binance data hole -> treated as missing
        if r is not None and not (isinstance(r, float) and math.isnan(r)):
            tk[t] = float(r)
    return oi, tk, n_zero


# ----------------------------------------------------------------------------- per-coin simulation
def run_coin(coin):
    met = load_metrics(coin)
    if met is None:
        return dict(coin=coin, skipped="no metrics")
    OI, TK, n_zero = met
    ot, op, hi, lo, cl = load_price(coin)
    n = len(ot)

    # true range and ATR14 (simple mean of TR, incl. the signal bar)
    tr = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = hi[i] - lo[i]
        else:
            tr[i] = max(hi[i] - lo[i], abs(hi[i] - cl[i - 1]), abs(lo[i] - cl[i - 1]))

    clusters = []          # each cluster: [side, level, mass_usdt, t_created]; side 'L' long-liq below, 'S' short-liq above
    m_hist_t = []          # past (S_up + L_down) series at bar closes
    m_hist_v = []
    win_lo = 0             # pointer into m_hist for the 90-day window
    map_start = None       # close time of the first bar with a valid OI update
    busy_until = -1        # bar index of the last exit (new signals allowed at index >= busy_until)

    trades = []
    diag = dict(coin=coin, n_zero_oi=n_zero, bars_loop=0, bars_upd=0, bars_noupd=0, bars_pos=0, bars_neg=0,
                bars_r_missing=0, bars_r_partial=0, gate_eval=0, gate_pass=0, sig_long=0, sig_short=0,
                sig_in_period=0, skip_busy=0, skip_rr=0, skip_wrong_side=0, skip_noatr=0, skip_nonext=0,
                wipes=0)
    mass_ratio = []        # total map mass / (OI * close) at bar close, sampled where OI_close exists
    n_clusters = []
    band_share = []

    for i in range(n):
        T = ot[i]
        Tc = T + H4
        if Tc >= PERIOD_END + H4:      # no further entry can fall inside the period
            break
        h = hi[i]
        l = lo[i]
        c = cl[i]

        # ---- 1) delete clusters touched by this bar
        if clusters:
            keep = []
            for k in clusters:
                if k[0] == 'L' and l <= k[1]:
                    continue
                if k[0] == 'S' and h >= k[1]:
                    continue
                keep.append(k)
            clusters = keep

        # ---- 2) apply this bar's dOI
        oi0 = OI.get(T)
        oi1 = OI.get(Tc)
        if oi0 is not None and oi1 is not None:
            if map_start is None:
                map_start = Tc
            diag["bars_upd"] += 1
            d_oi = oi1 - oi0
            P = (h + l + c) / 3.0
            if d_oi > 0:
                diag["bars_pos"] += 1
                rs = [TK[t] for t in (T + H1, T + 2 * H1, T + 3 * H1, T + 4 * H1) if t in TK]
                if len(rs) == 0:
                    r = 1.0
                    diag["bars_r_missing"] += 1
                else:
                    r = sum(rs) / len(rs)
                    if len(rs) < 4:
                        diag["bars_r_partial"] += 1
                long_share = r / (1.0 + r)
                base = d_oi * P
                for lev, w in TIERS:
                    clusters.append(['L', P * (1.0 - 1.0 / lev), base * long_share * w, Tc])
                    clusters.append(['S', P * (1.0 + 1.0 / lev), base * (1.0 - long_share) * w, Tc])
            elif d_oi < 0:
                diag["bars_neg"] += 1
                red = -d_oi * P
                tot = 0.0
                for k in clusters:
                    tot += k[2]
                if tot > 0:
                    f = 1.0 - red / tot
                    if f <= 0:
                        clusters = []
                        diag["wipes"] += 1
                    else:
                        for k in clusters:
                            k[2] = k[2] * f
        else:
            if map_start is not None:
                diag["bars_noupd"] += 1

        # ---- 3) age-out (> 30 days)
        if clusters:
            keep = []
            for k in clusters:
                if Tc - k[3] > MAX_AGE:
                    continue
                keep.append(k)
            clusters = keep

        if map_start is None:
            continue
        diag["bars_loop"] += 1

        # ---- 4) signal at the bar close
        s_up = 0.0
        s_up_w = 0.0
        l_dn = 0.0
        l_dn_w = 0.0
        tot_mass = 0.0
        for k in clusters:
            tot_mass += k[2]
            if k[0] == 'S' and k[1] > c:
                dist = (k[1] - c) / c
                if BAND_LO <= dist <= BAND_HI:
                    s_up += k[2]
                    s_up_w += k[2] * k[1]
            elif k[0] == 'L' and k[1] < c:
                dist = (c - k[1]) / c
                if BAND_LO <= dist <= BAND_HI:
                    l_dn += k[2]
                    l_dn_w += k[2] * k[1]
        M = s_up + l_dn

        # map sanity samples
        if oi1 is not None and oi1 > 0:
            mass_ratio.append(tot_mass / (oi1 * c))
        n_clusters.append(len(clusters))
        if tot_mass > 0:
            band_share.append(M / tot_mass)

        # 90-day gate on PAST values only
        while win_lo < len(m_hist_t) and m_hist_t[win_lo] < Tc - GATE_WIN:
            win_lo += 1
        signal = 0
        q80 = float("nan")
        I = float("nan")
        if (Tc - map_start) >= GATE_MIN_HIST and len(m_hist_t) - win_lo > 0:
            diag["gate_eval"] += 1
            q80 = float(np.percentile(m_hist_v[win_lo:], GATE_Q))
            if M > 0 and M >= q80:
                diag["gate_pass"] += 1
                I = (s_up - l_dn) / M
                if I >= IMB:
                    signal = 1
                    diag["sig_long"] += 1
                elif I <= -IMB:
                    signal = -1
                    diag["sig_short"] += 1
        m_hist_t.append(Tc)
        m_hist_v.append(M)

        if signal == 0:
            continue
        if i + 1 >= n:
            diag["skip_nonext"] += 1
            continue
        e_t = ot[i + 1]
        if not (PERIOD_START <= e_t < PERIOD_END):
            continue
        diag["sig_in_period"] += 1
        if i < busy_until:
            diag["skip_busy"] += 1
            continue
        if i < ATR_N - 1:
            diag["skip_noatr"] += 1
            continue
        atr = sum(tr[i - ATR_N + 1:i + 1]) / ATR_N
        entry = op[i + 1]
        if signal == 1:
            target = s_up_w / s_up
            stop = entry - STOP_ATR * atr
        else:
            target = l_dn_w / l_dn
            stop = entry + STOP_ATR * atr
        risk = abs(entry - stop)
        if risk <= 0:
            diag["skip_rr"] += 1
            continue
        rr = (target - entry) * signal / risk      # signed: target on the wrong side of entry -> negative -> skip
        if rr < MIN_RR:
            if rr <= 0:
                diag["skip_wrong_side"] += 1
            else:
                diag["skip_rr"] += 1
            continue

        # ---- trade simulation from the entry bar
        ex = None
        reason = None
        j_exit = None
        for j in range(i + 1, min(i + 1 + HOLD_BARS, n)):
            if j > i + 1:
                o_j = op[j]
                if signal == 1:
                    if o_j <= stop:
                        ex, reason, j_exit = o_j, "STOP_GAP", j
                        break
                    if o_j >= target:
                        ex, reason, j_exit = o_j, "TARGET_GAP", j
                        break
                else:
                    if o_j >= stop:
                        ex, reason, j_exit = o_j, "STOP_GAP", j
                        break
                    if o_j <= target:
                        ex, reason, j_exit = o_j, "TARGET_GAP", j
                        break
            if signal == 1:
                hit_s = lo[j] <= stop
                hit_t = hi[j] >= target
            else:
                hit_s = hi[j] >= stop
                hit_t = lo[j] <= target
            if hit_s:
                ex, reason, j_exit = stop, "STOP", j
                break
            if hit_t:
                ex, reason, j_exit = target, "TARGET", j
                break
            if j - i == HOLD_BARS:
                ex, reason, j_exit = cl[j], "TIME", j
                break
        if ex is None:
            j_exit = min(i + HOLD_BARS, n - 1)
            ex, reason = cl[j_exit], "END"
        busy_until = j_exit

        gross = (ex - entry) * signal
        cost_n = (2 * FEE_BP + SLIP_IN_N) * entry / 1e4 + SLIP_OUT_N * ex / 1e4
        cost_s = (2 * FEE_BP + SLIP_IN_S) * entry / 1e4 + SLIP_OUT_S * ex / 1e4
        trades.append(dict(
            coin=coin, dir=signal, signal_time=Tc, entry_time=e_t, exit_time=ot[j_exit],
            entry=entry, stop=stop, target=target, exit=ex, exit_reason=reason, bars_held=j_exit - i,
            atr=atr, sig_close=c, I=I, S_up=s_up, L_down=l_dn, M=M, q80=q80, rr=rr,
            target_dist_pct=abs(target - entry) / entry * 100.0, stop_dist_pct=risk / entry * 100.0,
            map_mass=tot_mass, R_gross=gross / risk, R_normal=(gross - cost_n) / risk, R_stress=(gross - cost_s) / risk))

    def q(a, p):
        return float(np.percentile(a, p)) if len(a) else float("nan")
    diag["mass_ratio_p5_50_95"] = [q(mass_ratio, 5), q(mass_ratio, 50), q(mass_ratio, 95)]
    diag["n_clusters_p50_max"] = [q(n_clusters, 50), float(max(n_clusters)) if n_clusters else float("nan")]
    diag["band_share_p50"] = q(band_share, 50)
    diag["map_start"] = pd.to_datetime(map_start, unit="ms", utc=True).strftime("%Y-%m-%d %H:%M") if map_start else None
    return dict(coin=coin, trades=trades, diag=diag)


# ----------------------------------------------------------------------------- bootstrap
def week_key(ms):
    iso = pd.to_datetime(pd.Series(ms), unit="ms", utc=True).dt.isocalendar()
    return (iso["year"].astype(np.int64) * 100 + iso["week"].astype(np.int64)).values


def block_bootstrap(R, wk):
    """ISO-week block bootstrap of the ratio-of-sums mean; fresh default_rng(SEED) per call."""
    if len(R) == 0:
        return dict(p2_5=float("nan"), p97_5=float("nan"), n_weeks=0)
    uw, inv = np.unique(wk, return_inverse=True)
    sR = np.bincount(inv, weights=R)
    sN = np.bincount(inv).astype(float)
    W = len(uw)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, W, size=(NBOOT, W))
    means = sR[idx].sum(axis=1) / sN[idx].sum(axis=1)
    p25, p975 = np.percentile(means, [2.5, 97.5])
    return dict(p2_5=float(p25), p97_5=float(p975), n_weeks=int(W))


def all_months():
    out = []
    t = pd.Timestamp("2022-03-01")
    end = pd.Timestamp("2025-08-08")
    while t < end:
        out.append(t.strftime("%Y-%m"))
        t = t + pd.offsets.MonthBegin(1)
    return out


def summarize(tr, uni):
    s = tr[tr.universe == uni]
    n = len(s)
    bs = block_bootstrap(s.R_normal.values, s.week.values)
    bss = block_bootstrap(s.R_stress.values, s.week.values)
    months = all_months()
    msum = s.groupby("month").R_normal.sum().reindex(months, fill_value=0.0)
    traded = s.groupby("month").size().reindex(months, fill_value=0)
    row = dict(universe=uni, n=int(n),
               meanR_normal=float(s.R_normal.mean()) if n else float("nan"),
               meanR_stress=float(s.R_stress.mean()) if n else float("nan"),
               meanR_gross=float(s.R_gross.mean()) if n else float("nan"),
               p2_5=bs["p2_5"], p97_5=bs["p97_5"], n_weeks=bs["n_weeks"],
               stress_p2_5=bss["p2_5"], stress_p97_5=bss["p97_5"],
               win_rate=float((s.R_normal > 0).mean()) if n else float("nan"),
               pos_month_share=float((msum > 0).mean()),
               pos_month_share_traded=float((msum[traded > 0] > 0).mean()) if (traded > 0).any() else float("nan"),
               n_months=len(months), n_months_traded=int((traded > 0).sum()))
    return row, msum


def main():
    coins = ESKI12 + YENI26
    with Pool(4) as pool:
        res = pool.map(run_coin, coins)
    rows = []
    diags = {}
    skipped = []
    for r in res:
        if "skipped" in r:
            skipped.append(r["coin"])
            continue
        diags[r["coin"]] = r["diag"]
        for t in r["trades"]:
            t["universe"] = "ESKI12" if r["coin"] in ESKI12 else "YENI26"
            rows.append(t)
    tr = pd.DataFrame(rows)
    tr = tr.sort_values(["universe", "entry_time", "coin"]).reset_index(drop=True)
    et = pd.to_datetime(tr.entry_time, unit="ms", utc=True)
    tr["week"] = week_key(tr.entry_time.values)
    tr["month"] = et.dt.strftime("%Y-%m")
    tr["year"] = et.dt.year
    for col in ("signal_time", "entry_time", "exit_time"):
        tr[col + "_utc"] = pd.to_datetime(tr[col], unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M")
    sfx = "_zeroraw" if ZERO_OI_RAW else ""
    tr.to_csv(os.path.join(OUT, f"trades_B{sfx}.csv"), index=False)

    out = dict(rows=[], monthly={}, by_dir={}, by_year={}, exit_mix={}, by_coin={}, dist={}, diag_coins=diags,
               skipped_coins=skipped, settings=dict(zero_oi_raw=ZERO_OI_RAW))
    summ = {}
    for uni in ("ESKI12", "YENI26"):
        row, msum = summarize(tr, uni)
        summ[uni] = row
        out["rows"].append(row)
        out["monthly"][uni] = {k: round(float(v), 3) for k, v in msum.items()}
        s = tr[tr.universe == uni]
        out["by_dir"][uni] = {("LONG" if d == 1 else "SHORT"): dict(n=int(len(g)), meanR_normal=float(g.R_normal.mean()),
                                                                     meanR_stress=float(g.R_stress.mean()),
                                                                     win=float((g.R_normal > 0).mean()))
                              for d, g in s.groupby("dir")}
        out["by_year"][uni] = {int(y): dict(n=int(len(g)), meanR_normal=float(g.R_normal.mean()),
                                            meanR_stress=float(g.R_stress.mean()), sumR_normal=float(g.R_normal.sum()))
                               for y, g in s.groupby("year")}
        out["exit_mix"][uni] = {k: dict(n=int(len(g)), share=float(len(g) / len(s)), meanR_normal=float(g.R_normal.mean()))
                                for k, g in s.groupby("exit_reason")}
        out["by_coin"][uni] = {c: dict(n=int(len(g)), meanR_normal=float(g.R_normal.mean()), sumR_normal=float(g.R_normal.sum()))
                               for c, g in s.groupby("coin")}
        out["dist"][uni] = dict(
            target_dist_pct_p25_50_75=[float(x) for x in np.percentile(s.target_dist_pct, [25, 50, 75])],
            stop_dist_pct_p25_50_75=[float(x) for x in np.percentile(s.stop_dist_pct, [25, 50, 75])],
            rr_p25_50_75=[float(x) for x in np.percentile(s.rr, [25, 50, 75])],
            absI_p50=float(np.percentile(np.abs(s.I), 50)),
            bars_held_mean=float(s.bars_held.mean()),
            gross_meanR=float(s.R_gross.mean()),
            cost_meanR_normal=float((s.R_gross - s.R_normal).mean()))
        dsum = {}
        for c in (ESKI12 if uni == "ESKI12" else YENI26):
            if c not in diags:
                continue
            for k, v in diags[c].items():
                if isinstance(v, int) and not isinstance(v, bool):
                    dsum[k] = dsum.get(k, 0) + v
        out["dist"][uni]["diag_sum"] = dsum

    e = summ["ESKI12"]
    y = summ["YENI26"]
    c1 = bool(e["meanR_normal"] > 0)
    c2 = bool(y["meanR_normal"] > 0 and y["meanR_stress"] > 0)
    c3 = bool(y["p2_5"] > 0)
    c4 = bool(y["n"] >= 100)
    verdict = "TUTTU" if (c1 and c2 and c3 and c4) else "TUTMADI"
    out["verdict"] = dict(verdict=verdict, c1_secim_normal_gt0=c1, c2_sinav_normal_stress_gt0=c2,
                          c3_sinav_p2_5_gt0=c3, c4_sinav_n_ge100=c4)
    with open(os.path.join(OUT, f"sonuc_B{sfx}.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)

    # ---- console report
    print("skipped coins:", skipped)
    for r in out["rows"]:
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}))
    print("verdict:", out["verdict"])
    for uni in ("ESKI12", "YENI26"):
        print("\n==", uni)
        print(" by_dir", json.dumps(out["by_dir"][uni], default=float))
        print(" by_year", json.dumps(out["by_year"][uni], default=float))
        print(" exit_mix", json.dumps(out["exit_mix"][uni], default=float))
        print(" dist", json.dumps(out["dist"][uni], default=float))
        print(" monthly", out["monthly"][uni])
        print(" by_coin", json.dumps({c: [v["n"], round(v["meanR_normal"], 3)] for c, v in out["by_coin"][uni].items()}))
    print("\nper-coin map diag:")
    for c, d in diags.items():
        print(c, d["map_start"], "zeroOI", d["n_zero_oi"], "upd", d["bars_upd"], "noupd", d["bars_noupd"],
              "wipes", d["wipes"], "gate", d["gate_pass"], "/", d["gate_eval"], "L/S", d["sig_long"], d["sig_short"],
              "mass/OI p5/50/95", [round(x, 3) for x in d["mass_ratio_p5_50_95"]],
              "ncl p50/max", d["n_clusters_p50_max"], "band_share", round(d["band_share_p50"], 3))


if __name__ == "__main__":
    main()
