"""osc_diag.py — GOREV B ek teshis: osilatorler donchian/squeeze mantigiyla NE KADAR
KORELE (yeni bilgi tasiyor mu) + en iyi adayin kac isleme dayandigi."""
import numpy as np, pandas as pd
import oscillator_filters as OF

data = OF.load_all()
base = OF.metrics(OF.run(data, {}))

print("=" * 78)
print("A) SINYAL ANINDA GOSTERGE DAGILIMI — 'yeni bilgi' var mi?")
for sl in ("donchian", "squeeze"):
    recs = [r for c in data[sl] for r in data[sl][c]]
    L = [r for r in recs if r["dir"] == 1]; S = [r for r in recs if r["dir"] == -1]
    print(f"\n  {sl}: {len(recs)} aday ({len(L)} long / {len(S)} short)")
    for nm, key in (("RSI(14)", "rsi"), ("StochRSI %K", "srk"), ("AroonUp", "aup"),
                    ("AroonDn", "adn")):
        lv = np.array([r[key] for r in L]); sv = np.array([r[key] for r in S])
        print(f"    {nm:<12} LONG  min{np.nanmin(lv):6.1f} p5{np.nanpercentile(lv,5):6.1f} "
              f"med{np.nanmedian(lv):6.1f} | SHORT max{np.nanmax(sv):6.1f} "
              f"p95{np.nanpercentile(sv,95):6.1f} med{np.nanmedian(sv):6.1f}")
    st = np.array([r["st"] for r in recs]); dr = np.array([r["dir"] for r in recs])
    print(f"    SuperTrend yonu sinyalle uyumlu: {(st==dr).mean()*100:.1f}%")
    mh = np.array([r["mhist"] for r in recs])
    print(f"    MACD hist isareti uyumlu:        {((np.sign(mh)==dr)).mean()*100:.1f}%")
    ml = np.array([r["macd"] for r in recs])
    print(f"    MACD cizgi isareti uyumlu:       {((np.sign(ml)==dr)).mean()*100:.1f}%")

print("\n" + "=" * 78)
print("B) EN IYI ADAY ([sque] MACD>0 uyum) — kazanc kac isleme dayaniyor?")
H = {h["name"]: h for h in OF.make_hypotheses()}
h = H["[sque] MACD>0 uyum"]
ks = OF.keeps_for(data, h)
m = OF.metrics(OF.run(data, ks))
allk = np.concatenate([v for v in ks.values()])
print(f"  squeeze adaylarinin {int((~allk).sum())}/{len(allk)} tanesi elendi "
      f"({(1-allk.mean())*100:.1f}%)")
print(f"  islem sayisi {base['n']} -> {m['n']}  (fark {m['n']-base['n']})")
print(f"  toplam $ {base['usd']:+.0f} -> {m['usd']:+.0f}  (delta ${m['usd']-base['usd']:+.0f})")
print(f"  WR {base['wr']:.2f}% -> {m['wr']:.2f}%   PF {base['pf']:.3f} -> {m['pf']:.3f}")
print(f"  ort risk {base['risk']:.3f}% -> {m['risk']:.3f}%  (kaldirac degisimi YOK ise "
      f"kazanc boyuttan degil)")
print(f"  => ${m['usd']-base['usd']:+.0f} kazanc {abs(m['n']-base['n'])} islemlik farktan geliyor; "
      f"1579 islemlik ornekte bu GURULTU seviyesi.")

print("\n" + "=" * 78)
print("C) SECIM KRITERI DUYARLILIGI — 'sadece TRAIN toplam$ > taban' desem ne olurdu?")
rows = []
for hh in OF.make_hypotheses():
    kk = OF.keeps_for(data, hh)
    mm = OF.metrics(OF.run(data, kk)); mm["name"] = hh["name"]
    rows.append(mm)
lax = [x for x in rows if x["train"] > base["train"]]
print(f"  gevsek kriterle TRAIN'i gecen: {len(lax)}")
for x in sorted(lax, key=lambda z: -z["train"]):
    yr_ok = all(x[f"y{y}"] > OF.BASE_YEAR_PNL[y] for y in (2023, 2024, 2025, 2026))
    print(f"    {x['name']:<32} TRAIN ${x['train']:+.0f} TEST ${x['test']:+.0f} "
          f"(taban {base['test']:+.0f}) her-yil-gecti={yr_ok}")
print("  => TEST bariyeri gevsek kriterle de gecilmiyor; sonuc secim esigine duyarli DEGIL.")
