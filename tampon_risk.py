"""
tampon_risk.py — ATR tamponu kaliteyi artırıyor ama hacmi kesiyor. Kesilen
hacmi RİSKLE geri alabilir miyiz?

kirilim_teyit.py bulgusu: tampon işlem KALİTESİNİ gerçekten artırıyor
(ort R 0.2373 → 0.2867 @1.0ATR, WR %43.5 → %44.4) ve RASTGELE SİLMEYİ
yeniyor (−$550 vs −$695). Bu, deponun "ne silinirse silinsin silmek negatif
beklentidir" kuralının ilk istisnası — filtre gerçekten seçiyor.
Ama toplam kâr yine de düşüyor, çünkü hacim kaliteden hızlı azalıyor.

BUGÜNKÜ İKİNCİ BULGU: bileşik maxDD %48.78 ve tolerans %50 — risk bütçesi DOLU.
Tampon maxDD'yi 12.96 puan DÜŞÜRÜYOR. Yani tampon bize RİSK BÜTÇESİ satın alıyor.

SORU: tamponla açılan bütçeyi riske çevirirsek, taban kârı geçer miyiz?
Bu bir risk-EŞİTLEMELİ kıyas: her varyantın riski, BİLEŞİK maxDD tabanla
aynı olana kadar artırılır. Sonra kârlar kıyaslanır.

⚠ Bileşik DD kullanılıyor, bileşiksiz DEĞİL — bot canlıda equity'ye göre
   boyutlanıyor ve bugün bu ayrımın 21 puan olduğu ölçüldü.

Kullanım:  py tampon_risk.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from kirilim_teyit import uret, portfoy

HEDEF_DD = None      # tabandan hesaplanır


def cagr(son, yil):
    """Yillik bilesik getiri — OLCEGE BAGIMSIZ, terminal dolar DEGIL.

    ⚠ 2026-09-10: ilk surum terminal dolari kiyasliyordu ve $605k vs $1.04M
    gibi rakamlar uretti. Ledger bunu zaten "FANTEZI" diye isaretlemisti
    (growth_sim notu): sifir-surtunme in-sample bilesik patlama. Ust uste
    1579 islemde islem basi minik bir edge farki terminal serveti KATLARCA
    ayirir; o fark bir bulgu degil, usteldir. Tasinabilir olculer: CAGR,
    maxDD ve ikisinin orani."""
    return (son / A.BAL0) ** (1.0 / yil) - 1.0


def bilesik(tk, riskf, cap=None):
    cap = A.CANLI_CAP if cap is None else cap
    R = np.array([r for _, r, _ in tk]); sp = np.array([s for _, _, s in tk])
    ex = pd.to_datetime([x for x, _, _ in tk])
    eff = np.minimum(riskf, cap * sp)
    e = A.BAL0; yol = [e]
    for r, f in zip(R, eff):
        e = max(e * (1.0 + r * f), 1e-9); yol.append(e)
    y = np.array(yol)
    ay = pd.Series(np.diff(y), index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()
    yil = (ex.max() - ex.min()).days / 365.25
    return {"dd": A.maxdd(y), "son": y[-1], "kar": y[-1] - A.BAL0, "n": len(tk),
            "cagr": cagr(y[-1], yil), "yil": yil,
            "kotu_ay_pct": (ay / y[:-1][pd.Series(np.arange(len(ay)))] if False else ay).min()}


def risk_esitle(tk, hedef_dd, lo=0.005, hi=0.20):
    """Bileşik maxDD'yi hedefe getiren riskf'i ikili aramayla bul."""
    for _ in range(60):
        mid = (lo + hi) / 2
        if bilesik(tk, mid)["dd"] < hedef_dd: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    ham0 = []
    for c in A.DONCH: ham0 += uret(c, fast_bt.load(c, source=src))
    taban = portfoy(ham0)
    if len(taban) != 1579:
        print(f"✗ taban {len(taban)} != 1579"); sys.exit(2)
    t = bilesik(taban, A.CANLI_RISKF)
    print(f"\n{'=' * 92}\n=== TAMPON → RİSK BÜTÇESİ TAKASI (bileşik) ===")
    print(f"  TABAN  risk %{A.CANLI_RISKF*100:.2f} · {t['n']} işlem · "
          f"CAGR %{t['cagr']*100:.1f} · bileşik maxDD %{t['dd']:.2f} · {t['yil']:.2f} yıl")
    print(f"  ⚠ terminal DOLAR kıyaslanmıyor: bileşik in-sample patlama fanteziдir")
    print(f"    (ledger growth_sim notu). Taşınabilir ölçü CAGR ve maxDD.\n")
    print(f"  {'varyant':<24s} {'n':>5s} {'DD (aynı risk)':>15s} {'eşit-DD riski':>14s} "
          f"{'CAGR (eşit DD)':>15s} {'ΔCAGR':>9s}")
    for ad, kw in (("tampon 0.25", dict(tampon=0.25)), ("tampon 0.50", dict(tampon=0.50)),
                   ("tampon 1.00", dict(tampon=1.00)), ("hacim 1.5x", dict(hacim_k=1.5))):
        ham = []
        for c in A.DONCH: ham += uret(c, fast_bt.load(c, source=src), **kw)
        tk = portfoy(ham)
        d0 = bilesik(tk, A.CANLI_RISKF)
        rf = risk_esitle(tk, t["dd"])
        m = bilesik(tk, rf)
        print(f"  {ad:<24s} {len(tk):>5d} {d0['dd']:>14.2f}% {rf*100:>13.2f}% "
              f"{m['cagr']*100:>14.1f}% {(m['cagr']-t['cagr'])*100:>+8.1f}p"
              f"{'  ✓ GEÇTİ' if m['cagr'] > t['cagr'] else ''}")
    print(f"\n  ⓘ 'eşit-DD riski': o varyantın bileşik maxDD'sini TABANLA aynı yapan risk.")
    print(f"    Kâr o riskte ölçülüyor, yani iki taraf AYNI drawdown'ı taşıyor.")
    print(f"    Tampon kaliteyi artırıyorsa, aynı riskte DAHA ÇOK kâr çıkmalı.")
    print(f"{'=' * 92}\n")


if __name__ == "__main__":
    main()
