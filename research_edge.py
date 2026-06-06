"""
Empirical edge research: for each indicator state, measure the FORWARD return.
This finds which signals actually predict price movement BEFORE building a
strategy — the opposite of overfitting (we discover edge, not fit the curve).

For each 5m candle we compute indicator features, then measure the return
N candles ahead. We bucket by feature value and report mean forward return,
win rate, and sample size. A feature has edge if forward returns differ
meaningfully across buckets in a monotonic, sensible way.
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import ema, macd, rsi, atr, adx, bollinger_bands


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


def analyze_feature(df, feature_col, forward_col, buckets, label):
    print(f"\n### {label}")
    valid = df[[feature_col, forward_col]].dropna()
    valid["bucket"] = pd.cut(valid[feature_col], bins=buckets)
    grouped = valid.groupby("bucket", observed=True)
    print(f"{'Bucket':>22s} {'N':>7s} {'FwdRet%':>9s} {'Win%':>7s}")
    for b, g in grouped:
        if len(g) < 50:
            continue
        mean_ret = g[forward_col].mean() * 100
        win = (g[forward_col] > 0).mean() * 100
        print(f"{str(b):>22s} {len(g):>7d} {mean_ret:>+8.3f}% {win:>6.1f}%")


def main():
    df_1m = load_all()
    df = resample(df_1m, "5min")
    print(f"5m candles: {len(df):,}")

    c = df["close"]
    # Features
    df["ema9"] = ema(c, 9)
    df["ema21"] = ema(c, 21)
    df["ema50"] = ema(c, 50)
    df["ema_sep"] = (df["ema9"] - df["ema21"]) / df["ema21"]
    _, _, df["macd_hist"] = macd(c)
    df["rsi"] = rsi(c, 14)
    df["atr"] = atr(df["high"], df["low"], c, 14)
    df["atr_pct"] = df["atr"] / c
    df["adx"] = adx(df["high"], df["low"], c, 14)
    bb_u, bb_m, bb_l = bollinger_bands(c, 20, 2.0)
    df["bb_pos"] = (c - bb_l) / (bb_u - bb_l)  # 0 = at lower, 1 = at upper

    # 1h trend context
    df1h = resample(df_1m, "1h")
    ema20_1h = ema(df1h["close"], 20)
    ema50_1h = ema(df1h["close"], 50)
    df["htf_bull"] = (ema20_1h > ema50_1h).reindex(df.index, method="ffill").astype(float)
    df["price_vs_1h50"] = (c / ema50_1h.reindex(df.index, method="ffill") - 1)

    # Forward returns at multiple horizons (in 5m candles)
    for h in [6, 12, 24, 48]:  # 30min, 1h, 2h, 4h
        df[f"fwd{h}"] = c.shift(-h) / c - 1

    print("\n" + "=" * 60)
    print("İLERİYE DÖNÜK GETİRİ ANALİZİ (edge araştırması)")
    print("Horizon: fwd12 = 1 saat sonraki getiri")
    print("=" * 60)

    # 1. EMA separation (trend strength/direction)
    analyze_feature(df, "ema_sep", "fwd12",
                    [-0.02, -0.005, -0.002, 0, 0.002, 0.005, 0.02],
                    "EMA9-21 ayrımı → 1h forward")

    # 2. RSI
    analyze_feature(df, "rsi", "fwd12",
                    [0, 25, 35, 45, 55, 65, 75, 100],
                    "RSI → 1h forward")

    # 3. ADX (does trend strength predict continuation?)
    analyze_feature(df, "adx", "fwd12",
                    [0, 15, 20, 25, 30, 40, 100],
                    "ADX → 1h forward (yön bağımsız |fwd|)")

    # 4. BB position (mean reversion signal)
    analyze_feature(df, "bb_pos", "fwd12",
                    [-0.5, 0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5],
                    "Bollinger pozisyonu → 1h forward")

    # 5. MACD histogram
    df["macd_norm"] = df["macd_hist"] / c
    analyze_feature(df, "macd_norm", "fwd12",
                    [-0.005, -0.001, -0.0003, 0, 0.0003, 0.001, 0.005],
                    "MACD histogram (normalize) → 1h forward")

    # 6. Price vs 1h EMA50 (macro trend position)
    analyze_feature(df, "price_vs_1h50", "fwd24",
                    [-0.1, -0.03, -0.01, 0, 0.01, 0.03, 0.1],
                    "Fiyat / 1h-EMA50 → 2h forward")

    # 7. CRITICAL: conditional — RSI in uptrend vs downtrend (1h context)
    print("\n" + "=" * 60)
    print("KOŞULLU: 1h trend bağlamında RSI (mean-reversion edge?)")
    print("=" * 60)
    for ctx, name in [(1.0, "1h BULLISH"), (0.0, "1h BEARISH")]:
        sub = df[df["htf_bull"] == ctx]
        print(f"\n--- {name} ({len(sub):,} mum) ---")
        analyze_feature(sub, "rsi", "fwd12",
                        [0, 25, 35, 45, 55, 65, 75, 100],
                        f"RSI → 1h forward [{name}]")

    # 8. Trend-following edge: EMA sep aligned WITH 1h trend
    print("\n" + "=" * 60)
    print("KOŞULLU: EMA ayrımı, 1h trend ile HİZALI olduğunda")
    print("=" * 60)
    bull_ctx = df[df["htf_bull"] == 1.0]
    analyze_feature(bull_ctx, "ema_sep", "fwd24",
                    [-0.02, -0.005, -0.002, 0, 0.002, 0.005, 0.02],
                    "EMA ayrımı → 2h forward [1h BULLISH]")
    bear_ctx = df[df["htf_bull"] == 0.0]
    analyze_feature(bear_ctx, "ema_sep", "fwd24",
                    [-0.02, -0.005, -0.002, 0, 0.002, 0.005, 0.02],
                    "EMA ayrımı → 2h forward [1h BEARISH]")


if __name__ == "__main__":
    main()
