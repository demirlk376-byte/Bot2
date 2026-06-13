"""
research_daytrading.py — Kısa vadeli BB mean reversion edge testi.

1m veriyi 5m ve 15m'e aggregate edip BB + hacim filtresi uygular.
Dürüst metodoloji: 2025-05 → 2025-12 = TRAIN, 2026-01+ = TEST.
Her parametre seti her iki periyotta tutarlı ise edge var demek.

Run: python research_daytrading.py
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import bollinger_bands, atr

COST    = 0.0002   # 0.01% maker her iki taraf
BAL     = 10_000.0
RISK    = 0.02     # %2 risk/trade (muhafazakar)
SPLIT   = pd.Timestamp("2026-01-01", tz="UTC")


def load_1m() -> pd.DataFrame:
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m


def resample_to(df_1m: pd.DataFrame, tf: str) -> pd.DataFrame:
    return df_1m.resample(tf).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


def backtest(df: pd.DataFrame, bb_period: int, bb_std: float,
             sl_mult: float, rr: float, max_hold: int,
             vol_filter: bool = True) -> list[dict]:
    c   = df["close"].values
    h   = df["high"].values
    lo  = df["low"].values
    vol = df["volume"].values

    upper, _, lower = bollinger_bands(df["close"], bb_period, bb_std)
    atr_s  = atr(df["high"], df["low"], df["close"], 14)
    vol_ma = df["volume"].rolling(20).mean().values
    band_w = (upper - lower).values
    bb_pos = ((df["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    n = len(c); balance = BAL; open_t = None; trades = []
    for i in range(max(bb_period + 14, 30), n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0 or np.isnan(band_w[i]) or band_w[i] <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]
            ep = None; reason = None
            held = i - open_t["i"]
            if d == 1:
                if lo[i] <= sl: ep, reason = sl, "sl"
                elif h[i] >= tp: ep, reason = tp, "tp"
            else:
                if h[i] >= sl: ep, reason = sl, "sl"
                elif lo[i] <= tp: ep, reason = tp, "tp"
            if ep is None and held >= max_hold: ep, reason = c[i], "mh"
            if ep is not None:
                pnl = d*(ep-entry)*qty - (entry+ep)*qty*COST
                balance += pnl
                trades.append({"ts": df.index[i], "pnl": pnl,
                               "reason": reason, "dir": d})
                open_t = None
            continue

        bp = bb_pos[i]
        if np.isnan(bp) or not (bp < 0 or bp > 1):
            continue
        if vol_filter and (np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]):
            continue
        direction = 1 if bp < 0 else -1
        ep = c[i]
        sl_d = sl_mult * a
        sl = ep - direction * sl_d
        tp = ep + direction * rr * sl_d
        qty = min(round(balance * RISK / (ep * sl_d / ep), 3), balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "dir": direction, "entry": ep, "sl": sl,
                  "tp": tp, "qty": qty}
    return trades


def score(trades: list[dict], label: str) -> str:
    if not trades:
        return f"{label:<50}  NO TRADES"
    p    = np.array([t["pnl"] for t in trades])
    tr   = [t for t in trades if t["ts"] < SPLIT]
    te   = [t for t in trades if t["ts"] >= SPLIT]
    pnl_tr = sum(t["pnl"] for t in tr) if tr else 0
    pnl_te = sum(t["pnl"] for t in te) if te else 0
    wr_tr  = (np.array([t["pnl"] for t in tr]) > 0).mean() if tr else 0
    wr_te  = (np.array([t["pnl"] for t in te]) > 0).mean() if te else 0
    wins   = (p > 0).mean()
    total  = p.sum()
    gross_p = p[p > 0].sum() if (p > 0).any() else 0
    gross_l = abs(p[p < 0].sum()) if (p < 0).any() else 1
    pf     = gross_p / gross_l if gross_l > 0 else 0
    bal    = np.cumsum(p)
    dd     = ((bal - np.maximum.accumulate(bal)) / (BAL + np.maximum.accumulate(bal))).min()
    # per-day trade count
    days = max((trades[-1]["ts"] - trades[0]["ts"]).days, 1)
    tpd  = len(p) / days
    return (f"{label:<50} {len(p):>4}t "
            f"WR{wins:.0%} PF{pf:.2f} ${total:>+7.0f}({total/100:>+5.1f}%) "
            f"DD{abs(dd)*100:.1f}% tpd={tpd:.1f} "
            f"| TR W{wr_tr:.0%} ${pnl_tr:>+6.0f} "
            f"| TE W{wr_te:.0%} ${pnl_te:>+6.0f}")


def main():
    print("Veri yükleniyor…")
    m = load_1m()
    print(f"1m: {len(m)} bar  ({m.index[0]:%Y-%m-%d} → {m.index[-1]:%Y-%m-%d})")

    df5  = resample_to(m, "5min")
    df15 = resample_to(m, "15min")
    df30 = resample_to(m, "30min")
    print(f"Aggregate: 5m={len(df5)} 15m={len(df15)} 30m={len(df30)}\n")

    # Referans: 1h BB (daha önce doğrulanmış)
    print("=== REFERANS 1H BB (doğrulanmış edge) ===")
    df1h = resample_to(m, "1h")
    ref  = backtest(df1h, 20, 2.0, 3.0, 5.0/3.0, 48)
    print(score(ref, "1H BB(20,2) SL3ATR TP5ATR mh48"))

    configs = [
        # (tf_label, df, bb_p, bb_std, sl_m, rr, max_hold, vol_filter)
        ("5m",  df5,  20, 2.0, 2.0, 2.0, 12, True),
        ("5m",  df5,  20, 2.0, 2.0, 3.0, 12, True),
        ("5m",  df5,  20, 2.0, 3.0, 5.0/3.0, 12, True),
        ("5m",  df5,  20, 2.0, 3.0, 2.0, 12, True),
        ("5m",  df5,  50, 2.0, 2.0, 2.0, 24, True),
        ("5m",  df5,  50, 2.0, 2.5, 2.0, 24, True),
        ("5m",  df5,  20, 2.5, 2.0, 2.0, 12, True),
        ("5m",  df5,  20, 2.0, 2.0, 2.0, 12, False),  # no vol filter
        ("15m", df15, 20, 2.0, 2.0, 2.0, 8, True),
        ("15m", df15, 20, 2.0, 2.0, 3.0, 8, True),
        ("15m", df15, 20, 2.0, 3.0, 5.0/3.0, 8, True),
        ("15m", df15, 20, 2.0, 3.0, 2.0, 8, True),
        ("15m", df15, 50, 2.0, 2.0, 2.0, 16, True),
        ("15m", df15, 20, 2.5, 2.0, 2.0, 8, True),
        ("30m", df30, 20, 2.0, 2.0, 2.0, 4, True),
        ("30m", df30, 20, 2.0, 3.0, 5.0/3.0, 4, True),
    ]

    print("\n=== KISA VADELI TEST ===")
    print(f"{'Konfig':<50} {'Trades':>5} {'WR':>4} {'PF':>5} {'PnL':>12} {'DD':>6} {'t/gün':>6} {'TR':>16} {'TE':>16}")
    print("-"*130)

    results = []
    for tf, df, bp, bs, sl, rr, mh, vf in configs:
        trades = backtest(df, bp, bs, sl, rr, mh, vf)
        lbl = f"{tf} BB({bp},{bs}) SL{sl:.1f}ATR RR{rr:.1f} mh{mh} {'vol' if vf else 'noVol'}"
        line = score(trades, lbl)
        te_pnl = sum(t["pnl"] for t in trades if t["ts"] >= SPLIT)
        results.append((te_pnl, line, trades))
        print(line)

    print("\n=== EN İYİ 3 (TEST PnL'e göre) ===")
    for _, line, _ in sorted(results, key=lambda x: x[0], reverse=True)[:3]:
        print(line)
    print()
    print("YORUM: TR ve TE'de tutarlı WR>45% ve PF>1.10 olan config → gerçek edge.")
    print("       Sadece birinde iyi ise → gürültü. 1H referansı geçemeyen config → gereksiz.")


if __name__ == "__main__":
    main()
