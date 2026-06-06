"""
Research: test principled improvements to the 1h BB mean-reversion strategy.
All changes are grounded in trading theory, NOT fitted to the data.
Train/test split preserved: Train = May-Dec 2025, Test = Jan-Apr 2026.

Improvements tested:
  A) Band re-entry confirmation  — enter when price RETURNS INTO the band
                                   (prev close outside band, curr close inside)
  B) ADX momentum filter         — skip if ADX > threshold (strong trend overrides reversion)
  C) Volume exhaustion filter    — require above-average volume on the extreme candle
  D) BB width (volatility) filter — avoid entries during BB squeeze (often precedes breakout)

Each improvement is tested independently and in combination to find what
genuinely helps WITHOUT cherry-picking (we pick the variant by train score,
verify on test).
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")

from config import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig, TelegramConfig
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


COST_PER_SIDE = 0.0004   # 0.04% per side = 0.08% round trip
BB_PERIOD = 20
BB_STD    = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
SL_MULT = 3.0
TP_MULT = 5.0
MAX_HOLD = 48
LEVERAGE = 10
BALANCE  = 10_000.0
RISK_PCT  = 0.02


def precompute(df_1h):
    close = df_1h["close"]
    high  = df_1h["high"]
    low   = df_1h["low"]
    vol   = df_1h["volume"]

    upper, middle, lower = bollinger_bands(close, BB_PERIOD, BB_STD)
    rsi_s  = rsi(close, RSI_PERIOD)
    atr_s  = atr(high, low, close, ATR_PERIOD)
    adx_s  = adx(high, low, close, ADX_PERIOD)
    vol_ma = vol.rolling(20).mean()

    bb_pos = (close - lower) / (upper - lower).replace(0, np.nan)

    return {
        "close": close.values,
        "high":  high.values,
        "low":   low.values,
        "volume": vol.values,
        "upper": upper.values,
        "lower": lower.values,
        "middle": middle.values,
        "bb_pos": bb_pos.values,
        "rsi":   rsi_s.values,
        "atr":   atr_s.values,
        "adx":   adx_s.values,
        "vol_ma": vol_ma.values,
        "index": df_1h.index,
    }


def backtest(pre, cfg: dict):
    """
    cfg keys (all optional with defaults):
      reentry        bool  — require band re-entry confirmation
      adx_max        float — skip when ADX > this (0 = disabled)
      vol_filter     bool  — require above-average volume on signal candle
      bb_width_min   float — skip when BB width < this fraction of price (0 = disabled)
    """
    reentry      = cfg.get("reentry", False)
    adx_max      = cfg.get("adx_max", 0.0)
    vol_filter   = cfg.get("vol_filter", False)
    bb_width_min = cfg.get("bb_width_min", 0.0)

    close   = pre["close"]
    high    = pre["high"]
    low     = pre["low"]
    volume  = pre["volume"]
    upper   = pre["upper"]
    lower   = pre["lower"]
    middle  = pre["middle"]
    bb_pos  = pre["bb_pos"]
    rsi_v   = pre["rsi"]
    atr_v   = pre["atr"]
    adx_v   = pre["adx"]
    vol_ma  = pre["vol_ma"]
    n       = len(close)
    warmup  = 60

    balance = BALANCE
    open_t  = None
    trades  = []

    for i in range(warmup, n):
        if np.isnan(atr_v[i]) or atr_v[i] <= 0:
            continue

        # ---------- manage open trade ----------
        if open_t is not None:
            d     = open_t["dir"]
            entry = open_t["entry"]
            sl    = open_t["sl"]
            tp    = open_t["tp"]
            qty   = open_t["qty"]
            held  = i - open_t["i"]

            exit_p = None
            reason = None
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

            if exit_p is None and held >= MAX_HOLD:
                exit_p, reason = close[i], "mh"

            if exit_p is not None:
                gross = d * (exit_p - entry) * qty
                fees  = (entry + exit_p) * qty * COST_PER_SIDE
                net   = gross - fees
                balance += net
                trades.append({
                    "ts": pre["index"][i],
                    "dir": d, "entry": entry, "exit": exit_p,
                    "pnl": net, "reason": reason, "hold": held,
                })
                open_t = None
            continue

        # ---------- entry logic ----------
        bpos = bb_pos[i]
        if np.isnan(bpos):
            continue

        # Band re-entry confirmation: previous candle outside band, current inside
        if reentry:
            if i < 1:
                continue
            prev_bpos = bb_pos[i - 1]
            if np.isnan(prev_bpos):
                continue
            long_ok  = (prev_bpos < 0.0) and (bpos >= 0.0)
            short_ok = (prev_bpos > 1.0) and (bpos <= 1.0)
        else:
            long_ok  = bpos < 0.0
            short_ok = bpos > 1.0

        if not long_ok and not short_ok:
            continue

        direction = 1 if long_ok else -1

        # ADX filter: skip in strong trends
        if adx_max > 0 and not np.isnan(adx_v[i]) and adx_v[i] > adx_max:
            continue

        # Volume exhaustion filter: signal candle must have above-average volume
        if vol_filter:
            ref_i = i - 1 if reentry else i
            if not np.isnan(vol_ma[ref_i]) and volume[ref_i] < vol_ma[ref_i]:
                continue

        # BB width filter: avoid squeeze / very tight bands
        if bb_width_min > 0:
            bw = (upper[i] - lower[i]) / middle[i] if middle[i] > 0 else 0
            if bw < bb_width_min:
                continue

        # Build trade setup — matches RiskManager.build_trade_setup() exactly
        a = atr_v[i]
        entry_price = close[i]
        sl_dist  = SL_MULT * a
        tp_dist  = TP_MULT * a
        if direction == 1:
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist
            tp_price = entry_price - tp_dist

        sl_dist_pct = sl_dist / entry_price
        if sl_dist_pct <= 0:
            continue
        risk_amt = balance * RISK_PCT
        qty = risk_amt / (entry_price * sl_dist_pct)
        qty = min(qty, balance * 0.5 / entry_price)
        qty = round(qty, 3)
        if qty < 0.001:
            continue

        open_t = {
            "i": i, "ts": pre["index"][i], "dir": direction,
            "entry": entry_price, "sl": sl_price, "tp": tp_price,
            "qty": qty,
        }

    return trades


def score(trades, split=None):
    if not trades:
        return dict(n=0, wr=0, pnl=0, pf=0, dd=0)
    if split is not None:
        trades = [t for t in trades if t["ts"] < split]
    pnls = np.array([t["pnl"] for t in trades])
    wins = (pnls > 0).sum()
    pos_sum = pnls[pnls > 0].sum()
    neg_sum = -pnls[pnls < 0].sum()
    pf = pos_sum / neg_sum if neg_sum > 0 else float("inf")
    eq   = BALANCE + np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd   = ((peak - eq) / peak).max()
    return dict(n=len(pnls), wr=wins / len(pnls), pnl=pnls.sum(), pf=pf, dd=dd)


def pr(label, tr, te):
    tot_n = tr["n"] + te["n"]
    tot_pnl = tr["pnl"] + te["pnl"]
    tot_pct = tot_pnl / 100
    print(f"{label:<42s}  "
          f"ALL {tot_n:>3d}t {tot_pct:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:>.2f} {tr['pnl']:>+7.0f}  |  "
          f"TEST {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:>.2f} {te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")


def main():
    df_1m = load_all()
    df_1h = resample(df_1m, "1h")
    pre   = precompute(df_1h)
    split = pd.Timestamp("2026-01-01")

    # --- Baseline ---
    base = backtest(pre, {})
    tr = score(base, split)
    te = score([t for t in base if t["ts"] >= split])
    print("=" * 100)
    print("IMPROVEMENT RESEARCH — Train: May-Dec 2025 | Test: Jan-Apr 2026")
    print("=" * 100)
    pr("BASELINE (no filter)", tr, te)
    print()

    configs = {
        # Single filters
        "A: reentry confirmation":         {"reentry": True},
        "B: ADX<30 filter":                {"adx_max": 30},
        "B: ADX<35 filter":                {"adx_max": 35},
        "B: ADX<40 filter":                {"adx_max": 40},
        "C: volume exhaustion filter":     {"vol_filter": True},
        "D: BB width>1.5% filter":         {"bb_width_min": 0.015},
        "D: BB width>2.0% filter":         {"bb_width_min": 0.020},
        # Combinations
        "A+B30: reentry + ADX<30":         {"reentry": True, "adx_max": 30},
        "A+B35: reentry + ADX<35":         {"reentry": True, "adx_max": 35},
        "A+B40: reentry + ADX<40":         {"reentry": True, "adx_max": 40},
        "A+C: reentry + volume":           {"reentry": True, "vol_filter": True},
        "A+C+B35: reentry+vol+ADX35":      {"reentry": True, "vol_filter": True, "adx_max": 35},
        "A+C+B40: reentry+vol+ADX40":      {"reentry": True, "vol_filter": True, "adx_max": 40},
        "B35+C: ADX35+volume":             {"adx_max": 35, "vol_filter": True},
        "B40+C: ADX40+volume":             {"adx_max": 40, "vol_filter": True},
    }

    results = {}
    for name, cfg in configs.items():
        trades = backtest(pre, cfg)
        tr = score(trades, split)
        te = score([t for t in trades if t["ts"] >= split])
        results[name] = (tr, te)
        pr(name, tr, te)

    # Pick winner by train PF (ignoring test entirely for selection)
    print()
    print("--- Best by TRAIN profit factor (test is hold-out) ---")
    best_name, best = max(results.items(), key=lambda x: x[1][0]["pf"])
    tr, te = best
    pr(f"WINNER: {best_name}", tr, te)

    # Now show detailed breakdown of winner vs baseline on test set
    print()
    print("--- Monthly breakdown: BASELINE vs WINNER ---")
    base_trades = backtest(pre, {})
    winner_cfg  = configs[best_name]
    win_trades  = backtest(pre, winner_cfg)

    months_b: dict = {}
    for t in base_trades:
        months_b.setdefault(t["ts"].strftime("%Y-%m"), []).append(t["pnl"])

    months_w: dict = {}
    for t in win_trades:
        months_w.setdefault(t["ts"].strftime("%Y-%m"), []).append(t["pnl"])

    print(f"{'Month':<10s}  {'Base n':>6s} {'Base $':>8s}  {'Win n':>6s} {'Win $':>8s}  {'Delta':>8s}")
    for m in sorted(set(list(months_b.keys()) + list(months_w.keys()))):
        bp = np.array(months_b.get(m, [0]))
        wp = np.array(months_w.get(m, [0]))
        bs = bp.sum(); ws = wp.sum()
        print(f"  {m}   {len(bp):>5d}t {bs:>+8.1f}    {len(wp):>5d}t {ws:>+8.1f}   {ws-bs:>+8.1f}")


if __name__ == "__main__":
    main()
