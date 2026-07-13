"""
research_spread.py — ETH/BTC oran (spread) mean-reversion: PİYASA-NÖTR aile.

NEDEN BU AİLE: portföydeki 7 sleeve'in tamamı YÖNLÜ — BTC çakılırsa hepsi aynı
fırtınayı yer. Oran ticareti (long ETH + short BTC ya da tersi, eşit notional)
piyasa yönünü nötrler: kazanç yalnız İKİ COİN ARASINDAKİ makasın kapanmasından
gelir. Geçerse portföye ilk gerçek çeşitlendirici sleeve olur.

HİPOTEZ (ön-kayıtlı): ETH/BTC oranı kısa vadede aşırı gerilir ve ortalamaya
döner. Oranın z-skoru |z| >= Z_ENTRY iken makasa karşı gir; |z| <= Z_EXIT'te
(ortalamaya dönüş) ya da SL/max-hold'da çık.

MEKANİK:
  ratio  = ETH_close / BTC_close (1h)
  z      = (ratio - SMA(ratio, N)) / STD(ratio, N)
  GİRİŞ  : z <= -Z → long spread (ETH al, BTC sat); z >= +Z → short spread
  ÇIKIŞ  : |z| <= Z_EXIT (dönüş) | spread PnL <= -SL_PCT (stop) | MAX_HOLD saat
  PnL    : eşit notional iki bacak, bacak başına taker fee (muhafazakâr:
           %0.01 × 4 bacak-işlem = round-trip %0.04 toplam notional)

ÖN-KAYITLI KABUL ÇITASI (test-tuning YOK — grid komşuluğu dahil):
  TRAIN (2023-24) PF >= 1.2  VE  TEST (2025-26) PF >= 1.2  VE  n >= 50
  VE komşu (N, Z) hücrelerinde yön tutarlı. Geçerse → paper-forward izleme;
  orada da yaşarsa → küçük canlı sleeve tasarımı. Aksi halde mühürlenir.

Kullanım (VPS — veriyi kendisi indirir):
  venv/bin/python research_spread.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_strategies_crosscoin import load_data   # binance vision 1h loader

YEARS   = [2023, 2024, 2025, 2026]
SPLIT   = pd.Timestamp("2025-01-01", tz="UTC")
FEE_LEG = 0.0001          # taker, bacak başına (giriş 2 + çıkış 2 = 4 bacak)
SL_PCT  = 0.04            # spread PnL stop: toplam notional'ın -%4'ü
MAX_HOLD = 24 * 7         # 7 gün (1h bar)

# Ön-kayıtlı grid — komşuluk tutarlılığı için 3×3
GRID_N = [120, 240, 480]          # z-skor penceresi (saat): 5g / 10g / 20g
GRID_Z = [2.0, 2.5, 3.0]          # giriş eşiği
Z_EXIT = 0.5                      # ortalamaya dönüş çıkışı


def run(ratio: pd.Series, N: int, Z: float) -> list[dict]:
    r = ratio.values
    idx = ratio.index
    ma = ratio.rolling(N).mean().values
    sd = ratio.rolling(N).std(ddof=0).values
    n = len(r)
    trades: list[dict] = []
    pos = 0          # +1 long spread (ETH>BTC beklenir), -1 short
    e_i = -1
    for i in range(N, n):
        if sd[i] <= 0 or np.isnan(sd[i]):
            continue
        z = (r[i] - ma[i]) / sd[i]
        if pos == 0:
            if z <= -Z:
                pos, e_i = 1, i
            elif z >= Z:
                pos, e_i = -1, i
            continue
        # açık pozisyon: spread PnL (eşit notional, oran değişimi ~ bacak farkı)
        pnl_pct = pos * (r[i] / r[e_i] - 1.0)
        held = i - e_i
        exit_reason = None
        if pnl_pct <= -SL_PCT:
            exit_reason = "sl"
        elif abs(z) <= Z_EXIT:
            exit_reason = "revert"
        elif held >= MAX_HOLD:
            exit_reason = "mh"
        if exit_reason:
            net = pnl_pct - 4 * FEE_LEG
            trades.append({"pnl": net, "year": idx[i].year,
                           "ts": idx[e_i], "reason": exit_reason, "held": held})
            pos = 0
    return trades


def stats(tr: list[dict]) -> dict:
    if not tr:
        return {"n": 0, "pf": 0.0, "wr": 0.0, "tot": 0.0}
    p = [t["pnl"] for t in tr]
    gp = sum(x for x in p if x > 0)
    gl = -sum(x for x in p if x < 0)
    return {"n": len(p), "pf": (gp / gl) if gl > 0 else 9.99,
            "wr": sum(1 for x in p if x > 0) / len(p), "tot": sum(p)}


def main() -> None:
    print("ETH ve BTC 1h verisi yükleniyor (2023-2026)...")
    eth = load_data("ETHUSDT", YEARS)["close"]
    btc = load_data("BTCUSDT", YEARS)["close"]
    df = pd.concat({"eth": eth, "btc": btc}, axis=1).dropna()
    ratio = df["eth"] / df["btc"]
    print(f"{len(ratio)} ortak 1h bar ({ratio.index[0].date()} → {ratio.index[-1].date()})")

    print("\n" + "=" * 76)
    print("  ETH/BTC SPREAD MEAN-REVERSION — piyasa-nötr aile taraması")
    print("  (pnl birimi: toplam notional yüzdesi; 4 bacak taker fee düşülmüş)")
    print("=" * 76)
    print(f"  {'N':>4} {'Z':>4} | {'TRAIN n':>7} {'PF':>5} {'WR':>4} {'tot%':>7} | "
          f"{'TEST n':>6} {'PF':>5} {'WR':>4} {'tot%':>7} | karar")
    print("  " + "-" * 72)
    passed = 0
    for N in GRID_N:
        for Z in GRID_Z:
            tr = run(ratio, N, Z)
            a = stats([t for t in tr if t["ts"] < SPLIT])
            b = stats([t for t in tr if t["ts"] >= SPLIT])
            ok = (a["pf"] >= 1.2 and b["pf"] >= 1.2 and (a["n"] + b["n"]) >= 50)
            passed += ok
            print(f"  {N:>4} {Z:>4.1f} | {a['n']:>7} {a['pf']:>5.2f} {a['wr']:>4.0%} "
                  f"{a['tot']*100:>+6.1f}% | {b['n']:>6} {b['pf']:>5.2f} {b['wr']:>4.0%} "
                  f"{b['tot']*100:>+6.1f}% | {'PASS' if ok else 'no'}")

    print("\n  ÖN-KAYITLI KARAR: 9 hücreden >=4 PASS ve PASS'ler komşu (tek şanslı")
    print("  hücre değil) → paper-forward izlemeye alınır. Aksi halde AİLE MÜHÜRLENİR.")
    print(f"  Sonuç: {passed}/9 PASS")


if __name__ == "__main__":
    main()
