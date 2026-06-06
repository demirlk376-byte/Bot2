"""
Thorough validation of the winning approach: 1h Bollinger-band mean reversion.
- Monthly breakdown across all 12 months
- Hold-time distribution (is it intraday-ish?)
- Parameter robustness (does it survive nearby parameter values?)
- Filter experiments (RSI, 1h trend alignment, ATR floor)
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


def build_1h(df_1m):
    df = resample(df_1m, "1h")
    c = df["close"]
    df["rsi"] = rsi(c, 14)
    df["atr"] = atr(df["high"], df["low"], c, 14)
    df["atr_pct"] = df["atr"] / c
    bb_u, bb_m, bb_l = bollinger_bands(c, 20, 2.0)
    df["bb_m"] = bb_m
    df["bb_pos"] = (c - bb_l) / (bb_u - bb_l)
    # 4h trend context (higher TF for the 1h system)
    df4h = resample(df_1m, "4h")
    e20, e50 = ema(df4h["close"], 20), ema(df4h["close"], 50)
    df["htf_bull"] = (e20 > e50).reindex(df.index, method="ffill").astype(float)
    return df.dropna(subset=["rsi", "atr", "bb_pos"])


def simulate(df, entry_fn, sl_atr, tp_atr, max_hold, cost):
    """Returns (rets, holds) — pct returns and hold durations in candles."""
    rets, holds = [], []
    i, n = 0, len(df)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    a_atr = df["atr"].values
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
        sl = entry - d * sl_atr * a
        tp = entry + d * tp_atr * a
        exit_ret, hold = None, 0
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            hold = j - i
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
            hold = j - i
            exit_ret = d * (close[j] - entry) / entry
        rets.append((df.index[i], exit_ret - cost))
        holds.append(hold)
        i = j + 1
    return rets, holds


def report(rets):
    if not rets:
        print("  0 trades"); return
    a = np.array([r for _, r in rets])
    wr = (a > 0).mean()
    pf = a[a > 0].sum() / (-a[a < 0].sum()) if (a < 0).any() else float("inf")
    # equity & drawdown (compounded on 2% risk-equivalent: here just sum of pct)
    eq = np.cumsum(a)
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))
    dd = (peak[1:] - eq)
    print(f"  {len(a)} trades | WR {wr:.0%} | total {a.sum()*100:+.1f}% | "
          f"PF {pf:.2f} | avg {a.mean()*100:+.3f}% | maxDD {dd.max()*100:.1f}%")


def monthly(rets):
    m: dict = {}
    for ts, r in rets:
        m.setdefault(ts.strftime("%Y-%m"), []).append(r)
    print(f"  {'Ay':9s} {'N':>4s} {'WR':>5s} {'PnL%':>8s} {'Kümül':>8s}")
    cum = 0
    for k in sorted(m):
        arr = np.array(m[k]); cum += arr.sum()
        print(f"  {k:9s} {len(arr):>4d} {(arr>0).mean():>4.0%} "
              f"{arr.sum()*100:>+7.1f}% {cum*100:>+7.1f}%")


def main():
    df_1m = load_all()
    df = build_1h(df_1m)
    split = pd.Timestamp("2026-01-01")
    COST = 0.0008  # 0.08% — realistic with limit/maker entry + market exit

    def bb_fade(row):
        if row["bb_pos"] < 0.0:
            return 1
        if row["bb_pos"] > 1.0:
            return -1
        return 0

    def bb_fade_rsi(row):
        # Require RSI confirmation
        if row["bb_pos"] < 0.0 and row["rsi"] < 40:
            return 1
        if row["bb_pos"] > 1.0 and row["rsi"] > 60:
            return -1
        return 0

    def bb_fade_aligned(row):
        # Counter-trend fade but only WITH the 4h trend (buy dips in 4h uptrend)
        if row["bb_pos"] < 0.0 and row["htf_bull"] == 1.0:
            return 1
        if row["bb_pos"] > 1.0 and row["htf_bull"] == 0.0:
            return -1
        return 0

    print("="*70)
    print("KAZANAN STRATEJİ DOĞRULAMA — 1h Bollinger mean-reversion")
    print(f"Maliyet varsayımı: {COST*100:.2f}%/işlem (limit giriş + market çıkış)")
    print("="*70)

    print("\n### Temel: BB fade SL3 TP5 (TÜM 12 AY)")
    rets, holds = simulate(df, bb_fade, 3, 5, 48, COST)
    report(rets)
    print(f"  Ortalama tutma: {np.mean(holds):.1f} saat | medyan: {np.median(holds):.0f}h | "
          f"max: {np.max(holds)}h | <24h: {(np.array(holds)<24).mean():.0%}")
    monthly(rets)

    print("\n### Train/Test ayrımı")
    tr = [(t, r) for t, r in rets if t < split]
    te = [(t, r) for t, r in rets if t >= split]
    print("  TRAIN (May-Dec 2025):", end=" "); report(tr)
    print("  TEST  (Jan-Apr 2026):", end=" "); report(te)

    print("\n### Filtre denemeleri (tüm 12 ay)")
    print("  BB fade + RSI confirm:")
    r2, _ = simulate(df, bb_fade_rsi, 3, 5, 48, COST); report(r2)
    print("  BB fade + 4h trend aligned (dip-buy/rip-sell):")
    r3, _ = simulate(df, bb_fade_aligned, 3, 5, 48, COST); report(r3)

    print("\n### Parametre sağlamlık matrisi (BB fade, tüm 12 ay)")
    sltp = "SL/TP"
    print(f"  {sltp:>6s}", end="")
    tps = [3, 4, 5, 6]
    for tp in tps:
        print(f"{'TP'+str(tp):>10s}", end="")
    print()
    for sl in [2, 2.5, 3, 3.5]:
        print(f"  {sl:>6.1f}", end="")
        for tp in tps:
            rr, _ = simulate(df, bb_fade, sl, tp, 48, COST)
            a = np.array([x for _, x in rr])
            tot = a.sum()*100 if len(a) else 0
            print(f"{tot:>+9.1f}%", end="")
        print()

    print("\n### Maliyet duyarlılığı (BB fade SL3 TP5, tüm 12 ay)")
    for cost in [0.0012, 0.0008, 0.0004]:
        rr, _ = simulate(df, bb_fade, 3, 5, 48, cost)
        a = np.array([x for _, x in rr])
        print(f"  cost {cost*100:.2f}%: total {a.sum()*100:+.1f}% | PF "
              f"{a[a>0].sum()/(-a[a<0].sum()) if (a<0).any() else 0:.2f}")


if __name__ == "__main__":
    main()
