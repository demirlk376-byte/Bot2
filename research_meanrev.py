"""
Validate a mean-reversion strategy with realistic costs across all 12 months.
Tests the edge found in research_edge.py: fade extensions from the mean,
biased by the 1h trend (buy dips in uptrend, sell rips in downtrend).

Round-trip cost modeled: 2x taker fee (0.01%) + 2x slippage (0.05%) = 0.12%.
We only keep rules whose edge survives this cost in BOTH train and test sets.
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import ema, rsi, atr, bollinger_bands


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


def build_features(df_1m):
    df = resample(df_1m, "5min")
    c = df["close"]
    df["ema9"] = ema(c, 9)
    df["ema21"] = ema(c, 21)
    df["rsi"] = rsi(c, 14)
    df["atr"] = atr(df["high"], df["low"], c, 14)
    df["atr_pct"] = df["atr"] / c
    bb_u, bb_m, bb_l = bollinger_bands(c, 20, 2.0)
    df["bb_u"], df["bb_m"], df["bb_l"] = bb_u, bb_m, bb_l
    df["bb_pos"] = (c - bb_l) / (bb_u - bb_l)

    # 1h context
    df1h = resample(df_1m, "1h")
    e20 = ema(df1h["close"], 20)
    e50 = ema(df1h["close"], 50)
    df["htf_bull"] = (e20 > e50).reindex(df.index, method="ffill").astype(float)
    df["ema50_1h"] = e50.reindex(df.index, method="ffill")
    df["ext_1h"] = c / df["ema50_1h"] - 1  # extension from 1h mean
    return df


def simulate(df, entry_fn, sl_atr=2.0, tp_to_mean=True, tp_atr=2.0, max_hold=48,
             cost=0.0012):
    """
    Generic event-driven sim. entry_fn(row) -> +1 long / -1 short / 0 none.
    SL = sl_atr * ATR. TP = BB middle (mean) if tp_to_mean else tp_atr*ATR.
    Exits also on max_hold candles. One position at a time.
    Returns list of pct returns (net of cost).
    """
    rets = []
    i = 0
    n = len(df)
    arr_close = df["close"].values
    arr_high = df["high"].values
    arr_low = df["low"].values
    arr_atr = df["atr"].values
    arr_mean = df["bb_m"].values

    while i < n - 1:
        row = df.iloc[i]
        d = entry_fn(row)
        if d == 0:
            i += 1
            continue
        entry = arr_close[i]
        a = arr_atr[i]
        if np.isnan(a) or a <= 0:
            i += 1
            continue
        if d == 1:
            sl = entry - sl_atr * a
            tp = arr_mean[i] if tp_to_mean else entry + tp_atr * a
            if tp <= entry:
                tp = entry + tp_atr * a
        else:
            sl = entry + sl_atr * a
            tp = arr_mean[i] if tp_to_mean else entry - tp_atr * a
            if tp >= entry:
                tp = entry - tp_atr * a

        exit_ret = None
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            hi, lo = arr_high[j], arr_low[j]
            if d == 1:
                if lo <= sl:
                    exit_ret = (sl - entry) / entry
                    break
                if hi >= tp:
                    exit_ret = (tp - entry) / entry
                    break
            else:
                if hi >= sl:
                    exit_ret = (entry - sl) / entry
                    break
                if lo <= tp:
                    exit_ret = (entry - tp) / entry
                    break
        if exit_ret is None:
            j = min(i + max_hold, n - 1)
            exit_ret = d * (arr_close[j] - entry) / entry
        rets.append(exit_ret - cost)
        i = j + 1  # move past exit
    return rets


def stats(rets, label):
    if not rets:
        print(f"{label:42s}: 0 trades")
        return 0
    arr = np.array(rets)
    wr = (arr > 0).mean()
    total = arr.sum()
    pf_num = arr[arr > 0].sum()
    pf_den = -arr[arr < 0].sum()
    pf = pf_num / pf_den if pf_den > 0 else float("inf")
    print(f"{label:42s}: {len(arr):4d} trades | WR {wr:4.0%} | "
          f"avg {arr.mean()*100:+.3f}% | total {total*100:+.1f}% | PF {pf:.2f}")
    return total


def main():
    df_1m = load_all()
    df = build_features(df_1m)
    df = df.dropna(subset=["ema9", "ema21", "rsi", "atr", "bb_pos", "htf_bull"])

    # Train/test split
    split = pd.Timestamp("2026-01-01")
    train = df[df.index < split]
    test = df[df.index >= split]
    print(f"TRAIN: {train.index[0]:%Y-%m} → {train.index[-1]:%Y-%m} ({len(train):,})")
    print(f"TEST:  {test.index[0]:%Y-%m} → {test.index[-1]:%Y-%m} ({len(test):,})")

    MIN_ATR = 0.0012

    # --- Candidate rules ---
    def r_bb_revert(row):
        # Fade Bollinger extremes (pure mean reversion)
        if row["atr_pct"] < MIN_ATR:
            return 0
        if row["bb_pos"] < 0.0:
            return 1
        if row["bb_pos"] > 1.0:
            return -1
        return 0

    def r_bb_trend_filtered(row):
        # Buy dips only in uptrend, sell rips only in downtrend
        if row["atr_pct"] < MIN_ATR:
            return 0
        if row["bb_pos"] < 0.05 and row["htf_bull"] == 1.0:
            return 1
        if row["bb_pos"] > 0.95 and row["htf_bull"] == 0.0:
            return -1
        return 0

    def r_rsi_revert(row):
        if row["atr_pct"] < MIN_ATR:
            return 0
        if row["rsi"] < 30:
            return 1
        if row["rsi"] > 70:
            return -1
        return 0

    def r_rsi_trend_filtered(row):
        if row["atr_pct"] < MIN_ATR:
            return 0
        if row["rsi"] < 35 and row["htf_bull"] == 1.0:
            return 1
        if row["rsi"] > 65 and row["htf_bull"] == 0.0:
            return -1
        return 0

    def r_ext_1h(row):
        # Fade extension from 1h mean
        if row["atr_pct"] < MIN_ATR:
            return 0
        if row["ext_1h"] > 0.025:
            return -1
        if row["ext_1h"] < -0.025:
            return 1
        return 0

    def r_combo(row):
        # Best hypothesis: BB extreme + RSI confirm + 1h aligned
        if row["atr_pct"] < MIN_ATR:
            return 0
        if row["bb_pos"] < 0.1 and row["rsi"] < 40 and row["htf_bull"] == 1.0:
            return 1
        if row["bb_pos"] > 0.9 and row["rsi"] > 60 and row["htf_bull"] == 0.0:
            return -1
        return 0

    rules = [
        ("BB fade (pure)", r_bb_revert),
        ("BB fade + 1h filter", r_bb_trend_filtered),
        ("RSI fade (pure)", r_rsi_revert),
        ("RSI fade + 1h filter", r_rsi_trend_filtered),
        ("Extension from 1h mean", r_ext_1h),
        ("Combo BB+RSI+1h", r_combo),
    ]

    for tp_mode in [("TP=mean", True), ("TP=2xATR", False)]:
        print(f"\n{'='*70}\n{tp_mode[0]} | SL=2xATR | cost=0.12%/trade\n{'='*70}")
        for name, fn in rules:
            print(f"\n  [{name}]")
            stats(simulate(train, fn, tp_to_mean=tp_mode[1]), "    TRAIN")
            stats(simulate(test, fn, tp_to_mean=tp_mode[1]), "    TEST ")


if __name__ == "__main__":
    main()
