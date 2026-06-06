"""
Find a VIABLE configuration: cost sensitivity + selective extreme signals.

Two levers to beat costs:
  1. Lower cost via maker/limit entries (MEXC futures maker = 0%)
  2. Larger targets via more selective extreme-extension signals (less frequent,
     bigger moves so the edge dwarfs the cost)

We test on train (May-Dec 2025) and test (Jan-Apr 2026) separately.
A config is only viable if it's profitable in BOTH.
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


def build(df_1m, tf):
    df = resample(df_1m, tf)
    c = df["close"]
    df["rsi"] = rsi(c, 14)
    df["atr"] = atr(df["high"], df["low"], c, 14)
    df["atr_pct"] = df["atr"] / c
    bb_u, bb_m, bb_l = bollinger_bands(c, 20, 2.0)
    df["bb_m"] = bb_m
    df["bb_pos"] = (c - bb_l) / (bb_u - bb_l)
    df1h = resample(df_1m, "1h")
    e20, e50 = ema(df1h["close"], 20), ema(df1h["close"], 50)
    df["htf_bull"] = (e20 > e50).reindex(df.index, method="ffill").astype(float)
    df["ema50_1h"] = e50.reindex(df.index, method="ffill")
    df["ext_1h"] = c / df["ema50_1h"] - 1
    return df.dropna(subset=["rsi", "atr", "bb_pos", "htf_bull", "ext_1h"])


def simulate(df, entry_fn, sl_atr, tp_atr, max_hold, cost):
    rets = []
    i, n = 0, len(df)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    a_atr = df["atr"].values
    mean = df["bb_m"].values
    while i < n - 1:
        d = entry_fn(df.iloc[i])
        if d == 0:
            i += 1
            continue
        entry = close[i]
        a = a_atr[i]
        if np.isnan(a) or a <= 0:
            i += 1
            continue
        if d == 1:
            sl = entry - sl_atr * a
            tp = entry + tp_atr * a
        else:
            sl = entry + sl_atr * a
            tp = entry - tp_atr * a
        exit_ret = None
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            if d == 1:
                if low[j] <= sl:
                    exit_ret = (sl - entry) / entry; break
                if high[j] >= tp:
                    exit_ret = (tp - entry) / entry; break
            else:
                if high[j] >= sl:
                    exit_ret = (entry - sl) / entry; break
                if low[j] <= tp:
                    exit_ret = (entry - tp) / entry; break
        if exit_ret is None:
            j = min(i + max_hold, n - 1)
            exit_ret = d * (close[j] - entry) / entry
        rets.append(exit_ret - cost)
        i = j + 1
    return rets


def stat(rets):
    if not rets:
        return (0, 0, 0, 0)
    a = np.array(rets)
    wr = (a > 0).mean()
    pf = a[a > 0].sum() / (-a[a < 0].sum()) if (a < 0).any() else float("inf")
    return (len(a), wr, a.sum(), pf)


def show(label, train_r, test_r):
    nt, wt, tt, pt = stat(train_r)
    ne, we, te, pe = stat(test_r)
    flag = "✓" if tt > 0 and te > 0 else " "
    print(f"{flag} {label:38s} TR:{nt:4d}t WR{wt:3.0%} {tt*100:+6.1f}% PF{pt:.2f} | "
          f"TE:{ne:4d}t WR{we:3.0%} {te*100:+6.1f}% PF{pe:.2f}")


def main():
    df_1m = load_all()
    split = pd.Timestamp("2026-01-01")

    # ---- Cost sensitivity on best rule (extension fade) at 5m ----
    print("="*100)
    print("MALİYET DUYARLILIĞI — Extension fade (5m), farklı maliyet seviyeleri")
    print("="*100)
    df5 = build(df_1m, "5min")
    tr5, te5 = df5[df5.index < split], df5[df5.index >= split]

    def ext_fade(thr):
        def fn(row):
            if row["atr_pct"] < 0.0012:
                return 0
            if row["ext_1h"] > thr:
                return -1
            if row["ext_1h"] < -thr:
                return 1
            return 0
        return fn

    for cost in [0.0012, 0.0008, 0.0004, 0.0002]:
        print(f"\n  cost={cost*100:.2f}%/trade:")
        for thr in [0.015, 0.025, 0.035]:
            show(f"ext>{thr*100:.0f}% SL2 TP2",
                 simulate(tr5, ext_fade(thr), 2, 2, 48, cost),
                 simulate(te5, ext_fade(thr), 2, 2, 48, cost))

    # ---- Higher timeframe (15m) with bigger targets ----
    print("\n" + "="*100)
    print("15m TIMEFRAME — büyük hedefler, seyrek işlem (maliyet=0.08%, limit giriş varsayımı)")
    print("="*100)
    df15 = build(df_1m, "15min")
    tr15, te15 = df15[df15.index < split], df15[df15.index >= split]

    def bb_fade_15(row):
        if row["atr_pct"] < 0.0015:
            return 0
        if row["bb_pos"] < 0.0:
            return 1
        if row["bb_pos"] > 1.0:
            return -1
        return 0

    def ext_fade_15(thr):
        def fn(row):
            if row["ext_1h"] > thr:
                return -1
            if row["ext_1h"] < -thr:
                return 1
            return 0
        return fn

    for cost in [0.0008, 0.0004]:
        print(f"\n  cost={cost*100:.2f}%/trade:")
        for sl, tp in [(2, 3), (2.5, 4), (3, 5)]:
            show(f"BBfade SL{sl} TP{tp}",
                 simulate(tr15, bb_fade_15, sl, tp, 64, cost),
                 simulate(te15, bb_fade_15, sl, tp, 64, cost))
        for thr in [0.02, 0.03]:
            for sl, tp in [(2.5, 4), (3, 5)]:
                show(f"ext>{thr*100:.0f}% SL{sl} TP{tp}",
                     simulate(tr15, ext_fade_15(thr), sl, tp, 64, cost),
                     simulate(te15, ext_fade_15(thr), sl, tp, 64, cost))

    # ---- 1h timeframe, swing-style ----
    print("\n" + "="*100)
    print("1h TIMEFRAME — swing, çok seyrek (maliyet=0.08%)")
    print("="*100)
    df1h = build(df_1m, "1h")
    tr1h, te1h = df1h[df1h.index < split], df1h[df1h.index >= split]

    def bb_fade_1h(row):
        if row["bb_pos"] < 0.0:
            return 1
        if row["bb_pos"] > 1.0:
            return -1
        return 0

    for cost in [0.0008]:
        print(f"\n  cost={cost*100:.2f}%/trade:")
        for sl, tp in [(2, 3), (2.5, 4), (3, 5)]:
            show(f"BBfade SL{sl} TP{tp}",
                 simulate(tr1h, bb_fade_1h, sl, tp, 48, cost),
                 simulate(te1h, bb_fade_1h, sl, tp, 48, cost))


if __name__ == "__main__":
    main()
