"""
research_sr.py — Support/Resistance breakout edge testi.

Kodda hazır ama devre dışı olan S/R breakout stratejisini (strategies/breakout.py
+ indicators.find_sr_levels) backtest'ler. Canlıya eklemeden önce gerçek edge'i
olup olmadığını görmek için.

Mantık (breakout.py'yi sadeleştirerek birebir taklit eder):
  • find_sr_levels: son `lookback` mumun swing high/low'larını cluster'la,
    `min_touches`+ dokunuş olanları seviye say.
  • Bullish breakout: close > direnç + %0.2 VE önceki close <= direnç.
  • Bearish breakout: close < destek − %0.2 VE önceki close >= destek.
  • Opsiyonel hacim filtresi (>1.5× ortalama) ve body_ratio>0.6 onayı.
  • SL = entry ∓ sl_mult×ATR,  TP = entry ± rr×sl_mult×ATR.
  • Aynı anda tek pozisyon; kapanınca yeni kırılımda tekrar girebilir.

Dürüst metodoloji: 2025-05→12 = TRAIN, 2026-01→ = TEST.
Her iki periyotta PF>1.10 ve TR+TE pozitif → gerçek edge.

Run: python research_sr.py
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr, find_sr_levels, is_volume_spike

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.02
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")


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


def to_tf(df_1m, rule):
    return df_1m.resample(rule).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def score(trades, label):
    if not trades:
        return f"{label:<54}  NO TRADES"
    p   = np.array([t["pnl"] for t in trades])
    tr  = [t for t in trades if t["ts"] < SPLIT]
    te  = [t for t in trades if t["ts"] >= SPLIT]
    def _s(lst):
        if not lst: return "—"
        pp = np.array([t["pnl"] for t in lst])
        return f"W{(pp>0).mean():.0%} ${pp.sum():>+6.0f}"
    gp = p[p>0].sum() if (p>0).any() else 0
    gl = abs(p[p<0].sum()) if (p<0).any() else 1
    pf = gp/gl
    bal = np.cumsum(p)
    dd  = abs(((bal-np.maximum.accumulate(bal))/(BAL+np.maximum.accumulate(bal))).min())*100
    days = max((trades[-1]["ts"]-trades[0]["ts"]).days,1)
    return (f"{label:<54} {len(p):>4}t WR{(p>0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f}({p.sum()/100:>+5.1f}%) DD{dd:.1f}% tpd={len(p)/days:.1f} "
            f"| TR {_s(tr)} | TE {_s(te)}")


def strat_sr_breakout(df, lookback, min_touches, sl_mult, rr, max_hold,
                      vol_filter=True, body_filter=True):
    """S/R breakout on the given timeframe. Walk-forward, one position at a time."""
    c   = df["close"].values
    h   = df["high"].values
    lo  = df["low"].values
    o   = df["open"].values
    atr_s = atr(df["high"], df["low"], df["close"], 14).values
    vspk  = is_volume_spike(df["volume"], 20, 1.5).values
    n = len(c)
    balance = BAL; open_t = None; trades = []

    start = max(lookback + 5, 30)
    for i in range(start, n):
        a = atr_s[i]
        if np.isnan(a) or a <= 0:
            continue

        # manage open position
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]; ep = None
            held = i - open_t["i"]
            if d == 1:
                if lo[i] <= open_t["sl"]: ep = open_t["sl"]
                elif h[i] >= open_t["tp"]: ep = open_t["tp"]
            else:
                if h[i] >= open_t["sl"]: ep = open_t["sl"]
                elif lo[i] <= open_t["tp"]: ep = open_t["tp"]
            if ep is None and held >= max_hold: ep = c[i]
            if ep is not None:
                pnl = d*(ep-entry)*open_t["qty"] - (entry+ep)*open_t["qty"]*COST
                balance += pnl
                trades.append({"ts": df.index[i], "pnl": pnl})
                open_t = None
            continue

        # detect breakout on the just-closed bar i
        window = df.iloc[i - lookback : i + 1]
        levels = find_sr_levels(window, lookback=lookback, min_touches=min_touches)
        if not levels:
            continue

        cur = c[i]; prev = c[i-1]
        min_break = cur * 0.002
        direction = 0
        for lvl in levels:
            lp = lvl.price
            if lvl.level_type == "resistance" and cur > lp + min_break and prev <= lp:
                direction = 1; break
            if lvl.level_type == "support" and cur < lp - min_break and prev >= lp:
                direction = -1; break
        if direction == 0:
            continue

        if vol_filter and not vspk[i]:
            continue
        if body_filter:
            crange = h[i] - lo[i]
            body = abs(c[i] - o[i])
            if crange <= 0 or body / crange <= 0.6:
                continue

        entry = cur; sl_d = sl_mult * a
        sl = entry - direction * sl_d
        tp = entry + direction * rr * sl_d
        qty = min(round(balance*RISK/(entry*sl_d/entry), 3), balance*0.5/entry)
        if qty < 0.001:
            continue
        open_t = {"i": i, "dir": direction, "entry": entry, "sl": sl, "tp": tp, "qty": qty}
    return trades


def main():
    print("Veri yükleniyor…")
    m = load_1m()
    df1h = to_tf(m, "1h")
    df4h = to_tf(m, "4h")
    print(f"1h={len(df1h)} 4h={len(df4h)}  ({m.index[0]:%Y-%m-%d} → {m.index[-1]:%Y-%m-%d})\n")

    print("="*130)
    print("REFERANS: 1h BB (doğrulanmış edge, PF~1.24 +%28)")
    from research_daytrading import backtest as bt1h
    ref = bt1h(df1h, 20, 2.0, 3.0, 5.0/3.0, 48)
    print(score(ref, "1H BB(20,2) SL3ATR TP1.67 mh48"))

    print("\n" + "="*130)
    print("S/R BREAKOUT — 1h timeframe")
    print("-"*130)
    for lb in [50, 80]:
        for mt in [2, 3]:
            for sl in [2.0, 3.0]:
                for rr in [1.5, 2.0, 3.0]:
                    t = strat_sr_breakout(df1h, lb, mt, sl, rr, max_hold=48,
                                          vol_filter=True, body_filter=True)
                    lbl = f"1h SR lb{lb} touch{mt} SL{sl:.1f}ATR RR{rr:.1f} vol+body"
                    print(score(t, lbl))

    print("\n" + "="*130)
    print("S/R BREAKOUT — 1h, filtre yok (ham kırılım)")
    print("-"*130)
    for sl in [2.0, 3.0]:
        for rr in [1.5, 2.0, 3.0]:
            t = strat_sr_breakout(df1h, 50, 2, sl, rr, max_hold=48,
                                  vol_filter=False, body_filter=False)
            lbl = f"1h SR lb50 touch2 SL{sl:.1f}ATR RR{rr:.1f} noFilter"
            print(score(t, lbl))

    print("\n" + "="*130)
    print("S/R BREAKOUT — 4h timeframe")
    print("-"*130)
    for lb in [40, 60]:
        for mt in [2, 3]:
            for sl in [2.0, 3.0]:
                for rr in [1.5, 2.0, 3.0]:
                    t = strat_sr_breakout(df4h, lb, mt, sl, rr, max_hold=24,
                                          vol_filter=True, body_filter=True)
                    lbl = f"4h SR lb{lb} touch{mt} SL{sl:.1f}ATR RR{rr:.1f} vol+body"
                    print(score(t, lbl))

    print("\n" + "="*130)
    print("YORUM: PF>1.10 ve TR+TE ikisinde de pozitif → gerçek edge, eklemeye değer.")
    print("       1H BB referansını geçemiyorsa → boş yere karmaşıklık, ekleme.")


if __name__ == "__main__":
    main()
