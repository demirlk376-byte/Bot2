"""
Research: test improved EXIT strategies and verify the volume filter result.
Exit improvements:
  E1) Partial TP: take 50% at 2.5xATR (midpoint), let 50% run to 5xATR
  E2) Midband target: close at middle BB band if it crosses before 5xATR TP
  E3) Trailing stop: once 2xATR profit, trail stop at 1xATR profit lock-in
  E4) Tighter max_hold: 36h vs 48h

All tested with and without volume filter.
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")

from indicators import bollinger_bands, rsi, atr, adx


def load_all():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts", "open", "high", "low", "close", "volume",
                      "ct", "qv", "count", "tbv", "tbqv", "ign"]
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df, rule):
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


COST_PER_SIDE = 0.0004
BB_PERIOD = 20; BB_STD = 2.0; RSI_PERIOD = 14; ATR_PERIOD = 14; ADX_PERIOD = 14
SL_MULT = 3.0; TP_MULT = 5.0; BALANCE = 10_000.0; RISK_PCT = 0.02


def precompute(df_1h):
    close = df_1h["close"]; high = df_1h["high"]; low = df_1h["low"]; vol = df_1h["volume"]
    upper, middle, lower = bollinger_bands(close, BB_PERIOD, BB_STD)
    atr_s = atr(high, low, close, ATR_PERIOD)
    vol_ma = vol.rolling(20).mean()
    bb_pos = (close - lower) / (upper - lower).replace(0, np.nan)
    return dict(close=close.values, high=high.values, low=low.values, volume=vol.values,
                upper=upper.values, lower=lower.values, middle=middle.values,
                bb_pos=bb_pos.values, atr=atr_s.values, vol_ma=vol_ma.values, index=df_1h.index)


def backtest(pre, cfg):
    """
    cfg:
      vol_filter    bool
      exit_mode     'baseline' | 'partial50' | 'midband' | 'trail' | 'hold36' | 'hold24'
    """
    vol_filter = cfg.get("vol_filter", False)
    exit_mode  = cfg.get("exit_mode", "baseline")
    max_hold   = {"baseline": 48, "hold36": 36, "hold24": 24}.get(exit_mode, 48)

    close  = pre["close"]; high = pre["high"]; low = pre["low"]
    volume = pre["volume"]; middle = pre["middle"]
    bb_pos = pre["bb_pos"]; atr_v  = pre["atr"]; vol_ma = pre["vol_ma"]
    n = len(close); warmup = 60

    balance = BALANCE
    open_t = None
    trades = []

    for i in range(warmup, n):
        if np.isnan(atr_v[i]) or atr_v[i] <= 0:
            continue

        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]
            qty = open_t["qty"]; held = i - open_t["i"]
            partial_done = open_t.get("partial_done", False)

            exit_p = None; reason = None

            if exit_mode == "partial50" and not partial_done:
                # Check partial TP (half at 2.5xATR)
                partial_tp = open_t["partial_tp"]
                if d == 1 and high[i] >= partial_tp:
                    # Take 50% here
                    half_qty = round(qty / 2, 3)
                    if half_qty >= 0.001:
                        gross = d * (partial_tp - entry) * half_qty
                        fees = (entry + partial_tp) * half_qty * COST_PER_SIDE
                        net = gross - fees
                        balance += net
                        trades.append({"ts": pre["index"][i], "dir": d, "entry": entry,
                                       "exit": partial_tp, "pnl": net, "reason": "partial_tp", "hold": held})
                        open_t["qty"] = qty - half_qty
                        open_t["partial_done"] = True
                        continue
                elif d == -1 and low[i] <= partial_tp:
                    half_qty = round(qty / 2, 3)
                    if half_qty >= 0.001:
                        gross = d * (partial_tp - entry) * half_qty
                        fees = (entry + partial_tp) * half_qty * COST_PER_SIDE
                        net = gross - fees
                        balance += net
                        trades.append({"ts": pre["index"][i], "dir": d, "entry": entry,
                                       "exit": partial_tp, "pnl": net, "reason": "partial_tp", "hold": held})
                        open_t["qty"] = qty - half_qty
                        open_t["partial_done"] = True
                        continue

            if exit_mode == "trail":
                # Once price reaches 2xATR profit, move SL to breakeven + 1xATR profit
                profit_dist = abs(close[i] - entry)
                atr_entry = open_t["atr_entry"]
                if not open_t.get("trailed", False) and profit_dist >= 2 * atr_entry:
                    new_sl = entry + d * atr_entry
                    if d == 1:
                        open_t["sl"] = max(open_t["sl"], new_sl)
                    else:
                        open_t["sl"] = min(open_t["sl"], new_sl)
                    open_t["trailed"] = True
                sl = open_t["sl"]

            # SL / TP check
            if d == 1:
                if low[i] <= sl:
                    exit_p, reason = sl, "sl"
                elif high[i] >= tp:
                    exit_p, reason = tp, "tp"
            else:
                if high[i] >= sl:
                    exit_p, reason = sl, "sl"
                elif low[i] <= tp:
                    exit_p, reason = tp, "tp"

            # Midband exit: close when price crosses back through the middle band
            if exit_mode == "midband" and exit_p is None:
                mid = middle[i]
                if not np.isnan(mid):
                    if d == 1 and high[i] >= mid:
                        exit_p, reason = mid, "midband"
                    elif d == -1 and low[i] <= mid:
                        exit_p, reason = mid, "midband"

            if exit_p is None and held >= max_hold:
                exit_p, reason = close[i], "mh"

            if exit_p is not None:
                cur_qty = open_t["qty"]
                gross = d * (exit_p - entry) * cur_qty
                fees = (entry + exit_p) * cur_qty * COST_PER_SIDE
                net = gross - fees
                balance += net
                trades.append({"ts": pre["index"][i], "dir": d, "entry": entry,
                               "exit": exit_p, "pnl": net, "reason": reason, "hold": held})
                open_t = None
            continue

        # Entry
        bpos = bb_pos[i]
        if np.isnan(bpos):
            continue
        long_ok = bpos < 0.0; short_ok = bpos > 1.0
        if not long_ok and not short_ok:
            continue
        direction = 1 if long_ok else -1

        if vol_filter and not np.isnan(vol_ma[i]) and volume[i] < vol_ma[i]:
            continue

        a = atr_v[i]; entry_price = close[i]
        sl_dist = SL_MULT * a; tp_dist = TP_MULT * a
        if direction == 1:
            sl_price = entry_price - sl_dist; tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist; tp_price = entry_price - tp_dist

        sl_dist_pct = sl_dist / entry_price
        qty = round((balance * RISK_PCT) / (entry_price * sl_dist_pct), 3)
        qty = min(qty, balance * 0.5 / entry_price)
        if qty < 0.001:
            continue

        open_t = {"i": i, "ts": pre["index"][i], "dir": direction,
                  "entry": entry_price, "sl": sl_price, "tp": tp_price,
                  "qty": qty, "atr_entry": a,
                  "partial_tp": entry_price + direction * 2.5 * a,
                  "partial_done": False, "trailed": False}

    return trades


def score_split(trades, split=pd.Timestamp("2026-01-01")):
    tr = [t for t in trades if t["ts"] < split]
    te = [t for t in trades if t["ts"] >= split]

    def _s(tt):
        if not tt:
            return dict(n=0, wr=0, pnl=0, pf=0, dd=0)
        p = np.array([t["pnl"] for t in tt])
        pos = p[p > 0].sum(); neg = -p[p < 0].sum()
        pf = pos / neg if neg > 0 else float("inf")
        eq = BALANCE + np.cumsum(p); peak = np.maximum.accumulate(eq)
        dd = ((peak - eq) / peak).max()
        return dict(n=len(p), wr=(p > 0).mean(), pnl=p.sum(), pf=pf, dd=dd)

    return _s(tr), _s(te)


def pr(label, tr, te):
    tot = tr["pnl"] + te["pnl"]
    print(f"{label:<40s}  ALL {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:>.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:>.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")


def main():
    df_1m = load_all()
    df_1h = resample(df_1m, "1h")
    pre   = precompute(df_1h)

    print("=" * 110)
    print("EXIT STRATEGY RESEARCH — Train: May-Dec 2025 | Test: Jan-Apr 2026")
    print("=" * 110)

    configs = {
        "BASELINE":                 {"vol_filter": False, "exit_mode": "baseline"},
        "BASELINE + vol filter":    {"vol_filter": True,  "exit_mode": "baseline"},
        "Partial50% TP at 2.5xATR": {"vol_filter": False, "exit_mode": "partial50"},
        "Partial50% + vol filter":  {"vol_filter": True,  "exit_mode": "partial50"},
        "Midband target":           {"vol_filter": False, "exit_mode": "midband"},
        "Midband + vol filter":     {"vol_filter": True,  "exit_mode": "midband"},
        "Trailing stop":            {"vol_filter": False, "exit_mode": "trail"},
        "Trailing stop + vol filter":{"vol_filter": True, "exit_mode": "trail"},
        "Max hold 36h":             {"vol_filter": False, "exit_mode": "hold36"},
        "Max hold 36h + vol filter":{"vol_filter": True,  "exit_mode": "hold36"},
        "Max hold 24h":             {"vol_filter": False, "exit_mode": "hold24"},
        "Max hold 24h + vol filter":{"vol_filter": True,  "exit_mode": "hold24"},
    }

    for name, cfg in configs.items():
        trades = backtest(pre, cfg)
        tr, te = score_split(trades)
        pr(name, tr, te)

    # Detailed breakdown of best combos
    print("\n--- Check partial50+vol vs baseline (monthly) ---")
    base_trades = backtest(pre, {"vol_filter": False, "exit_mode": "baseline"})
    test_trades = backtest(pre, {"vol_filter": True, "exit_mode": "partial50"})

    def monthly(trades):
        m = {}
        for t in trades:
            m.setdefault(t["ts"].strftime("%Y-%m"), []).append(t["pnl"])
        return m

    mb = monthly(base_trades); mt = monthly(test_trades)
    print(f"{'Month':<10s}  {'Base n':>6s} {'Base $':>8s}  {'Test n':>6s} {'Test $':>8s}  {'Delta':>8s}")
    for month in sorted(set(list(mb.keys()) + list(mt.keys()))):
        bp = np.array(mb.get(month, [0])); tp = np.array(mt.get(month, [0]))
        print(f"  {month}   {len(bp):>5d}t {bp.sum():>+8.1f}    {len(tp):>5d}t {tp.sum():>+8.1f}   {tp.sum()-bp.sum():>+8.1f}")


if __name__ == "__main__":
    main()
