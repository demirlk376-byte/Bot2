"""
research_intraday.py

Backtest: Setup Library — Clean BOS + Retest + Liquidity Sweep + Reclaim.

Based on setup_library.md specification.  Tests whether structural break-of-
structure (BOS) followed by a retest has a real edge on BTCUSDT 1M data
(May 2025 – Apr 2026), across three entry timeframes (1H / 15M / 5M).

Key rules implemented:
  - Swing detection: N-bar confirmation on struct TF (no lookahead)
  - Bullish BOS: 5M/15M/1H body close above last confirmed swing high
  - WATCH: wait for price to return to BOS level ± zone_pct
  - EXECUTE: at retest, optionally require pin bar / engulfing trigger
  - SL: sl_atr_mult × ATR(14) on entry TF
  - TP: rr × SL  (1:2 or 1:3)
  - Trend filter: 1H/4H EMA50 direction (from spec: "trending regime")

Liquidity Sweep + Reclaim:
  - Wick pierces structural swing H/L, close reclaims inside → entry
  - (This is Setup 3 from spec, equivalent to SFP but on confirmed swings)

Run: python research_intraday.py
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import atr, ema as ema_fn

COST  = 0.0002          # maker round trip (0.04%)
BAL   = 10_000.0
RISK  = 0.02            # 2% per trade (conservative vs 3% for BB)
SPLIT = pd.Timestamp("2026-01-01")
MH    = 48              # max hold bars on entry TF


# ── Data ──────────────────────────────────────────────────────────────────────

def load_btc():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df = df.rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def rs(df, rule):
    return df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()


# ── Swing detection (no lookahead) ────────────────────────────────────────────

def compute_swings(df, lookback=3):
    """
    At bar i, last_sh[i] / last_sl[i] = most recently CONFIRMED swing H/L.
    Confirmed means: bar at pivot=(i-lookback) has lookback higher bars
    on each side.  Delay = lookback bars (no lookahead).
    """
    n = len(df)
    highs = df["high"].values
    lows  = df["low"].values
    last_sh = np.full(n, np.nan)
    last_sl = np.full(n, np.nan)
    cur_sh = cur_sl = np.nan

    for i in range(lookback, n):
        pivot = i - lookback
        if pivot >= lookback:
            ok_h = all(highs[pivot] >= highs[pivot - k] for k in range(1, lookback + 1)) and \
                   all(highs[pivot] >= highs[pivot + k] for k in range(1, lookback + 1))
            if ok_h:
                cur_sh = highs[pivot]

            ok_l = all(lows[pivot] <= lows[pivot - k] for k in range(1, lookback + 1)) and \
                   all(lows[pivot] <= lows[pivot + k] for k in range(1, lookback + 1))
            if ok_l:
                cur_sl = lows[pivot]

        last_sh[i] = cur_sh
        last_sl[i] = cur_sl

    return last_sh, last_sl


# ── Candle patterns (from candle_pattern_library.md) ─────────────────────────

def bullish_pin(o, h, l, c):
    """Hammer: small body top, long lower wick, bullish close."""
    body = abs(c - o); rng = h - l
    if rng < 1e-9 or body / rng > 0.35:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    return lower_wick > 2 * body and lower_wick > upper_wick and c >= o


def bearish_pin(o, h, l, c):
    """Shooting star: small body bottom, long upper wick, bearish close."""
    body = abs(c - o); rng = h - l
    if rng < 1e-9 or body / rng > 0.35:
        return False
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return upper_wick > 2 * body and upper_wick > lower_wick and c <= o


def bullish_engulf(o0, c0, o1, c1):
    return c0 < o0 and c1 > o1 and o1 <= c0 and c1 >= o0


def bearish_engulf(o0, c0, o1, c1):
    return c0 > o0 and c1 < o1 and o1 >= c0 and c1 <= o0


# ── Core: BOS + Retest ────────────────────────────────────────────────────────

def run_bos_retest(
    df_entry, df_struct, df_trend,
    swing_lb=3, sl_m=2.0, rr=2.0, max_watch=12, zone_pct=0.002,
    trend_filter=True, pattern_filter=False
):
    """
    Clean BOS + Retest (Setup 1 from spec).

    df_entry : timeframe for BOS detection and trade execution
    df_struct: timeframe for swing H/L (one level higher than entry)
    df_trend : timeframe for EMA50 trend direction (highest level)
    """
    sh_s, sl_s = compute_swings(df_struct, lookback=swing_lb)

    ema50 = ema_fn(df_trend["close"], 50)
    trend_dir = np.sign(df_trend["close"].values - ema50.values)

    # Forward-fill higher-TF data onto entry TF (no future information)
    sh_e = pd.Series(sh_s, index=df_struct.index).reindex(df_entry.index, method="ffill").values
    sl_e = pd.Series(sl_s, index=df_struct.index).reindex(df_entry.index, method="ffill").values
    tr_e = pd.Series(trend_dir, index=df_trend.index).reindex(df_entry.index, method="ffill").values

    atr_e = atr(df_entry["high"], df_entry["low"], df_entry["close"], 14).values

    n = len(df_entry)
    c = df_entry["close"].values; h_arr = df_entry["high"].values
    l_arr = df_entry["low"].values; o_arr = df_entry["open"].values

    warmup = 80
    balance = BAL
    state = 0           # 0=idle 1=watch_long 2=watch_short 3=in_trade
    direction = 0
    bos_level = np.nan; bos_bar = 0; hold_bars = 0
    t_entry = t_sl = t_tp = t_qty = np.nan
    trades = []

    for i in range(warmup, n):
        a = atr_e[i]
        if np.isnan(a) or a <= 0:
            continue

        hi = h_arr[i]; lo = l_arr[i]; cl = c[i]; op = o_arr[i]
        cur_sh = sh_e[i]; cur_sl = sl_e[i]; trend = tr_e[i]

        # ── In trade ─────────────────────────────────────────────────────────
        if state == 3:
            ep = None; reason = None
            hold_bars += 1
            if direction == 1:
                if lo <= t_sl and hi >= t_tp:
                    ep, reason = t_sl, "sl"    # conservative: SL first
                elif lo <= t_sl:
                    ep, reason = t_sl, "sl"
                elif hi >= t_tp:
                    ep, reason = t_tp, "tp"
            else:
                if hi >= t_sl and lo <= t_tp:
                    ep, reason = t_sl, "sl"
                elif hi >= t_sl:
                    ep, reason = t_sl, "sl"
                elif lo <= t_tp:
                    ep, reason = t_tp, "tp"
            if ep is None and hold_bars >= MH:
                ep, reason = cl, "mh"
            if ep is not None:
                pnl = direction * (ep - t_entry) * t_qty - (t_entry + ep) * t_qty * COST
                balance += pnl
                trades.append({"ts": df_entry.index[i], "pnl": pnl, "reason": reason})
                state = 0
            continue

        # ── BOS detection ─────────────────────────────────────────────────────
        if state == 0 and i > warmup:
            prev_sh = sh_e[i - 1]; prev_sl = sl_e[i - 1]
            prev_cl = c[i - 1]

            # Bullish BOS: close body crosses above last confirmed struct swing high
            if (not trend_filter or trend >= 0) and \
               not np.isnan(prev_sh) and prev_cl <= prev_sh and cl > prev_sh:
                state = 1; direction = 1
                bos_level = prev_sh; bos_bar = i

            # Bearish BOS
            elif (not trend_filter or trend <= 0) and \
                 not np.isnan(prev_sl) and prev_cl >= prev_sl and cl < prev_sl:
                state = 2; direction = -1
                bos_level = prev_sl; bos_bar = i

        # ── Watch: waiting for retest ─────────────────────────────────────────
        elif state in (1, 2):
            if i - bos_bar > max_watch:
                state = 0
                continue

            tol = zone_pct * bos_level
            prev_op = o_arr[i - 1]; prev_cl = c[i - 1]

            if state == 1:  # long: waiting for pullback to BOS level
                if lo <= bos_level + tol and cl > bos_level - tol:
                    ok = True
                    if pattern_filter:
                        ok = (bullish_pin(op, hi, lo, cl) or
                              bullish_engulf(prev_op, prev_cl, op, cl))
                    if ok:
                        ep = cl; sl_d = sl_m * a
                        t_entry = ep
                        t_sl = ep - sl_d
                        t_tp = ep + rr * sl_d
                        t_qty = min(
                            round((balance * RISK) / max(ep * sl_d / ep, 1e-9), 3),
                            balance * 0.5 / ep
                        )
                        if t_qty >= 0.001:
                            state = 3; direction = 1; hold_bars = 0
                        else:
                            state = 0

            else:  # short: waiting for pullback to BOS level
                if hi >= bos_level - tol and cl < bos_level + tol:
                    ok = True
                    if pattern_filter:
                        ok = (bearish_pin(op, hi, lo, cl) or
                              bearish_engulf(prev_op, prev_cl, op, cl))
                    if ok:
                        ep = cl; sl_d = sl_m * a
                        t_entry = ep
                        t_sl = ep + sl_d
                        t_tp = ep - rr * sl_d
                        t_qty = min(
                            round((balance * RISK) / max(ep * sl_d / ep, 1e-9), 3),
                            balance * 0.5 / ep
                        )
                        if t_qty >= 0.001:
                            state = 3; direction = -1; hold_bars = 0
                        else:
                            state = 0

    return trades


# ── Liquidity Sweep + Reclaim (Setup 3 from spec) ────────────────────────────

def run_sweep_reclaim(
    df_entry, df_struct, df_trend,
    swing_lb=5, sl_m=1.5, rr=2.0, trend_filter=True
):
    """
    Liquidity Sweep + Reclaim (Setup 3).
    Wick pierces confirmed structural swing H/L, bar closes back inside.
    Immediate entry at close.  SL = sl_m × ATR below/above entry.
    """
    sh_s, sl_s = compute_swings(df_struct, lookback=swing_lb)
    ema50 = ema_fn(df_trend["close"], 50)
    trend_dir = np.sign(df_trend["close"].values - ema50.values)

    sh_e = pd.Series(sh_s, index=df_struct.index).reindex(df_entry.index, method="ffill").values
    sl_e = pd.Series(sl_s, index=df_struct.index).reindex(df_entry.index, method="ffill").values
    tr_e = pd.Series(trend_dir, index=df_trend.index).reindex(df_entry.index, method="ffill").values
    atr_e = atr(df_entry["high"], df_entry["low"], df_entry["close"], 14).values

    n = len(df_entry)
    c = df_entry["close"].values; h_arr = df_entry["high"].values
    l_arr = df_entry["low"].values

    warmup = 80; balance = BAL
    state = 0; direction = 0; hold_bars = 0
    t_entry = t_sl = t_tp = t_qty = np.nan
    trades = []

    for i in range(warmup, n):
        a = atr_e[i]
        if np.isnan(a) or a <= 0:
            continue

        hi = h_arr[i]; lo = l_arr[i]; cl = c[i]
        cur_sh = sh_e[i]; cur_sl = sl_e[i]; trend = tr_e[i]

        if state == 1:
            ep = None; reason = None
            hold_bars += 1
            if direction == 1:
                if lo <= t_sl and hi >= t_tp:
                    ep, reason = t_sl, "sl"
                elif lo <= t_sl:
                    ep, reason = t_sl, "sl"
                elif hi >= t_tp:
                    ep, reason = t_tp, "tp"
            else:
                if hi >= t_sl and lo <= t_tp:
                    ep, reason = t_sl, "sl"
                elif hi >= t_sl:
                    ep, reason = t_sl, "sl"
                elif lo <= t_tp:
                    ep, reason = t_tp, "tp"
            if ep is None and hold_bars >= MH:
                ep, reason = cl, "mh"
            if ep is not None:
                pnl = direction * (ep - t_entry) * t_qty - (t_entry + ep) * t_qty * COST
                balance += pnl
                trades.append({"ts": df_entry.index[i], "pnl": pnl, "reason": reason})
                state = 0
            continue

        if state == 0:
            # Bullish sweep: wick below struct swing low, close reclaims above
            if (not trend_filter or trend >= 0) and not np.isnan(cur_sl):
                if lo < cur_sl and cl > cur_sl:
                    ep = cl; sl_d = sl_m * a
                    t_entry = ep; t_sl = ep - sl_d; t_tp = ep + rr * sl_d
                    t_qty = min(round((balance * RISK) / max(ep * sl_d / ep, 1e-9), 3),
                                balance * 0.5 / ep)
                    if t_qty >= 0.001:
                        state = 1; direction = 1; hold_bars = 0
                    continue

            # Bearish sweep: wick above struct swing high, close reclaims below
            if (not trend_filter or trend <= 0) and not np.isnan(cur_sh):
                if hi > cur_sh and cl < cur_sh:
                    ep = cl; sl_d = sl_m * a
                    t_entry = ep; t_sl = ep + sl_d; t_tp = ep - rr * sl_d
                    t_qty = min(round((balance * RISK) / max(ep * sl_d / ep, 1e-9), 3),
                                balance * 0.5 / ep)
                    if t_qty >= 0.001:
                        state = 1; direction = -1; hold_bars = 0

    return trades


# ── Stats ─────────────────────────────────────────────────────────────────────

def stat(tt, label):
    if not tt:
        return f"{label:<62} 0t"
    p  = np.array([t["pnl"] for t in tt])
    wr = (p > 0).mean()
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf  = pos / neg if neg > 0 else float("inf")
    eq  = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd  = ((pk - eq) / pk).max()
    tr  = [t for t in tt if t["ts"] < SPLIT]
    te  = [t for t in tt if t["ts"] >= SPLIT]
    tp_ = np.array([t["pnl"] for t in tr]) if tr else np.array([0.0])
    te_ = np.array([t["pnl"] for t in te]) if te else np.array([0.0])
    return (f"{label:<62} {len(p):>4}t WR{wr:.0%} PF{pf:.2f} "
            f"${p.sum():>+8.0f}({p.sum()/100:>+.1f}%) DD{dd*100:.1f}% "
            f"| TR WR{(tp_>0).mean():.0%} ${tp_.sum():>+7.0f}"
            f"| TE WR{(te_>0).mean():.0%} ${te_.sum():>+7.0f}")


def main():
    print("Loading data…")
    df_1m  = load_btc()
    df_5m  = rs(df_1m,  "5min")
    df_15m = rs(df_1m, "15min")
    df_1h  = rs(df_1m,   "1h")
    df_4h  = rs(df_1m,   "4h")

    print(f"Range: {df_1m.index[0].date()} → {df_1m.index[-1].date()} | "
          f"5M={len(df_5m)} 15M={len(df_15m)} 1H={len(df_1h)} 4H={len(df_4h)}")
    print("=" * 140)

    # ── Setup 1: Clean BOS + Retest ──────────────────────────────────────────
    print("\n═══ SETUP 1: Clean BOS + Retest ════════════════════════════════════════════")

    print("\n── Entry=1H | Structure=4H swings | SL=2×ATR TP=2:1 ──")
    for label, tf, pf in [
        ("1H BOS, 4H trend filter",    True,  False),
        ("1H BOS, no trend filter",    False, False),
        ("1H BOS, trend + pin bar",    True,  True),
    ]:
        t = run_bos_retest(df_1h, df_4h, df_4h, swing_lb=3, sl_m=2.0, rr=2.0,
                           max_watch=12, zone_pct=0.002, trend_filter=tf, pattern_filter=pf)
        print(stat(t, f"  {label}"))

    print("\n── Entry=15M | Structure=1H swings | SL=2×ATR TP=2:1 ──")
    for label, tf, pf in [
        ("15M BOS, 1H trend filter",   True,  False),
        ("15M BOS, no trend filter",   False, False),
        ("15M BOS, trend + pin bar",   True,  True),
    ]:
        t = run_bos_retest(df_15m, df_1h, df_1h, swing_lb=3, sl_m=2.0, rr=2.0,
                           max_watch=12, zone_pct=0.002, trend_filter=tf, pattern_filter=pf)
        print(stat(t, f"  {label}"))

    print("\n── Entry=5M | Structure=15M swings | SL=2×ATR TP=2:1 ──")
    for label, tf, pf in [
        ("5M BOS, 1H trend filter",    True,  False),
        ("5M BOS, no trend filter",    False, False),
    ]:
        t = run_bos_retest(df_5m, df_15m, df_1h, swing_lb=3, sl_m=2.0, rr=2.0,
                           max_watch=12, zone_pct=0.002, trend_filter=tf, pattern_filter=pf)
        print(stat(t, f"  {label}"))

    # ── Setup 3: Liquidity Sweep + Reclaim ───────────────────────────────────
    print("\n═══ SETUP 3: Liquidity Sweep + Reclaim (Structural SFP) ════════════════════")
    for entry_label, ent, struct, trend_df in [
        ("1H entry, 4H swings",   df_1h,  df_4h, df_4h),
        ("15M entry, 1H swings",  df_15m, df_1h, df_1h),
        ("5M entry, 15M swings",  df_5m,  df_15m, df_1h),
    ]:
        for label, tf in [("trend filter", True), ("no filter", False)]:
            t = run_sweep_reclaim(ent, struct, trend_df, swing_lb=5, sl_m=1.5,
                                  rr=2.0, trend_filter=tf)
            print(stat(t, f"  {entry_label} / {label}"))

    # ── 1H BOS parameter sweep ───────────────────────────────────────────────
    print("\n═══ 1H BOS parameter sweep (trend_filter=True) ═════════════════════════════")
    best_pnl = -9999; best_cfg = ""
    for sl_m in [1.5, 2.0, 3.0]:
        for rr in [1.5, 2.0, 3.0]:
            for lb in [2, 3, 5]:
                t = run_bos_retest(df_1h, df_4h, df_4h, swing_lb=lb, sl_m=sl_m, rr=rr,
                                   max_watch=12, zone_pct=0.002, trend_filter=True)
                pnl = sum(x["pnl"] for x in t)
                label = f"  SL={sl_m}×ATR TP={rr}:1 swing_lb={lb}"
                line = stat(t, label)
                print(line)
                if pnl > best_pnl:
                    best_pnl = pnl; best_cfg = label

    print(f"\nBest 1H BOS config: {best_cfg} → ${best_pnl:+.0f}")

    # ── Reference ────────────────────────────────────────────────────────────
    print("\n═══ Reference ═══════════════════════════════════════════════════════════════")
    print("  BASELINE 1H BB fade + vol filter + maker + 3% risk:")
    print("  238t WR47% PF1.24 $+2822 (+28.2%) DD10.5% | TR WR47% $+1105 | TE WR47% $+1717")


if __name__ == "__main__":
    main()
