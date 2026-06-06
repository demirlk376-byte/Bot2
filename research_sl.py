"""
research_sl.py

SL (stop-loss) mesafesi optimizasyonu.
Mevcut: SL=3xATR, TP=5xATR  WR=47%  +28.2%

SL cok mu dar? Genis SL → daha az SL hit → daha yuksek WR, ama daha kucuk R:R.
Optimal noktayi bul.

Test: SL_M = 2.0 to 5.0 (TP_M sabit = 5.0)
Bonus: TP de degistirince ne olur?

Run: python research_sl.py
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.03
MH    = 48
SPLIT = pd.Timestamp("2026-01-01")


def load_btc():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df = df.rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df):
    return df.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()


def run(df_1h, sl_m=3.0, tp_m=5.0):
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
    n = len(c); warmup = 60
    balance = BAL; open_t = None; trades = []

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
                trades.append({
                    "ts": df_1h.index[i], "pnl": pnl,
                    "reason": reason, "ts_entry": open_t["ts"]
                })
                open_t = None
            continue

        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue

        ep = c[i]; sl_d = sl_m * a
        sl = ep - direction * sl_d
        tp = ep + direction * tp_m * a
        qty = round((balance * RISK) / (ep * (sl_d / ep)), 3)
        qty = min(qty, balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}
    return trades


def stat(tt, label):
    if not tt:
        return f"{label:<45} 0 trades"
    p  = np.array([t["pnl"] for t in tt])
    wr = (p > 0).mean()
    sl_hits  = sum(1 for t in tt if t["reason"] == "sl")
    tp_hits  = sum(1 for t in tt if t["reason"] == "tp")
    mh_hits  = sum(1 for t in tt if t["reason"] == "mh")
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf = pos / neg if neg > 0 else float("inf")
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd = ((pk - eq) / pk).max()
    tr = [t for t in tt if t["ts_entry"] < SPLIT]
    te = [t for t in tt if t["ts_entry"] >= SPLIT]
    tp_ = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    te_ = np.array([t["pnl"] for t in te]) if te else np.array([])
    s_tr = f"WR{(tp_>0).mean():.0%} ${tp_.sum():>+7.0f}" if len(tp_) else "no train"
    s_te = f"WR{(te_>0).mean():.0%} ${te_.sum():>+7.0f}" if len(te_) else "no test"
    return (
        f"{label:<45} {len(p):>3}t WR{wr:.0%} "
        f"SL:{sl_hits}({sl_hits/len(p):.0%}) TP:{tp_hits} MH:{mh_hits} "
        f"PF{pf:.2f} ${p.sum():>+8.0f} ({p.sum()/100:>+.1f}%) "
        f"DD{dd*100:.1f}% | TR {s_tr} | TE {s_te}"
    )


def main():
    df   = load_btc()
    df1h = resample(df)
    print(f"BTC 1h: {len(df1h)} bar  ({df1h.index[0]:%Y-%m-%d} → {df1h.index[-1]:%Y-%m-%d})")
    print("=" * 140)

    # ── 1. SL sweep (TP sabit = 5.0) ─────────────────────────────────────────
    print("\n[SL SWEEP — TP=5.0 sabit]\n")
    for sl in [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
        t = run(df1h, sl_m=sl, tp_m=5.0)
        mark = " ← baseline" if sl == 3.0 else ""
        print(stat(t, f"SL={sl:.1f}×ATR  TP=5.0×ATR") + mark)

    # ── 2. TP sweep (SL sabit = 3.0) ─────────────────────────────────────────
    print("\n[TP SWEEP — SL=3.0 sabit]\n")
    for tp in [3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.0]:
        t = run(df1h, sl_m=3.0, tp_m=tp)
        mark = " ← baseline" if tp == 5.0 else ""
        print(stat(t, f"SL=3.0×ATR  TP={tp:.1f}×ATR") + mark)

    # ── 3. Sabit R:R orani (1:2) ─────────────────────────────────────────────
    print("\n[SABIT R:R = 1:2 — SL ve TP birlikte artar]\n")
    for sl in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        tp = sl * 2.0
        t = run(df1h, sl_m=sl, tp_m=tp)
        mark = " ← nearest to baseline" if sl == 3.0 else ""
        print(stat(t, f"SL={sl:.1f}×ATR  TP={tp:.1f}×ATR (1:2 RR)") + mark)

    # ── 4. En iyi kombinasyon detail ─────────────────────────────────────────
    print("\n[DETAYLI KARŞILAŞTIRMA — öne çıkan kombinasyonlar]\n")
    combos = [
        (3.0, 5.0, "baseline"),
        (4.0, 5.0, "genis SL, ayni TP"),
        (4.0, 6.0, "genis SL, genis TP"),
        (3.5, 5.0, "biraz genis SL"),
        (3.0, 4.0, "ayni SL, dar TP"),
        (2.5, 5.0, "dar SL, ayni TP"),
    ]
    for sl, tp, note in combos:
        t = run(df1h, sl_m=sl, tp_m=tp)
        print(stat(t, f"SL={sl:.1f} TP={tp:.1f} [{note}]"))


if __name__ == "__main__":
    main()
