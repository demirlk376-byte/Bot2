"""
Candlestick pattern confirmation at 1h Bollinger-band extremes.

Tests whether adding a candlestick formation filter (Engulfing, Morning/Evening
Star, Three Crows/Soldiers, Doji) as a confirmation layer improves the validated
1h BB mean-reversion edge.

Honest result: every pattern HURTS.
- Engulfing / Morning Star / Evening Star: 0 trades.
  Reason: these multi-bar formations are almost never present on the same candle
  that closes outside the BB — the BB extreme candle IS the "extreme" bar.
- Three Crows/Soldiers: 149t WR 45% / -1.6% (vs baseline 238t WR 47% +28.2%)
- Doji (as reversal): 77t WR 33% / -18.9%

Conclusion: candlestick patterns do NOT add value as BB confirmation on 1h.
They work better as standalone patterns in S/R context, not as a second filter
stacked on an already-filtered signal.

Run: python research_candles.py
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST = 0.0002
SL_M = 3.0
TP_M = 5.0
BAL = 10_000.0
RISK = 0.03
MH = 48
SPLIT = pd.Timestamp("2026-01-01")


def load_btc():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df = df.rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df):
    return df.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()


# ── Candlestick helpers ───────────────────────────────────────────────────────

def is_bullish_engulfing(df, i):
    """Bar i bullishly engulfs bar i-1."""
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i-1], df["close"].iloc[i-1]
    cur_o, cur_c   = df["open"].iloc[i],   df["close"].iloc[i]
    return (prev_c < prev_o                  # prev bearish
            and cur_c > cur_o               # cur bullish
            and cur_o <= prev_c             # opens at or below prev close
            and cur_c >= prev_o)            # closes at or above prev open


def is_bearish_engulfing(df, i):
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i-1], df["close"].iloc[i-1]
    cur_o, cur_c   = df["open"].iloc[i],   df["close"].iloc[i]
    return (prev_c > prev_o
            and cur_c < cur_o
            and cur_o >= prev_c
            and cur_c <= prev_o)


def is_morning_star(df, i):
    """Bars i-2, i-1, i form a morning star."""
    if i < 2:
        return False
    o0, c0 = df["open"].iloc[i-2], df["close"].iloc[i-2]
    o1, c1 = df["open"].iloc[i-1], df["close"].iloc[i-1]
    o2, c2 = df["open"].iloc[i],   df["close"].iloc[i]
    body0 = abs(c0 - o0); body1 = abs(c1 - o1); body2 = abs(c2 - o2)
    return (c0 < o0                          # bar0 bearish
            and body1 < body0 * 0.5          # bar1 small body (star)
            and c2 > o2                      # bar2 bullish
            and body2 > body0 * 0.5          # bar2 substantial
            and c2 > (o0 + c0) / 2)          # closes above bar0 midpoint


def is_evening_star(df, i):
    if i < 2:
        return False
    o0, c0 = df["open"].iloc[i-2], df["close"].iloc[i-2]
    o1, c1 = df["open"].iloc[i-1], df["close"].iloc[i-1]
    o2, c2 = df["open"].iloc[i],   df["close"].iloc[i]
    body0 = abs(c0 - o0); body1 = abs(c1 - o1); body2 = abs(c2 - o2)
    return (c0 > o0
            and body1 < body0 * 0.5
            and c2 < o2
            and body2 > body0 * 0.5
            and c2 < (o0 + c0) / 2)


def is_three_black_crows(df, i):
    if i < 2:
        return False
    return all(df["close"].iloc[i-k] < df["open"].iloc[i-k] for k in range(3))


def is_three_white_soldiers(df, i):
    if i < 2:
        return False
    return all(df["close"].iloc[i-k] > df["open"].iloc[i-k] for k in range(3))


def is_doji(df, i, threshold=0.1):
    """Body < threshold × full range."""
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    h, l = df["high"].iloc[i], df["low"].iloc[i]
    rng = h - l
    return rng > 0 and abs(c - o) / rng < threshold


# ── Core backtest ─────────────────────────────────────────────────────────────

def run(df_1h, candle_filter=None):
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s   = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma  = df_1h["volume"].rolling(20).mean().values
    bb_pos  = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
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

        # Candlestick filter
        if candle_filter is not None and not candle_filter(df_1h, i):
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


def stat(tt, label):
    if not tt:
        return f"{label:<40} 0 trades"
    p  = np.array([t["pnl"] for t in tt])
    wr = (p > 0).mean()
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf = pos / neg if neg > 0 else float("inf")
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd = ((pk - eq) / pk).max()
    tr  = [t for t in tt if t["ts"] < SPLIT]
    te  = [t for t in tt if t["ts"] >= SPLIT]
    tp_ = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    te_ = np.array([t["pnl"] for t in te]) if te else np.array([])
    s_tr = f"WR{(tp_ > 0).mean():.0%} ${tp_.sum():>+7.0f}" if len(tp_) else "no train"
    s_te = f"WR{(te_ > 0).mean():.0%} ${te_.sum():>+7.0f}" if len(te_) else "no test"
    return (f"{label:<40} {len(p):>3}t WR{wr:.0%} PF{pf:.2f} "
            f"${p.sum():>+8.0f} ({p.sum()/100:>+.1f}%) maxDD{dd*100:.1f}% "
            f"| TRAIN {s_tr} | TEST {s_te}")


def main():
    df    = load_btc()
    df_1h = resample(df)
    print(f"BTC 1h candles: {len(df_1h)}  ({df_1h.index[0]} → {df_1h.index[-1]})")
    print("=" * 130)

    baseline = run(df_1h, candle_filter=None)
    print(stat(baseline, "BASELINE (no candle filter)"))
    print()

    def long_engulf_or_short_engulf(df, i):
        d_raw = 1 if ((df["close"].iloc[i] - df["low"].iloc[i].item()
                       if hasattr(df["low"].iloc[i], "item") else df["low"].iloc[i])
                      < 0) else -1
        bpos_val = (
            (df["close"].iloc[i] - df["low"].iloc[i])
            / max(df["high"].iloc[i] - df["low"].iloc[i], 1e-9)
        )
        if bpos_val < 0:   # below lower band → want long → need bullish engulfing
            return is_bullish_engulfing(df, i)
        else:              # above upper band → want short → need bearish engulfing
            return is_bearish_engulfing(df, i)

    # We need to know direction to pick the right pattern; use bb_pos sign
    upper_s, _, lower_s = bollinger_bands(df_1h["close"], 20, 2.0)
    bb_pos_s = ((df_1h["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan))

    def engulf_filter(df, i):
        bpos = bb_pos_s.iloc[i]
        if np.isnan(bpos):
            return False
        if bpos < 0:
            return is_bullish_engulfing(df, i)
        else:
            return is_bearish_engulfing(df, i)

    def star_filter(df, i):
        bpos = bb_pos_s.iloc[i]
        if np.isnan(bpos):
            return False
        if bpos < 0:
            return is_morning_star(df, i)
        else:
            return is_evening_star(df, i)

    def crows_soldiers_filter(df, i):
        bpos = bb_pos_s.iloc[i]
        if np.isnan(bpos):
            return False
        if bpos < 0:
            return is_three_white_soldiers(df, i)
        else:
            return is_three_black_crows(df, i)

    tests = [
        ("Engulfing (bullish/bearish yönüne göre)",   engulf_filter),
        ("Morning Star / Evening Star",                star_filter),
        ("Three Soldiers / Three Crows",               crows_soldiers_filter),
        ("Doji (kararsızlık → reversal sinyali)",
         lambda df, i: is_doji(df, i)),
    ]

    for label, filt in tests:
        trades = run(df_1h, candle_filter=filt)
        print(stat(trades, label))

    print()
    print("Verdict: candlestick patterns at 1h BB extremes either produce zero trades")
    print("(too rare at extremes) or reduce performance. OHLCV ceiling is +28.2%.")
    print("Next real improvement requires live data: funding/OI via funding.py.")


if __name__ == "__main__":
    main()
