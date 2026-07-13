"""
research_nr7.py — NR-N günlük sıkışma kırılımı ailesi. Sprint #3.

NEDEN BU AİLE: squeeze sleeve'inin (BB-içinde-KC, saatlik) günlük kuzeni.
NR7 = günlük aralığı (high-low) son 7 günün en darı olan gün — klasik
Toby Crabel sıkışma günü. Hipotez: dar günü izleyen gün, dar günün
aralığının kırılması yönünde devam eder (vol genişlemesi).

MEKANİK (ön-kayıtlı):
  Tetik  : NR-N günü tespit edilir (bugünün aralığı son N günün en darı).
  Giriş  : ERTESİ gün fiyat NR gününün HIGH'ını aşarsa LONG (stop-entry
           seviyeden), LOW'unu kırarsa SHORT. İlk dokunan taraf alınır;
           gün içinde ikisi de dokunursa pesimistik: ZARAR eden taraf
           alınmış sayılır (intrabar sırası günlük veride bilinemez).
  SL     : NR gününün karşı ucu.  TP: giriş ± RR × (NR aralığı).
  Çıkış  : SL/TP aynı gün pesimistik (SL önce); değmezse H gün max-hold,
           kapanıştan çık. Fee: 2 taker bacağı.
  Coin   : BTC karar, ETH doğrulama (aynı #2 standardı).

ÖN-KAYITLI KABUL ÇITASI:
  BTC'de TRAIN(2023-24) PF >= 1.2 VE TEST(2025-26) PF >= 1.2 VE n >= 50,
  >= 3 KOMŞU hücrede; VE o hücrelerin yarısı ETH'de iki dönem PF >= 1.0.
  Geçerse paper-forward; geçmezse AİLE MÜHÜRLENİR.

Kullanım (VPS):  venv/bin/python research_nr7.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_strategies_crosscoin import load_data

YEARS = [2023, 2024, 2025, 2026]
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
FEE_LEG = 0.0001

GRID_N  = [5, 7, 9]        # NR penceresi
GRID_RR = [1.0, 1.5, 2.0]  # TP = RR × NR aralığı
MAX_HOLD = 3               # gün


def daily(sym: str) -> pd.DataFrame:
    df = load_data(sym, YEARS)
    return df.resample("1D").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"}).dropna()


def run(d: pd.DataFrame, N: int, rr: float) -> list[dict]:
    h = d["high"].values; l = d["low"].values; c = d["close"].values
    idx = d.index
    rng = h - l
    n = len(d)
    trades: list[dict] = []
    i = N
    while i < n - 1:
        # NR-N günü mü? (bugünün aralığı son N günün en darı — kendisi dahil)
        if rng[i] > 0 and rng[i] == rng[i - N + 1: i + 1].min():
            nr_h, nr_l, nr_r = h[i], l[i], rng[i]
            j = i + 1
            d_dir = 0
            if h[j] > nr_h and l[j] < nr_l:
                # iki taraf da dokundu — pesimistik: kaybeden yön alınmış say
                d_dir = 1 if c[j] < nr_h else -1   # kapanış aşağıdaysa long tuzağı
            elif h[j] > nr_h:
                d_dir = 1
            elif l[j] < nr_l:
                d_dir = -1
            if d_dir != 0:
                entry = nr_h if d_dir == 1 else nr_l
                sl = nr_l if d_dir == 1 else nr_h
                tp = entry + d_dir * rr * nr_r
                exit_p = None
                # giriş günü dahil pesimistik yol
                for k in range(j, min(j + MAX_HOLD + 1, n)):
                    lo_k, hi_k = l[k], h[k]
                    if k == j:
                        # giriş günü: girişten sonra SL'e gidebilir
                        if d_dir == 1 and lo_k <= sl: exit_p = sl; break
                        if d_dir == -1 and hi_k >= sl: exit_p = sl; break
                        if d_dir == 1 and hi_k >= tp: exit_p = tp; break
                        if d_dir == -1 and lo_k <= tp: exit_p = tp; break
                    else:
                        if d_dir == 1:
                            if lo_k <= sl: exit_p = sl; break
                            if hi_k >= tp: exit_p = tp; break
                        else:
                            if hi_k >= sl: exit_p = sl; break
                            if lo_k <= tp: exit_p = tp; break
                if exit_p is None:
                    exit_p = c[min(j + MAX_HOLD, n - 1)]
                risk = abs(entry - sl)
                if risk > 0:
                    r_mult = d_dir * (exit_p - entry) / risk
                    fee_r = 2 * FEE_LEG * entry / risk
                    trades.append({"pnl": r_mult - fee_r, "ts": idx[j]})
                i = min(j + MAX_HOLD, n - 1)   # pozisyon bitene kadar yeni tetik yok
                continue
        i += 1
    return trades


def stats(tr):
    if not tr:
        return {"n": 0, "pf": 0.0, "wr": 0.0, "tot": 0.0}
    p = [t["pnl"] for t in tr]
    gp = sum(x for x in p if x > 0); gl = -sum(x for x in p if x < 0)
    return {"n": len(p), "pf": (gp / gl) if gl > 0 else 9.99,
            "wr": sum(1 for x in p if x > 0) / len(p), "tot": sum(p)}


def main() -> None:
    print("BTC + ETH günlük veri (2023-2026)...")
    b = daily("BTCUSDT"); e = daily("ETHUSDT")
    print(f"BTC {len(b)}g, ETH {len(e)}g")

    print("\n" + "=" * 86)
    print("  NR-N SIKIŞMA KIRILIMI (#3) — BTC karar / ETH doğrulama (pnl: R, fee dahil)")
    print("=" * 86)
    print(f"  {'N':>3} {'RR':>4} | {'BTC-TR n':>8} {'PF':>5} {'totR':>7} | "
          f"{'BTC-TE n':>8} {'PF':>5} {'totR':>7} | {'ETH TR/TE PF':>13} | karar")
    print("  " + "-" * 82)
    passed = 0
    for N in GRID_N:
        for rr in GRID_RR:
            trb = run(b, N, rr)
            a = stats([x for x in trb if x["ts"] < SPLIT])
            z = stats([x for x in trb if x["ts"] >= SPLIT])
            tre = run(e, N, rr)
            ea = stats([x for x in tre if x["ts"] < SPLIT])
            ez = stats([x for x in tre if x["ts"] >= SPLIT])
            ok = (a["pf"] >= 1.2 and z["pf"] >= 1.2 and (a["n"] + z["n"]) >= 50)
            passed += ok
            print(f"  {N:>3} {rr:>4.1f} | {a['n']:>8} {a['pf']:>5.2f} {a['tot']:>+6.1f}R | "
                  f"{z['n']:>8} {z['pf']:>5.2f} {z['tot']:>+6.1f}R | "
                  f"{ea['pf']:>5.2f}/{ez['pf']:<5.2f} | {'PASS' if ok else 'no'}")

    print("\n  ÖN-KAYITLI KARAR: BTC'de >=3 KOMŞU PASS + yarısı ETH'de iki dönem")
    print("  PF>=1.0 → paper-forward. Aksi halde AİLE MÜHÜRLENİR.")
    print(f"  Sonuç: {passed}/9 BTC-PASS")


if __name__ == "__main__":
    main()
