"""
trail_exit_diag3.py — KUYRUK BAĞIMLILIĞI: "kazananı serbest bırak" tezinin tüm kârı
kaç işlemden geliyor ve o işlemler ZAMANDA nasıl dağılmış? (notp/donchian, saf kontrol)
Az sayıda dev kazanan = tahmin edicinin varyansı devasa = TRAIN/TEST ayrımı bunu ÇÖZEMEZ.
"""
import numpy as np, pandas as pd
import trail_exit_test as T

P = T.build_cache("local")
basef = T.stats(T.portfolio(P, {}), funding=True)
st = T.stats(T.portfolio(P, {"donchian": ("notp", None)}), funding=True)

for tag, s in (("TABAN", basef), ("notp donchian", st)):
    m = s["slv"] == "donchian"
    r = s["R"][m]; p = s["pnl"][m]; y = s["yrs"][m]
    print(f"\n=== {tag} — donchian bacakları (n{m.sum()}) ===")
    print(f"  toplam ${p.sum():+.0f} | ort {r.mean():+.3f}R")
    for thr in (3, 5, 10):
        k = r > thr
        print(f"  R>{thr:2d}: {k.sum():3d} işlem (%{k.mean()*100:.1f}) → ${p[k].sum():+.0f} "
              f"= toplam kârın %{p[k].sum()/max(p.sum(),1e-9)*100:.0f}'ı | yıllar: "
              + " ".join(f"{yy}:{(y[k]==yy).sum()}" for yy in (2023, 2024, 2025, 2026)))
    o = np.argsort(p)[::-1]
    for k in (3, 5, 10):
        print(f"  EN İYİ {k:2d} işlem ${p[o[:k]].sum():+.0f} → onlarsız toplam ${p.sum()-p[o[:k]].sum():+.0f} "
              f"(taban-donchian ${basef['pnl'][basef['slv']=='donchian'].sum():+.0f})")
    print(f"  en iyi 5 işlemin yılı: " + " ".join(str(int(v)) for v in y[o[:5]]))

# portföy düzeyinde: en iyi 5 işlem çıkarılınca TEST/TRAIN ne olur
print("\n=== portföy: kâr yoğunlaşması ===")
for tag, s in (("TABAN", basef), ("notp donchian", st)):
    p = s["pnl"]; o = np.argsort(p)[::-1]
    print(f"  {tag:14s} en iyi 10 işlem ${p[o[:10]].sum():+.0f} / toplam ${p.sum():+.0f} "
          f"(%{p[o[:10]].sum()/p.sum()*100:.0f})")
