"""
benchmark_recent.py — "Kötü giden biz miyiz, piyasa mı?" kıyası.

Canlı botun işlem yaptığı pencereyi (temiz epoch 2026-06-29 → şimdi) borsadan
çeker ve DOĞRULANMIŞ modelleri aynen üzerinde koşar:

  • BB mean-rev : ÜRETİM sınıfı (MeanReversionStrategy, sniper dahil) +
                  parite-referansı fill mantığı (SL önce, max-hold 48h).
                  Canlı allowlist coin'lerinde (BTC/ETH/SOL).
  • ORB         : doğrulanmış model (14:00 UTC aralığı, SL=range, TP=2R, 6h,
                  gün başına 1 trade) — 5 coin.

Çıktı: pencere içinde modelin R-cinsinden ve ~$ beklentisi vs canlının
gerçekleşen sonucu. Model de eksideyse → rejim kaybettiriyor, canlı normal.
Model artıda / canlı eksideyse → fark hâlâ bizde (varyans + düzeltilen hatalar).

Kullanım (VPS):  venv/bin/python benchmark_recent.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from indicators import atr as atr_fn
from strategies.mean_reversion import MeanReversionStrategy
from config import StrategyConfig

EPOCH = pd.Timestamp("2026-06-29", tz="UTC")
BB_COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
ORB_COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
RISK_PCT = 0.025          # canlı: %2 × RISK_SCALE 1.25
BAL = 190.0               # ~canlı hesap (yalnız $ ölçeği için)


def fetch_1h(symbol: str, days: int = 40) -> pd.DataFrame:
    import ccxt
    ex = ccxt.mexc()
    since = int((datetime.now(timezone.utc).timestamp() - days * 86400) * 1000)
    rows = []
    while True:
        batch = ex.fetch_ohlcv(symbol, "1h", since=since, limit=500)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 500:
            break
        since = batch[-1][0] + 1
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop(columns=["ts"]).astype(float)
    return df.iloc[:-1]  # forming bar


def run_bb(df: pd.DataFrame) -> list[float]:
    """Üretim BB sınıfı + parite fill mantığı. R-listesi döner (epoch sonrası)."""
    strat = MeanReversionStrategy(StrategyConfig())
    atr_s = atr_fn(df["high"], df["low"], df["close"], 14)
    h = df["high"].values; lo = df["low"].values; c = df["close"].values
    idx = df.index
    n = len(df)
    rs: list[float] = []
    ot = None
    for i in range(60, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if ot is not None:
            d, e, sl, tp, i0 = ot
            ep = None
            if d == 1:
                if lo[i] <= sl: ep = sl
                elif h[i] >= tp: ep = tp
            else:
                if h[i] >= sl: ep = sl
                elif lo[i] <= tp: ep = tp
            if ep is None and (i - i0) >= 48:
                ep = c[i]
            if ep is not None:
                rs.append(d * (ep - e) / abs(e - sl))
                ot = None
            continue
        sig = strat.analyze(df.iloc[: i + 1])
        if sig.direction != 0 and idx[i] >= EPOCH:
            e = c[i]; sld = 3.0 * a
            ot = (sig.direction, e, e - sig.direction * sld,
                  e + sig.direction * (5.0 / 3.0) * sld, i)
    return rs


def run_orb(df: pd.DataFrame) -> list[float]:
    h = df["high"].values; lo = df["low"].values; c = df["close"].values
    idx = df.index
    hours = idx.hour
    dates = idx.normalize()
    n = len(df)
    orb = {}
    for j in range(n):
        if hours[j] == 14:
            orb[dates[j]] = (h[j], lo[j])
    rs: list[float] = []
    traded = set()
    i = 60
    while i < n:
        d0 = dates[i]
        if (idx[i] >= EPOCH and hours[i] > 14 and d0 not in traded and d0 in orb):
            oh, ol = orb[d0]
            rng = oh - ol
            if rng > 0:
                dr = 0
                if c[i] > oh: dr, e, sl, tp = 1, oh, ol, oh + 2 * rng
                elif c[i] < ol: dr, e, sl, tp = -1, ol, oh, ol - 2 * rng
                if dr != 0:
                    traded.add(d0)
                    ep = None
                    for k in range(i + 1, min(i + 7, n)):
                        if dr == 1:
                            if lo[k] <= sl: ep = sl; break
                            if h[k] >= tp: ep = tp; break
                        else:
                            if h[k] >= sl: ep = sl; break
                            if lo[k] <= tp: ep = tp; break
                    if ep is None:
                        ep = c[min(i + 6, n - 1)]
                    rs.append(dr * (ep - e) / rng)
                    i = min(i + 6, n - 1)
        i += 1
    return rs


def summarize(name: str, rs: list[float]) -> float:
    if not rs:
        print(f"  {name:<18s} n=0")
        return 0.0
    a = np.array(rs)
    wr = (a > 0).mean()
    usd = a.sum() * BAL * RISK_PCT
    print(f"  {name:<18s} n={len(a):<3d} WR={wr:4.0%}  toplam={a.sum():+6.2f}R  ≈${usd:+7.2f}")
    return usd


def main() -> None:
    print("=" * 70)
    print(f"  MODEL vs PİYASA — pencere: {EPOCH.date()} → bugün (canlı temiz epoch)")
    print(f"  ($ ölçeği: ~${BAL:.0f} hesap, %{RISK_PCT*100:.1f} risk — kıyas amaçlı)")
    print("=" * 70)
    total = 0.0
    print("\n  [BB mean-rev — üretim sınıfı, canlı allowlist]")
    for sym in BB_COINS:
        try:
            df = fetch_1h(sym)
            total += summarize(sym.split("/")[0], run_bb(df))
        except Exception as e:
            print(f"  {sym}: veri hatası: {e}")
    print("\n  [ORB — doğrulanmış model, 5 coin]")
    for sym in ORB_COINS:
        try:
            df = fetch_1h(sym)
            total += summarize(sym.split("/")[0], run_orb(df))
        except Exception as e:
            print(f"  {sym}: veri hatası: {e}")
    print("\n" + "-" * 70)
    print(f"  MODELİN BU PENCEREDEKİ TOPLAMI: ≈ ${total:+.2f}")
    print("  Kıyas: canlının aynı penceredeki gerçekleşen net PnL'i (live_report).")
    print("  Model de eksideyse → rejim; model artıdaysa → fark bizdeydi")
    print("  (varyans + bu hafta düzeltilen 20 hata).")
    print("-" * 70)


if __name__ == "__main__":
    main()
