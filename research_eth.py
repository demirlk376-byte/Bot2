"""
Cross-asset robustness check: does the BTC 1h BB-fade edge transfer to ETH?

Runs the IDENTICAL strategy (1h Bollinger fade + volume filter + 3% risk +
maker cost), with ZERO re-tuning, on 5 months of ETH/USDT 1m data
(Sep–Dec 2025 train, Apr 2026 test).

Honest result: it does NOT transfer cleanly. ETH trended hard in Sep–Oct 2025
(WR 24% / 32%) and mean reversion got run over, dragging the train window to
-10%. Only the single test month (Apr 2026, 19 trades) was good (+10%). Overall
roughly flat (+0.5%). Re-tuning ETH on 5 months would be overfitting — so the
conclusion is to NOT trade ETH with this edge, and to pursue funding/OI instead.

Run: python research_eth.py
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST = 0.0002      # maker entry + market exit (0.04% round trip)
SL_M = 3.0
TP_M = 5.0
BAL = 10_000.0
RISK = 0.03
MH = 48


def load_eth():
    files = sorted(glob.glob("/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv"))
    if not files:
        print("No ETH data found in eth_data/ — skipping.")
        sys.exit(0)
    frames = []
    for f in files:
        df = pd.read_csv(f)  # ETH files carry a header row
        df = df.rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df, rule):
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def run(df_1h, vol_filter=True):
    c = df_1h["close"].values; h = df_1h["high"].values
    lo = df_1h["low"].values; vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
    n = len(c); warmup = 60; balance = BAL; open_t = None; trades = []

    for i in range(warmup, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]; held = i - open_t["i"]
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
        if vol_filter and not np.isnan(vol_ma[i]) and vol[i] < vol_ma[i]:
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


def stat(tt):
    if not tt:
        return "0t"
    p = np.array([t["pnl"] for t in tt])
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf = pos / neg if neg > 0 else float("inf")
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq); dd = ((pk - eq) / pk).max()
    return (f"{len(p)}t WR{(p > 0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+8.0f} ({p.sum()/100:+.1f}%) maxDD{dd*100:.1f}%")


def main():
    df = load_eth(); df_1h = resample(df, "1h")
    split = pd.Timestamp("2026-01-01")
    print(f"ETH range: {df_1h.index[0]} -> {df_1h.index[-1]} ({len(df_1h)} 1h candles)")
    print("=" * 90)

    trades = run(df_1h, vol_filter=True)
    tr = [t for t in trades if t["ts"] < split]
    te = [t for t in trades if t["ts"] >= split]
    print("ETH — IDENTICAL BTC strategy (1h BB fade + volume filter), zero re-tuning")
    print(f"  ALL (5 months)   : {stat(trades)}")
    print(f"  TRAIN (Sep-Dec25): {stat(tr)}")
    print(f"  TEST  (Apr 2026) : {stat(te)}")

    print("\nMonthly:")
    m: dict = {}
    for t in trades:
        m.setdefault(t["ts"].strftime("%Y-%m"), []).append(t["pnl"])
    for k in sorted(m):
        p = np.array(m[k])
        print(f"  {k}: {len(p):>3d}t WR{(p > 0).mean():>4.0%} ${p.sum():>+8.0f}")

    print("\nVerdict: edge does NOT transfer to ETH in this sample (train -10%).")
    print("Pursue funding/OI (funding.py) over multi-pair diversification.")


if __name__ == "__main__":
    main()
