"""
research_tsm.py — Günlük zaman-serisi momentum (TSM) ailesi. Sprint #2.

NEDEN BU AİLE: mevcut sleeve'lerin tamamı saatlik frekansta çalışır. Günlük
TSM ("son N gün yükseldiyse yarın da yükselir") akademik literatürün en eski
anomalilerinden ve frekansı farklı olduğu için 1h sleeve'leriyle korelasyonu
düşük olur. Kripto'da 2017-2021 döneminde güçlüydü — hâlâ yaşıyor mu?

MEKANİK (ön-kayıtlı):
  Sinyal : günlük kapanışta, son LB günün getirisi > +T → LONG,  < -T → SHORT
           (T = eşik; 0 ya da günlük vol'ün katı). Aradaysa FLAT.
  Pozisyon: işaret değişene ya da FLAT'e dönene kadar tut (günlük rebalans yok,
           flip başına 2 taker bacağı fee).
  Coin   : BTC ana karar verisi; ETH bağımsız doğrulama kolonu.

ÖN-KAYITLI KABUL ÇITASI:
  BTC'de TRAIN(2023-24) PF >= 1.2 VE TEST(2025-26) PF >= 1.2 VE flip-n >= 50,
  >= 3 KOMŞU hücrede; VE o hücrelerin en az yarısı ETH'de de iki dönemde
  PF >= 1.0. Geçerse paper-forward; geçmezse AİLE MÜHÜRLENİR.

Kullanım (VPS):  venv/bin/python research_tsm.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_strategies_crosscoin import load_data

YEARS = [2023, 2024, 2025, 2026]
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
FEE_LEG = 0.0001            # taker per leg; flip = çıkış+giriş = 2 bacak

GRID_LB = [3, 5, 7, 14]     # momentum penceresi (gün)
GRID_T  = [0.0, 0.5, 1.0]   # eşik: günlük vol'ün katı (0 = saf işaret)


def daily(sym: str) -> pd.DataFrame:
    df = load_data(sym, YEARS)
    return df.resample("1D").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"}).dropna()


def run(d: pd.DataFrame, lb: int, t_mult: float) -> list[dict]:
    c = d["close"].values
    idx = d.index
    ret1 = pd.Series(c).pct_change()
    vol = ret1.rolling(30).std().values          # 30g günlük vol
    n = len(c)
    trades: list[dict] = []
    pos = 0
    e_i = -1
    for i in range(max(lb, 30), n - 1):
        mom = c[i] / c[i - lb] - 1.0
        thr = t_mult * (vol[i] if not np.isnan(vol[i]) else 0.0)
        want = 1 if mom > thr else (-1 if mom < -thr else 0)
        if want != pos:
            if pos != 0:   # kapat
                pnl = pos * (c[i] / c[e_i] - 1.0) - 2 * FEE_LEG
                trades.append({"pnl": pnl, "ts": idx[e_i], "held": i - e_i})
            pos = want
            e_i = i if want != 0 else -1
    if pos != 0 and e_i >= 0:
        pnl = pos * (c[-1] / c[e_i] - 1.0) - 2 * FEE_LEG
        trades.append({"pnl": pnl, "ts": idx[e_i], "held": n - 1 - e_i})
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
    print("BTC + ETH günlük veri (2023-2026)...")
    b = daily("BTCUSDT")
    e = daily("ETHUSDT")
    print(f"BTC {len(b)}g, ETH {len(e)}g")

    print("\n" + "=" * 88)
    print("  GÜNLÜK TSM — BTC karar / ETH doğrulama  (pnl: notional %, flip fee dahil)")
    print("=" * 88)
    print(f"  {'LB':>3} {'T':>4} | {'BTC-TR n':>8} {'PF':>5} {'tot%':>7} | "
          f"{'BTC-TE n':>8} {'PF':>5} {'tot%':>7} | {'ETH TR/TE PF':>13} | karar")
    print("  " + "-" * 84)
    passed = 0
    for lb in GRID_LB:
        for t in GRID_T:
            trb = run(b, lb, t)
            a = stats([x for x in trb if x["ts"] < SPLIT])
            z = stats([x for x in trb if x["ts"] >= SPLIT])
            tre = run(e, lb, t)
            ea = stats([x for x in tre if x["ts"] < SPLIT])
            ez = stats([x for x in tre if x["ts"] >= SPLIT])
            ok = (a["pf"] >= 1.2 and z["pf"] >= 1.2 and (a["n"] + z["n"]) >= 50)
            passed += ok
            print(f"  {lb:>3} {t:>4.1f} | {a['n']:>8} {a['pf']:>5.2f} {a['tot']*100:>+6.1f}% | "
                  f"{z['n']:>8} {z['pf']:>5.2f} {z['tot']*100:>+6.1f}% | "
                  f"{ea['pf']:>5.2f}/{ez['pf']:<5.2f} | {'PASS' if ok else 'no'}")

    print("\n  ÖN-KAYITLI KARAR: BTC'de >=3 KOMŞU PASS + o hücrelerin yarısı ETH'de")
    print("  iki dönemde PF>=1.0 → paper-forward. Aksi halde AİLE MÜHÜRLENİR.")
    print(f"  Sonuç: {passed}/12 BTC-PASS")


if __name__ == "__main__":
    main()
