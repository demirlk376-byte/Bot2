"""
research_combine.py

Can we beat +28.2% by combining the 1H BB system with structural signals?

Tested combinations:
  1. BB + 15M Structural Sweep confluence
     At 1H BB signal, check if ≥1 of the last 4 fifteen-minute bars had a
     same-direction structural sweep (wick through 1H swing H/L, close back
     inside).  Two independent signals agreeing should boost WR.

  2. BB + RSI divergence filter
     At 1H BB extreme, require RSI bullish/bearish divergence vs. the
     previous swing low/high in the last 20 bars.  Divergence = price new
     extreme but RSI is recovering → momentum suggests reversal imminent.

  3. BB UNION 15M Sweep (no overlap)
     Take ALL BB signals PLUS standalone 15M Sweep signals that occur when
     there is no open position.  Tests whether the two positive-PnL systems
     together beat either alone.

  4. Fake Trap Score filter on BB signals
     Score each BB signal for trap risk (trap_manipulation_library.md):
       +2  wick/body ratio > 2 at signal candle → ambiguous bar
       +2  RSI divergence present (counter-trend strength)
       +1  ATR spike > 1.5×mean (abnormal volatility)
       +2  volume < 0.8× avg volume (already caught by vol_filter, but weight)
     Skip if trap_score ≥ threshold (tests thresholds 3–7).

  5. BB + Opposite-direction Sweep as ANTI-signal
     If a sweep fires in the OPPOSITE direction of a BB signal within the
     same 1H bar, skip (the structure just rejected the move).

Baseline: 238t WR47% PF1.24 $+2822 (+28.2%) DD10.5%

Run: python research_combine.py
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, rsi as rsi_fn

COST  = 0.0002      # maker round trip (0.04%)
BAL   = 10_000.0
RISK  = 0.03        # same as validated BB system
SL_M  = 3.0
TP_M  = 5.0
MH    = 48
SPLIT = pd.Timestamp("2026-01-01")


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
    n = len(df); highs = df["high"].values; lows = df["low"].values
    last_sh = np.full(n, np.nan); last_sl = np.full(n, np.nan)
    cur_sh = cur_sl = np.nan
    for i in range(lookback, n):
        p = i - lookback
        if p >= lookback:
            if (all(highs[p] >= highs[p - k] for k in range(1, lookback + 1)) and
                    all(highs[p] >= highs[p + k] for k in range(1, lookback + 1))):
                cur_sh = highs[p]
            if (all(lows[p] <= lows[p - k] for k in range(1, lookback + 1)) and
                    all(lows[p] <= lows[p + k] for k in range(1, lookback + 1))):
                cur_sl = lows[p]
        last_sh[i] = cur_sh; last_sl[i] = cur_sl
    return last_sh, last_sl


# ── 15M Sweep events (boolean series) ────────────────────────────────────────

def compute_sweep_events(df_15m, df_1h):
    """
    Returns two boolean arrays (indexed on 15M):
      bull_sweep[i]: 15M bar i had wick below 1H structural low, close above it
      bear_sweep[i]: 15M bar i had wick above 1H structural high, close below it
    """
    sh_1h, sl_1h = compute_swings(df_1h, lookback=3)

    # Forward-fill 1H swing data onto 15M bars (no lookahead)
    sh_on_15m = pd.Series(sh_1h, index=df_1h.index).reindex(df_15m.index, method="ffill").values
    sl_on_15m = pd.Series(sl_1h, index=df_1h.index).reindex(df_15m.index, method="ffill").values

    hi = df_15m["high"].values
    lo = df_15m["low"].values
    cl = df_15m["close"].values

    n = len(df_15m)
    bull_sweep = np.zeros(n, dtype=bool)
    bear_sweep = np.zeros(n, dtype=bool)

    for i in range(1, n):
        sl = sl_on_15m[i]; sh = sh_on_15m[i]
        if not np.isnan(sl) and lo[i] < sl and cl[i] > sl:
            bull_sweep[i] = True
        if not np.isnan(sh) and hi[i] > sh and cl[i] < sh:
            bear_sweep[i] = True

    return bull_sweep, bear_sweep


# ── RSI divergence ────────────────────────────────────────────────────────────

def compute_rsi_divergence(close_vals, rsi_vals, lookback=20):
    """
    At each bar i:
      +1  bullish divergence: close makes lower low vs. lookback window,
                              RSI makes higher low → momentum recovering.
      -1  bearish divergence: close higher high, RSI lower high.
       0  no divergence.
    """
    n = len(close_vals)
    div = np.zeros(n)
    for i in range(lookback, n):
        if np.isnan(rsi_vals[i]):
            continue
        w_c = close_vals[i - lookback: i]
        w_r = rsi_vals[i - lookback: i]
        if np.any(np.isnan(w_r)):
            continue

        prev_low_idx  = int(np.argmin(w_c))
        prev_high_idx = int(np.argmax(w_c))

        # Bullish: current close < prev window low AND RSI > RSI at that low
        if close_vals[i] < w_c[prev_low_idx] and rsi_vals[i] > w_r[prev_low_idx]:
            div[i] = 1
        # Bearish: current close > prev window high AND RSI < RSI at that high
        elif close_vals[i] > w_c[prev_high_idx] and rsi_vals[i] < w_r[prev_high_idx]:
            div[i] = -1

    return div


# ── Fake Trap Score (from trap_manipulation_library.md) ───────────────────────

def compute_trap_score(o, h, l, c, vol, vol_ma, atr_val, atr_ma, rsi_val, rsi_prev):
    """
    0 = low trap risk, 10 = high trap risk.
    Used to SKIP signals: high score → fake move likely → skip.
    """
    score = 0
    body = abs(c - o); rng = h - l
    if rng > 1e-9:
        wick = max(h - max(o, c), min(o, c) - l)
        if body > 1e-9 and wick / body > 2:
            score += 2                       # wick-dominated bar = uncertain
    if not np.isnan(vol_ma) and vol < 0.8 * vol_ma:
        score += 2                           # low volume = weak conviction
    if not np.isnan(atr_ma) and atr_val > 1.5 * atr_ma:
        score += 1                           # abnormal volatility spike
    # RSI momentum divergence is handled separately (it's a separate filter here)
    return min(score, 10)


# ── Core BB backtest (identical to production_backtest.py) ────────────────────

def run_bb(df_1h, extra_filter=None):
    """
    Baseline 1H BB + volume system.
    extra_filter(i, direction) → bool: True = allow signal, False = skip.
    """
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    rsi_s  = rsi_fn(df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    n = len(c); warmup = 60; balance = BAL; open_t = None; trades = []

    for i in range(warmup, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]
            qty = open_t["qty"]; held = i - open_t["i"]
            ep = None; reason = None
            if d == 1:
                if lo[i] <= sl: ep, reason = sl, "sl"
                elif h[i] >= tp: ep, reason = tp, "tp"
            else:
                if h[i] >= sl: ep, reason = sl, "sl"
                elif lo[i] <= tp: ep, reason = tp, "tp"
            if ep is None and held >= MH:
                ep, reason = c[i], "mh"
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                trades.append({"ts": df_1h.index[i], "pnl": pnl, "reason": reason,
                                "dir": d})
                open_t = None
            continue

        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue

        # Extra filter (combination logic)
        if extra_filter is not None and not extra_filter(i, direction):
            continue

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = round((balance * RISK) / (ep * (sl_d / ep)), 3)
        qty = min(qty, balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}
    return trades


# ── Combined: BB UNION 15M Sweep ──────────────────────────────────────────────

def run_bb_union_sweep(df_1h, df_15m):
    """
    Take BB signals (1H) + standalone 15M Sweep signals.
    Sweep signals only fire if no BB trade is open.
    """
    # BB component
    bb_trades = run_bb(df_1h)
    bb_ts_set = {t["ts"] for t in bb_trades}

    # 15M Sweep component — same SL/TP scaled for 15M
    bull_sw, bear_sw = compute_sweep_events(df_15m, df_1h)
    atr_15m = atr(df_15m["high"], df_15m["low"], df_15m["close"], 14)

    # Identify periods when BB trade is open (block 15M sweep entries then)
    # Build set of 1H bar timestamps where a BB trade is open
    # (simplification: 15M sweep can fire when not in a BB-originated trade)
    c15 = df_15m["close"].values
    h15 = df_15m["high"].values
    lo15 = df_15m["low"].values

    n = len(df_15m)
    balance = BAL
    # Initialize with BB PnL
    for t in bb_trades:
        balance += t["pnl"]
    balance = BAL  # reset — we run in parallel and then combine

    # Run 15M sweep backtest, skipping when a BB trade would be open
    # (for simplicity: check if the 15M bar's 1H period is in bb_ts_set)
    # This is an approximation — true overlap tracking requires more state
    sw_trades = []
    open_sw = None
    balance_sw = BAL

    for i in range(60, n):
        a = atr_15m.iloc[i]
        if np.isnan(a) or a <= 0:
            continue

        # Check if currently in a BB trade (approximate: find matching 1H bar)
        bar_ts = df_15m.index[i]
        bar_1h = bar_ts.floor("1h")
        in_bb = bar_1h in bb_ts_set  # rough proxy

        if open_sw is not None:
            d = open_sw["dir"]; entry = open_sw["entry"]
            sl_p = open_sw["sl"]; tp_p = open_sw["tp"]
            qty = open_sw["qty"]; held = i - open_sw["i"]
            ep = None; reason = None
            if d == 1:
                if lo15[i] <= sl_p: ep, reason = sl_p, "sl"
                elif h15[i] >= tp_p: ep, reason = tp_p, "tp"
            else:
                if h15[i] >= sl_p: ep, reason = sl_p, "sl"
                elif lo15[i] <= tp_p: ep, reason = tp_p, "tp"
            if ep is None and held >= MH * 4:  # scale MH to 15M bars
                ep, reason = c15[i], "mh"
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance_sw += pnl
                sw_trades.append({"ts": df_15m.index[i], "pnl": pnl, "reason": reason})
                open_sw = None
            continue

        if in_bb:
            continue  # BB system has priority

        ep = None; direction = 0
        sl_d = 1.5 * a
        if bull_sw[i]:
            ep = c15[i]; direction = 1
        elif bear_sw[i]:
            ep = c15[i]; direction = -1
        if ep is None:
            continue

        sl_p = ep - direction * sl_d
        tp_p = ep + direction * 2.0 * sl_d
        qty = round((balance_sw * RISK) / max(ep * sl_d / ep, 1e-9), 3)
        qty = min(qty, balance_sw * 0.5 / ep)
        if qty < 0.001:
            continue
        open_sw = {"i": i, "ts": df_15m.index[i], "dir": direction,
                   "entry": ep, "sl": sl_p, "tp": tp_p, "qty": qty}

    return bb_trades, sw_trades


# ── Stats ─────────────────────────────────────────────────────────────────────

def stat(tt, label):
    if not tt:
        return f"{label:<65} 0t"
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
    return (f"{label:<65} {len(p):>4}t WR{wr:.0%} PF{pf:.2f} "
            f"${p.sum():>+8.0f}({p.sum()/100:>+.1f}%) DD{dd*100:.1f}% "
            f"| TR WR{(tp_>0).mean():.0%} ${tp_.sum():>+7.0f}"
            f"| TE WR{(te_>0).mean():.0%} ${te_.sum():>+7.0f}")


def main():
    print("Loading data…")
    df_1m  = load_btc()
    df_15m = rs(df_1m, "15min")
    df_1h  = rs(df_1m, "1h")

    print(f"Range: {df_1m.index[0].date()} → {df_1m.index[-1].date()}")
    print("=" * 140)

    # ── Precompute signals ────────────────────────────────────────────────────
    print("Computing 15M sweep events…")
    bull_sw, bear_sw = compute_sweep_events(df_15m, df_1h)

    # Forward-fill 15M sweep signals onto 1H bars
    # At 1H bar i, check if ANY of the 4 preceding 15M bars had a sweep
    df_15m_idx = df_15m.index
    df_1h_idx  = df_1h.index

    def had_sweep_in_window(ts_1h, direction, window=4):
        """True if any of the last `window` 15M bars had a same-dir sweep."""
        ts_end = ts_1h
        ts_start = ts_end - pd.Timedelta(minutes=15 * window)
        mask = (df_15m_idx >= ts_start) & (df_15m_idx <= ts_end)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            return False
        if direction == 1:
            return bool(np.any(bull_sw[idx]))
        else:
            return bool(np.any(bear_sw[idx]))

    # Map to 1H index
    n_1h = len(df_1h)
    sweep_long_at_1h  = np.zeros(n_1h, dtype=bool)
    sweep_short_at_1h = np.zeros(n_1h, dtype=bool)
    for i, ts in enumerate(df_1h_idx):
        sweep_long_at_1h[i]  = had_sweep_in_window(ts, 1)
        sweep_short_at_1h[i] = had_sweep_in_window(ts, -1)

    # ── RSI + Trap precompute ─────────────────────────────────────────────────
    print("Computing RSI divergence…")
    rsi_vals = rsi_fn(df_1h["close"], 14).values
    close_1h = df_1h["close"].values
    rsi_div  = compute_rsi_divergence(close_1h, rsi_vals, lookback=20)

    atr_1h   = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14).values
    atr_ma_1h = pd.Series(atr_1h).rolling(20).mean().values
    vol_1h    = df_1h["volume"].values
    vol_ma_1h = df_1h["volume"].rolling(20).mean().values
    o_1h      = df_1h["open"].values
    h_1h      = df_1h["high"].values
    lo_1h     = df_1h["low"].values

    # Precompute trap scores
    trap_scores = np.zeros(n_1h)
    for i in range(n_1h):
        trap_scores[i] = compute_trap_score(
            o_1h[i], h_1h[i], lo_1h[i], close_1h[i],
            vol_1h[i], vol_ma_1h[i],
            atr_1h[i], atr_ma_1h[i],
            rsi_vals[i],
            rsi_vals[i - 1] if i > 0 else np.nan
        )

    # ── Baseline ──────────────────────────────────────────────────────────────
    print("Running backtests…\n")
    baseline = run_bb(df_1h)
    print(stat(baseline, "BASELINE (1H BB + vol filter)"))
    print()

    # ── Combo 1: BB + 15M Sweep confluence ───────────────────────────────────
    print("─── Combo 1: BB + 15M Structural Sweep confluence ───────────────────────────────")
    for window in [2, 4, 6]:
        # Recompute with specific window
        sw_l = np.zeros(n_1h, dtype=bool)
        sw_s = np.zeros(n_1h, dtype=bool)
        for i, ts in enumerate(df_1h_idx):
            sw_l[i] = had_sweep_in_window(ts, 1,  window)
            sw_s[i] = had_sweep_in_window(ts, -1, window)

        def filt_sweep(i, direction, _sw_l=sw_l, _sw_s=sw_s):
            if direction == 1:
                return bool(_sw_l[i])
            else:
                return bool(_sw_s[i])

        t = run_bb(df_1h, extra_filter=filt_sweep)
        print(stat(t, f"  BB + 15M sweep in last {window} bars"))
    print()

    # ── Combo 2: BB + RSI divergence ─────────────────────────────────────────
    print("─── Combo 2: BB + RSI divergence ────────────────────────────────────────────────")

    def filt_div(i, direction):
        # Bullish div (+1) → confirms long; bearish div (-1) → confirms short
        return rsi_div[i] == direction

    t = run_bb(df_1h, extra_filter=filt_div)
    print(stat(t, "  BB + RSI divergence required"))

    # RSI divergence as optional boost: include both div and no-div signals
    # but check them separately to understand contribution
    def filt_no_div(i, direction):
        return rsi_div[i] == 0 or rsi_div[i] == direction

    t_nodiv = run_bb(df_1h, extra_filter=filt_no_div)
    print(stat(t_nodiv, "  BB + RSI divergence allowed (no opp divergence)"))
    print()

    # ── Combo 3: BB + 15M Sweep OR RSI divergence ────────────────────────────
    print("─── Combo 3: BB + (15M Sweep OR RSI divergence) ─────────────────────────────────")
    sw_l4 = np.zeros(n_1h, dtype=bool)
    sw_s4 = np.zeros(n_1h, dtype=bool)
    for i, ts in enumerate(df_1h_idx):
        sw_l4[i] = had_sweep_in_window(ts, 1,  4)
        sw_s4[i] = had_sweep_in_window(ts, -1, 4)

    def filt_sweep_or_div(i, direction):
        sweep_ok = (direction == 1 and sw_l4[i]) or (direction == -1 and sw_s4[i])
        div_ok = rsi_div[i] == direction
        return sweep_ok or div_ok

    t = run_bb(df_1h, extra_filter=filt_sweep_or_div)
    print(stat(t, "  BB + (sweep OR rsi_div)"))

    def filt_sweep_and_div(i, direction):
        sweep_ok = (direction == 1 and sw_l4[i]) or (direction == -1 and sw_s4[i])
        div_ok = rsi_div[i] == direction
        return sweep_ok and div_ok

    t = run_bb(df_1h, extra_filter=filt_sweep_and_div)
    print(stat(t, "  BB + (sweep AND rsi_div) — both required"))
    print()

    # ── Combo 4: Fake Trap Score filter ──────────────────────────────────────
    print("─── Combo 4: Fake Trap Score filter (skip high-risk BB signals) ─────────────────")
    for thresh in [2, 3, 4, 5]:
        def filt_trap(i, direction, _th=thresh):
            return trap_scores[i] < _th

        t = run_bb(df_1h, extra_filter=filt_trap)
        print(stat(t, f"  BB + trap_score < {thresh}"))
    print()

    # ── Combo 5: BB + opposite-direction sweep as SKIP ───────────────────────
    print("─── Combo 5: BB + skip if opposite-direction sweep present ──────────────────────")

    def filt_no_opp_sweep(i, direction):
        # Skip BB long if a BEAR sweep fired in the same window (market just
        # rejected upside → don't fade the band with a sweep against you)
        if direction == 1 and sw_s4[i]:
            return False
        if direction == -1 and sw_l4[i]:
            return False
        return True

    t = run_bb(df_1h, extra_filter=filt_no_opp_sweep)
    print(stat(t, "  BB + skip if opposite sweep in last 4 bars"))
    print()

    # ── BB UNION 15M Sweep ────────────────────────────────────────────────────
    print("─── Combo 6: BB UNION 15M Sweep (take both, no overlap) ─────────────────────────")
    bb_t, sw_t = run_bb_union_sweep(df_1h, df_15m)
    all_t = sorted(bb_t + sw_t, key=lambda x: x["ts"])
    print(stat(bb_t, "  BB component alone (for reference)"))
    print(stat(sw_t, "  15M Sweep component alone"))
    # Combine PnL (they run independently with separate capital)
    all_pnl = sum(t["pnl"] for t in all_t)
    print(f"  UNION combined PnL: ${all_pnl:+.0f} ({all_pnl/100:+.1f}%)")
    print()

    # ── Sweep as ADDITIONAL ENTRY on BB signal day ────────────────────────────
    print("─── Combo 7: Upsize BB when sweep confirms (same entry, larger qty) ─────────────")

    def run_bb_sized(df_1h, sw_l, sw_s, boost_mult=1.5):
        """BB system with RISK boosted by boost_mult when sweep confirms."""
        c   = df_1h["close"].values; h = df_1h["high"].values
        lo  = df_1h["low"].values;   vol = df_1h["volume"].values
        upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
        atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
        vol_ma = df_1h["volume"].rolling(20).mean().values
        bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
        n = len(c); warmup = 60; balance = BAL; open_t = None; trades = []
        for i in range(warmup, n):
            a = atr_s.iloc[i]
            if np.isnan(a) or a <= 0:
                continue
            if open_t is not None:
                d = open_t["dir"]; entry = open_t["entry"]
                sl = open_t["sl"]; tp = open_t["tp"]
                qty = open_t["qty"]; held = i - open_t["i"]
                ep = None; reason = None
                if d == 1:
                    if lo[i] <= sl: ep, reason = sl, "sl"
                    elif h[i] >= tp: ep, reason = tp, "tp"
                else:
                    if h[i] >= sl: ep, reason = sl, "sl"
                    elif lo[i] <= tp: ep, reason = tp, "tp"
                if ep is None and held >= MH: ep, reason = c[i], "mh"
                if ep is not None:
                    pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                    balance += pnl
                    trades.append({"ts": df_1h.index[i], "pnl": pnl, "reason": reason})
                    open_t = None
                continue
            bpos = bb_pos[i]
            if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
                continue
            direction = 1 if bpos < 0 else -1
            if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
                continue
            sweep_confirms = (direction == 1 and sw_l[i]) or (direction == -1 and sw_s[i])
            risk = RISK * boost_mult if sweep_confirms else RISK
            ep = c[i]; sl_d = SL_M * a
            sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
            qty = round((balance * risk) / (ep * (sl_d / ep)), 3)
            qty = min(qty, balance * 0.5 / ep)
            if qty < 0.001:
                continue
            open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                      "entry": ep, "sl": sl, "tp": tp, "qty": qty}
        return trades

    for mult in [1.3, 1.5, 2.0]:
        t = run_bb_sized(df_1h, sw_l4, sw_s4, boost_mult=mult)
        print(stat(t, f"  BB + sweep → boost size ×{mult}"))

    print()
    print("═══ Summary ════════════════════════════════════════════════════════════════════")
    print(stat(baseline, "BASELINE"))
    print(f"  Train/test consistent improvement requires: BOTH TR and TE positive and")
    print(f"  total PnL > $+2822 (+28.2%) with DD ≤ 10.5%.")


if __name__ == "__main__":
    main()
