"""
research_vwap_sweep.py — Liquidity Sweep + VWAP + STDV filtreli edge testi

HİPOTEZ (social media "90% WR VWAP+LQ sweep+STDV" konseptinden):
  Klasik LQ sweep tek başına BTC/ETH'de edge vermiyor (research_liquidity_sweep.py).
  Ek filtreler:
    1. VWAP: sweep anında fiyat VWAP'ın uzak tarafında olmalı
       (long: fiyat VWAP altı → VWAP'a dönüş potansiyeli)
    2. STDV: fiyat günlük VWAP'ın ±N standart sapma dışında → aşırı gerilmiş

YÖNTEM:
  • 1h mumlar (botun ana timeframe'i)
  • Look-ahead yok: sinyal mumunun kapanışında tetiklenir
  • TRAIN (2026 öncesi) + TEST (2026+) ikisinde de PF>1.10 → gerçek edge
  • Referans: doğrulanmış 1H BB (PF ~1.18, +20%)

Run: python research_vwap_sweep.py
"""
from __future__ import annotations
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr, ema

COST  = 0.0002       # taker round-trip
BAL   = 10_000.0
RISK  = 0.02
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")


def load_1m(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m


def to_tf(df_1m, rule):
    return df_1m.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()


def score(trades, label):
    if not trades:
        return f"{label:<70}  NO TRADES"
    p  = np.array([t["pnl"] for t in trades])
    tr = [t for t in trades if t["ts"] < SPLIT]
    te = [t for t in trades if t["ts"] >= SPLIT]
    def _s(lst):
        if not lst: return "—"
        pp = np.array([t["pnl"] for t in lst])
        return f"W{(pp>0).mean():.0%} ${pp.sum():>+6.0f}"
    gp = p[p > 0].sum() if (p > 0).any() else 0
    gl = abs(p[p < 0].sum()) if (p < 0).any() else 1
    pf = gp / gl
    bal_curve = np.cumsum(p)
    dd = abs(((bal_curve - np.maximum.accumulate(bal_curve)) /
              (BAL + np.maximum.accumulate(bal_curve))).min()) * 100
    return (f"{label:<70} {len(p):>4}t WR{(p>0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f} DD{dd:.1f}% "
            f"| TR {_s(tr)} | TE {_s(te)}")


def rolling_vwap_stdv(df: pd.DataFrame, period: int = 24):
    """Rolling VWAP ve standart sapma bandı (VWAP ± N*std)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tpv = typical * df["volume"]
    vwap_vals = tpv.rolling(period).sum() / df["volume"].rolling(period).sum()
    # Standart sapma: typical fiyatın VWAP etrafındaki dağılımı
    vwap_arr = vwap_vals.values
    typ_arr  = typical.values
    std_vals = np.full(len(df), np.nan)
    for i in range(period - 1, len(df)):
        window = typ_arr[i - period + 1:i + 1]
        std_vals[i] = np.std(window, ddof=0)
    return vwap_vals.values, std_vals


def strat_vwap_sweep(
    df,
    lookback: int = 20,
    sl_buf_atr: float = 0.25,
    rr: float = 2.0,
    max_hold: int = 24,
    use_trend: bool = True,
    ema_period: int = 200,
    min_wick_atr: float = 0.0,
    vwap_period: int = 24,
    stdv_mult: float = 1.5,    # VWAP ± N*std dışında ol şartı
    require_vwap: bool = True,  # VWAP taraf filtresi
    require_stdv: bool = True,  # STDV aşırı-gerilme filtresi
):
    """
    LQ Sweep + VWAP + STDV filtreli strateji.

    Ekstra filtreler:
      require_vwap: long → fiyat VWAP altı, short → VWAP üstü
      require_stdv: fiyat VWAP ± stdv_mult*std dışında olmalı
    """
    h  = df["high"].values
    l  = df["low"].values
    c  = df["close"].values
    n  = len(c)
    at = atr(df["high"], df["low"], df["close"], 14).values
    em = ema(df["close"], ema_period).values if use_trend else np.full(n, np.nan)
    vw, sv = rolling_vwap_stdv(df, vwap_period)

    balance = BAL
    open_t  = None
    trades  = []

    warmup = max(lookback + 1, ema_period + 1 if use_trend else 15,
                 vwap_period + 1, 15)

    for i in range(warmup, n):
        # ── pozisyon yönetimi ──
        if open_t is not None:
            d = open_t["dir"]
            ep = None
            if d == 1:
                if l[i] <= open_t["sl"]:   ep = open_t["sl"]
                elif h[i] >= open_t["tp"]: ep = open_t["tp"]
            else:
                if h[i] >= open_t["sl"]:   ep = open_t["sl"]
                elif l[i] <= open_t["tp"]: ep = open_t["tp"]
            if ep is None and (i - open_t["i"]) >= max_hold:
                ep = c[i]
            if ep is not None:
                pnl = (d * (ep - open_t["entry"]) * open_t["qty"]
                       - (open_t["entry"] + ep) * open_t["qty"] * COST)
                balance += pnl
                trades.append({"ts": df.index[i], "pnl": pnl})
                open_t = None
            continue

        if np.isnan(at[i]) or at[i] <= 0:
            continue
        if use_trend and np.isnan(em[i]):
            continue
        if np.isnan(vw[i]) or np.isnan(sv[i]):
            continue

        # swing seviyeleri
        swing_low  = l[i - lookback:i].min()
        swing_high = h[i - lookback:i].max()

        direction = 0

        # Bullish sweep: düşük swing altına fitil, kapanış üstte
        if l[i] < swing_low and c[i] > swing_low:
            wick = swing_low - l[i]
            if wick >= min_wick_atr * at[i]:
                if not use_trend or c[i] > em[i]:
                    # VWAP filtresi: long → fiyat VWAP altında (reversion fuel)
                    vwap_ok = (not require_vwap) or (c[i] < vw[i])
                    # STDV filtresi: fiyat VWAP - stdv_mult*std altında
                    stdv_ok = (not require_stdv) or (c[i] < vw[i] - stdv_mult * sv[i])
                    if vwap_ok and stdv_ok:
                        direction = 1

        # Bearish sweep
        if direction == 0 and h[i] > swing_high and c[i] < swing_high:
            wick = h[i] - swing_high
            if wick >= min_wick_atr * at[i]:
                if not use_trend or c[i] < em[i]:
                    vwap_ok = (not require_vwap) or (c[i] > vw[i])
                    stdv_ok = (not require_stdv) or (c[i] > vw[i] + stdv_mult * sv[i])
                    if vwap_ok and stdv_ok:
                        direction = -1

        if direction == 0:
            continue

        entry = c[i]
        if direction == 1:
            sl   = l[i] - sl_buf_atr * at[i]
            sl_d = entry - sl
        else:
            sl   = h[i] + sl_buf_atr * at[i]
            sl_d = sl - entry
        if sl_d <= 0:
            continue
        tp  = entry + direction * rr * sl_d
        qty = min(round(balance * RISK / sl_d, 3), balance * 0.5 / entry)
        if qty < 0.001:
            continue
        open_t = {"i": i, "dir": direction, "entry": entry,
                  "sl": sl, "tp": tp, "qty": qty}
    return trades


def run_for(name, m):
    if m.empty:
        print(f"\n{name}: veri yok, atlanıyor.")
        return

    df1h = to_tf(m, "1h")
    print(f"\n{'='*120}")
    print(f"{name}  (1h bars={len(df1h)}, "
          f"{df1h.index[0].date()} → {df1h.index[-1].date()})")
    print("-" * 120)

    # Referans: doğrulanmış BB
    try:
        from research_daytrading import backtest as bt1h
        ref = bt1h(df1h, 20, 2.0, 3.0, 5.0 / 3.0, 48)
        print(score(ref, "REF 1H BB(20,2) SL3ATR RR1.67 mh48  [doğrulanmış]"))
    except Exception as e:
        print(f"REF BB çalışmadı: {e}")

    # Orijinal sweep (filtresiz) — karşılaştırma için
    from research_liquidity_sweep import strat_sweep
    t_base = strat_sweep(df1h, 20, 0.25, 2.0, 24, use_trend=True)
    print(score(t_base, "BASE Sweep lb20 SLbuf0.25 RR2.0 trend+ (filtresiz)"))
    print("-" * 120)
    print("VWAP+STDV filtreli kombinasyonlar:")
    print("-" * 120)

    best = None
    configs = [
        # (lb, slbuf, rr, trend, vwap_p, stdv_m, req_v, req_s, label)
        # Sadece VWAP filtresi
        (20, 0.25, 2.0, True,  24, 1.5, True,  False, "Sweep+VWAP lb20 RR2.0 trend+"),
        (20, 0.25, 2.0, False, 24, 1.5, True,  False, "Sweep+VWAP lb20 RR2.0 trend-"),
        (10, 0.25, 2.0, True,  24, 1.5, True,  False, "Sweep+VWAP lb10 RR2.0 trend+"),
        (30, 0.25, 2.0, True,  24, 1.5, True,  False, "Sweep+VWAP lb30 RR2.0 trend+"),
        # VWAP + STDV 1.0σ
        (20, 0.25, 2.0, True,  24, 1.0, True,  True,  "Sweep+VWAP+STDV1.0 lb20 RR2.0"),
        (20, 0.25, 2.5, True,  24, 1.0, True,  True,  "Sweep+VWAP+STDV1.0 lb20 RR2.5"),
        (10, 0.25, 2.0, True,  24, 1.0, True,  True,  "Sweep+VWAP+STDV1.0 lb10 RR2.0"),
        (30, 0.25, 2.0, True,  24, 1.0, True,  True,  "Sweep+VWAP+STDV1.0 lb30 RR2.0"),
        # VWAP + STDV 1.5σ
        (20, 0.25, 2.0, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb20 RR2.0"),
        (20, 0.25, 2.5, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb20 RR2.5"),
        (20, 0.25, 3.0, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb20 RR3.0"),
        (10, 0.25, 2.0, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb10 RR2.0"),
        (30, 0.25, 2.0, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb30 RR2.0"),
        (50, 0.25, 2.0, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb50 RR2.0"),
        # STDV 2.0σ (daha seçici)
        (20, 0.25, 2.0, True,  24, 2.0, True,  True,  "Sweep+VWAP+STDV2.0 lb20 RR2.0"),
        (20, 0.25, 2.5, True,  24, 2.0, True,  True,  "Sweep+VWAP+STDV2.0 lb20 RR2.5"),
        (10, 0.25, 2.0, True,  24, 2.0, True,  True,  "Sweep+VWAP+STDV2.0 lb10 RR2.0"),
        # VWAP periyodu değişimi
        (20, 0.25, 2.0, True,  12, 1.5, True,  True,  "Sweep+VWAP12+STDV1.5 lb20 RR2.0"),
        (20, 0.25, 2.0, True,  48, 1.5, True,  True,  "Sweep+VWAP48+STDV1.5 lb20 RR2.0"),
        # min wick filtresi ekleme
        (20, 0.25, 2.0, True,  24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5+wick0.3 lb20"),
        # trend filtresi kapalı + STDV
        (20, 0.25, 2.0, False, 24, 1.5, True,  True,  "Sweep+VWAP+STDV1.5 lb20 trend-"),
        (20, 0.25, 2.0, False, 24, 2.0, True,  True,  "Sweep+VWAP+STDV2.0 lb20 trend-"),
    ]

    for lb, slb, rr, tr, vp, sm, rv, rs, lbl in configs:
        mw = 0.3 if "wick0.3" in lbl else 0.0
        t = strat_vwap_sweep(
            df1h, lookback=lb, sl_buf_atr=slb, rr=rr,
            max_hold=24, use_trend=tr, vwap_period=vp,
            stdv_mult=sm, require_vwap=rv, require_stdv=rs,
            min_wick_atr=mw,
        )
        line = score(t, lbl)
        print(line)

        if t:
            p  = np.array([x["pnl"] for x in t])
            tr_t = [x for x in t if x["ts"] < SPLIT]
            te_t = [x for x in t if x["ts"] >= SPLIT]
            if tr_t and te_t and len(p) >= 20:
                tr_pos = sum(x["pnl"] for x in tr_t) > 0
                te_pos = sum(x["pnl"] for x in te_t) > 0
                gp = p[p > 0].sum() if (p > 0).any() else 0
                gl = abs(p[p < 0].sum()) if (p < 0).any() else 1
                pf = gp / gl
                if tr_pos and te_pos and pf > 1.10:
                    if best is None or pf > best[0]:
                        best = (pf, lbl, p.sum(), len(p))

    print("-" * 120)
    if best:
        print(f"\n>>> {name} EN İYİ (TR+TE pozitif, PF>1.10, ≥20 trade):")
        print(f"    {best[1]}  PF{best[0]:.2f}  ${best[2]:+.0f}  {best[3]}t")
    else:
        print(f"\n>>> {name}: VWAP+STDV filtresiyle de TR+TE ikisinde pozitif config YOK.")
        print(f"    → Strateji BTC için güvenilir edge taşımıyor.")


def main():
    print("Veri yükleniyor…")
    btc = load_1m("/home/user/Bot2/BTCUSDT-1m-*.csv")
    eth = load_1m("/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv")

    run_for("BTC", btc)
    run_for("ETH", eth)

    print("\n" + "=" * 120)
    print("KARAR KRİTERİ: BTC+ETH ikisinde de TR+TE pozitif & PF>1.10 → deploy")
    print("              Aksi halde overfit — bota eklenmez.")


if __name__ == "__main__":
    main()
