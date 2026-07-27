"""
partial_by_sleeve.py — Kısmi TP'yi SLEEVE bazında ayrıştır + yılların karakterini ölç.

SORU (kullanıcı gözlemi): p50@1R %4 riskte 2023 sadece +%5, 2025 +%52 — neden bu kadar dengesiz?
HİPOTEZ: kısmi TP trendde ZARARLI (büyük kazananı kırpar), chop'ta FAYDALI. donchian bir TREND
takipçisi → ona kısmi TP uygulamak yanlış olabilir; squeeze kısa vadeli → ona doğru olabilir.
2023 muhtemelen güçlü trend yılıydı (2022 dibinden toparlanma) → faydanın küçük olması beklenir.

TEST (risk SABİT %2.25 — kaldıraç etkisini izole et, sadece kısmi TP'nin kendisine bak):
  baseline            : hiç kısmi TP yok
  partial_donch_only  : sadece donchian'da p50@1R
  partial_sqz_only    : sadece squeeze'de p50@1R
  partial_both        : ikisinde de (önceki testteki p50@1R)

+ Her yılın REJİM KARAKTERİ: chop oranı (4h barların önceki-40 kanal İÇİNDE kalma payı) ve
  ortalama ADX — 7 donchian coini ortalaması. Fayda chop'la birlikte mi hareket ediyor?

Eğer fayda tamamen bir sleeve'den geliyorsa → o sleeve'e uygula, diğerine dokunma (daha dengeli
ve daha az kod). Eğer fayda chop yılına yığılıysa → rejime bağlı, ve rejim öngörülemez (kanıtlı)
→ dürüst sonuç "beklenti yıldan yıla oynar".

Kullanım:  py partial_by_sleeve.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
import partial_tp_test as P


def portfolio(trades, riskf=0.0225):
    ev = sorted(trades, key=lambda t: t["entry_ns"]); openh = []; taken = []; ctr = 0
    for t in ev:
        while openh and openh[0][0].value <= t["entry_ns"]: heapq.heappop(openh)
        if len(openh) < P.MAXPOS:
            ctr += 1; heapq.heappush(openh, (t["exit"], ctr, t)); taken.append(t)
    taken.sort(key=lambda t: t["exit"])
    r = np.array([t["R"] for t in taken])
    eff = np.minimum(riskf, P.CAP * np.array([t["sl_pct"] for t in taken]))
    pnl = r * eff * P.BAL0
    allq = np.concatenate([[P.BAL0], P.BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(allq); mdd = ((peak - allq) / peak).max() * 100
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    ex = [pd.Timestamp(t["exit"]) for t in taken]; ya = np.array([x.year for x in ex])
    sl = np.array([t["sleeve"] for t in taken])
    yrs = {y: pnl[ya == y].sum() for y in sorted(set(ya))}
    by_sleeve_yr = {}
    for s in ("donchian", "squeeze"):
        by_sleeve_yr[s] = {y: pnl[(ya == y) & (sl == s)].sum() for y in sorted(set(ya))}
    return dict(pf=pf, tot=pnl.sum(), mdd=mdd, yrs=yrs, bys=by_sleeve_yr)


def regime_by_year(coins, source):
    """Yıl karakteri: chop oranı (kanal İÇİNDE kalan 4h bar payı) + ort ADX, coin ortalaması."""
    acc = {}
    for c in coins:
        d = fast_bt.resample(fast_bt.load(c, source=source), "4h")
        ch_hi = d["high"].rolling(40).max().shift(1)
        ch_lo = d["low"].rolling(40).min().shift(1)
        inside = ((d["close"] <= ch_hi) & (d["close"] >= ch_lo))
        adxv = adx_fn(d["high"], d["low"], d["close"], 14)
        for y in sorted(set(d.index.year)):
            m = d.index.year == y
            if m.sum() < 100: continue
            a = acc.setdefault(y, {"chop": [], "adx": []})
            a["chop"].append(float(inside[m].mean()) * 100)
            a["adx"].append(float(adxv[m].mean()))
    return {y: (np.mean(v["chop"]), np.mean(v["adx"])) for y, v in acc.items()}


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    dpk = {c: P.prep("donchian", fast_bt.load(c, source=source)) for c in P.DONCH}
    spk = {c: P.prep("squeeze", fast_bt.load(c, source=source)) for c in P.SQZ}

    def build(donch_partial, sqz_partial):
        tr = []
        for c in P.DONCH:
            f, pt = (0.50, 1.0) if donch_partial else (0.0, 0.0)
            tr += P.walk(dpk[c], "donchian", c, f, pt, False)
        for c in P.SQZ:
            f, pt = (0.50, 1.0) if sqz_partial else (0.0, 0.0)
            tr += P.walk(spk[c], "squeeze", c, f, pt, False)
        return tr

    VARS = [("baseline", False, False), ("donch_only", True, False),
            ("sqz_only", False, True), ("both", True, True)]
    res = {}
    print(f"\n{'='*94}\n=== KISMİ TP SLEEVE AYRIŞTIRMASI (risk SABİT %2.25 — kaldıraçsız) ===")
    print(f"  {'varyant':12s} {'PF':>5s} {'toplam$':>9s} {'maxDD%':>7s}  yıl-yıl (toplam)")
    for name, dp, sp in VARS:
        m = portfolio(build(dp, sp)); res[name] = m
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in m["yrs"].items())
        print(f"  {name:12s} {m['pf']:>5.2f} {m['tot']:>+9.0f} {m['mdd']:>7.1f}  {ys}")

    print(f"\n  --- baseline'a göre FARK (yıl-yıl, $) ---")
    b = res["baseline"]
    for name in ("donch_only", "sqz_only", "both"):
        d = {y: res[name]["yrs"][y] - b["yrs"].get(y, 0) for y in res[name]["yrs"]}
        tot = res[name]["tot"] - b["tot"]
        ys = " ".join(f"{y}:{v:+.0f}" for y, v in d.items())
        print(f"  {name:12s} toplam {tot:+7.0f}   {ys}")

    print(f"\n  --- sleeve bazında kısmi TP etkisi (both vs baseline, $) ---")
    for s in ("donchian", "squeeze"):
        d = {y: res["both"]["bys"][s][y] - b["bys"][s].get(y, 0) for y in res["both"]["bys"][s]}
        print(f"  {s:12s} " + " ".join(f"{y}:{v:+.0f}" for y, v in d.items()))

    print(f"\n  --- YIL KARAKTERİ (7 donchian coini ort) ---")
    print(f"  {'yıl':>6s} {'chop%':>7s} {'ort ADX':>8s}   (chop yüksek = testere, ADX düşük = trendsiz)")
    for y, (ch, ax) in regime_by_year(P.DONCH, source).items():
        print(f"  {y:>6d} {ch:>7.1f} {ax:>8.1f}")
    print("\n  Fayda tek sleeve'den geliyorsa → sadece ona uygula (daha dengeli, daha az kod).")
    print("  Fayda chop yılına yığılıysa → rejime bağlı; rejim ÖNGÖRÜLEMEZ (kanıtlı) → beklenti oynar.")


if __name__ == "__main__":
    main()
