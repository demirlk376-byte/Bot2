"""
tampon_karar.py — ATR tamponu: eşit DRAWDOWN'da eşit kâr mı, fazla mı?

ÜÇÜNCÜ DENEME. İlk ikisi de KENDİ ÖLÇÜ HATAMDI ve ikisi de aynı tuzağın
farklı kılıklarıydı:
  1) bileşik TERMINAL DOLAR kıyası → $605k vs $1.04M (ledger: "FANTEZİ")
  2) CAGR kıyası → %1319 vs %911 — matematiksel olarak doğru ama AYNI fantezi,
     çünkü in-sample bileşik patlama üsteldir ve her bileşik ölçüyü domine eder.

DOĞRU KURULUM — iki ölçü, iki ayrı uzay:
  · RİSK KAPASİTESİ bileşikte ölçülür (bot canlıda bileşikleniyor; bugün bu
    ayrımın 21 puan olduğu ölçüldü: %27.35 sabit vs %48.78 bileşik)
  · KÂR sabit-oranda ölçülür (doğrusal, patlamaz, ankorun kendi birimi)

Yani: her varyantın bileşik maxDD'si tabanla EŞİTLENİR, sonra o risk
seviyesindeki SABİT-ORAN kârı kıyaslanır. Tampon kaliteyi gerçekten
artırıyorsa, aynı drawdown'ı taşırken daha çok kâr çıkmalıdır.

Kullanım:  py tampon_karar.py local
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from kirilim_teyit import uret, portfoy

ONBELLEK = "data/_tampon_cache.pkl"


def ol(tk, riskf, bilesikMi):
    R = np.array([r for _, r, _ in tk]); sp = np.array([s for _, _, s in tk])
    ex = pd.to_datetime([x for x, _, _ in tk])
    eff = np.minimum(riskf, A.CANLI_CAP * sp)
    if bilesikMi:
        e = A.BAL0; yol = [e]
        for r, f in zip(R, eff):
            e = max(e * (1.0 + r * f), 1e-9); yol.append(e)
        return A.maxdd(np.array(yol))
    pnl = R * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / A.BAL0 * 100
    return {"kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu": ay.min(), "ortR": R.mean(), "n": len(tk)}


def esitle(tk, hedef):
    lo, hi = 0.005, 0.25
    for _ in range(60):
        mid = (lo + hi) / 2
        if ol(tk, mid, True) < hedef: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    VAR = [("taban", {}), ("tampon 0.10", dict(tampon=0.10)),
           ("tampon 0.25", dict(tampon=0.25)), ("tampon 0.50", dict(tampon=0.50)),
           ("tampon 1.00", dict(tampon=1.00)), ("hacim 1.5x", dict(hacim_k=1.5))]
    if os.path.exists(ONBELLEK):
        with open(ONBELLEK, "rb") as f: cache = pickle.load(f)
    else:
        cache = {}
        for ad, kw in VAR:
            ham = []
            for c in A.DONCH: ham += uret(c, fast_bt.load(c, source=src), **kw)
            cache[ad] = portfoy(ham)
        with open(ONBELLEK, "wb") as f: pickle.dump(cache, f)

    taban = cache["taban"]
    if len(taban) != 1579:
        print(f"✗ taban {len(taban)} != 1579"); sys.exit(2)
    hedef_dd = ol(taban, A.CANLI_RISKF, True)
    t = ol(taban, A.CANLI_RISKF, False)
    print(f"\n{'=' * 96}\n=== ATR TAMPONU — EŞİT DRAWDOWN KARARI ===")
    print(f"  TABAN  risk %{A.CANLI_RISKF*100:.2f} · {t['n']} işlem · ortR {t['ortR']:+.4f}")
    print(f"         bileşik maxDD %{hedef_dd:.2f} (risk kapasitesi ölçüsü)")
    print(f"         sabit-oran kâr ${t['kar']:+.2f} (kâr ölçüsü, doğrusal)\n")
    print(f"  {'varyant':<16s} {'n':>5s} {'ortR':>8s} {'eşit-DD riski':>14s} "
          f"{'sabit kâr $':>12s} {'Δ$':>9s} {'en kötü ay':>11s}  BAR")
    for ad, _ in VAR:
        tk = cache[ad]
        rf = A.CANLI_RISKF if ad == "taban" else esitle(tk, hedef_dd)
        m = ol(tk, rf, False)
        d = m["kar"] - t["kar"]
        gec = ad != "taban" and d >= 36 and m["kotu"] >= t["kotu"]
        print(f"  {ad:<16s} {m['n']:>5d} {m['ortR']:>+8.4f} {rf*100:>13.2f}% "
              f"{m['kar']:>+12.2f} {d:>+9.2f} {m['kotu']:>10.2f}%  "
              f"{'✓ GEÇTİ' if gec else ('—' if ad == 'taban' else '✗')}")
    print(f"\n  ⓘ Risk kapasitesi BİLEŞİKTE, kâr SABİT-ORANDA ölçülüyor. İkisi ayrı")
    print(f"    uzaylar: bileşik drawdown ne kadar risk taşıyabileceğini söyler,")
    print(f"    sabit-oran kâr o riskteki taşınabilir edge büyüklüğünü.")
    print(f"{'=' * 96}\n")


if __name__ == "__main__":
    main()
