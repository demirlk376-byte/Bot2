"""Pairs spread'in mevcut kitapla korelasyonu + çakışma analizi."""
import numpy as np, pandas as pd, heapq
import fast_bt, pairs_spread as PS
import deployed_backtest as DB

# 1) PAIRS aylık PnL (günlük barlar, en iyi config)
px = PS.load_px("local", "1d")
pairs, info = PS.pick_pairs(px)
allr = []
for a, b in pairs:
    for t in PS.run_pair(px, a, b, 2.0, 0.5, 3.5, 20):
        allr.append({**t, "pair": f"{a}/{b}"})
ps_m = pd.Series([t["ret"]*PS.BAL0 for t in allr],
                 index=[pd.Timestamp(t["ts"]).to_period("M") for t in allr]).groupby(level=0).sum()

# 2) DEPLOY kitabı aylık PnL
tr = []
for c in DB.DONCH: tr += DB.gen("donchian", fast_bt.load(c, source="local"))
for c in DB.SQZ:   tr += DB.gen("squeeze",  fast_bt.load(c, source="local"))
taken = DB.seat_select(tr)
r = np.array([R for _,R,_ in taken]); slp = np.array([s for _,_,s in taken])
eff = np.minimum(DB.RISKF, DB.CAP*slp); pnl = r*eff*DB.BAL0
bk_m = pd.Series(pnl, index=[pd.Timestamp(x).to_period("M") for x,_,_ in taken]).groupby(level=0).sum()

j = pd.concat({"pairs": ps_m, "book": bk_m}, axis=1).dropna()
print(f"\n=== KORELASYON ({len(j)} ortak ay) ===")
print(f"  Pearson : {j['pairs'].corr(j['book']):+.3f}")
print(f"  Spearman: {j['pairs'].corr(j['book'], method='spearman'):+.3f}")
print(f"  pairs pozitif-ay %{(j['pairs']>0).mean()*100:.0f} | book pozitif-ay %{(j['book']>0).mean()*100:.0f}")
bad = j[j["book"] < 0]
print(f"\n  Kitabın KAYIP aylarında ({len(bad)} ay) pairs ne yapmış:")
print(f"    pairs toplam ${bad['pairs'].sum():+.0f} | pozitif olduğu ay: {(bad['pairs']>0).sum()}/{len(bad)}")
comb = j["pairs"] + j["book"]
def mdd(s):
    eq = np.cumsum(s.values); pk = np.maximum.accumulate(np.concatenate([[0],eq]))
    return (pk - np.concatenate([[0],eq])).max()
print(f"\n=== BİRLEŞTİRME ETKİSİ (aylık seri) ===")
print(f"  sadece kitap : toplam ${j['book'].sum():+.0f}  en kötü ay ${j['book'].min():+.0f}  maxDD ${mdd(j['book']):.0f}")
print(f"  sadece pairs : toplam ${j['pairs'].sum():+.0f}  en kötü ay ${j['pairs'].min():+.0f}  maxDD ${mdd(j['pairs']):.0f}")
print(f"  BİRLİKTE     : toplam ${comb.sum():+.0f}  en kötü ay ${comb.min():+.0f}  maxDD ${mdd(comb):.0f}")

# 3) ÇAKIŞMA (netted: coin başına tek pozisyon)
used = set(DB.DONCH) | set(DB.SQZ) | {"LTC"}
print(f"\n=== ÇAKIŞMA (netted mod: coin başına TEK pozisyon) ===")
print(f"  deploy'da kullanılan: {sorted(used)}")
free_pairs, clash = [], []
for a,b in pairs:
    (clash if (a in used or b in used) else free_pairs).append(f"{a}/{b}")
print(f"  ÇAKIŞAN çiftler ({len(clash)}): {', '.join(clash)}")
print(f"  SERBEST çiftler ({len(free_pairs)}): {', '.join(free_pairs) if free_pairs else '— yok'}")
# serbest çiftlerle performans
fr = [t for t in allr if t["pair"] in free_pairs]
if fr:
    d = np.array([t["ret"]*PS.BAL0 for t in fr]); ya = np.array([pd.Timestamp(t["ts"]).year for t in fr])
    gp=d[d>0].sum(); gl=-d[d<0].sum()
    print(f"  SADECE serbest çiftlerle: n={len(d)} PF{gp/max(gl,1e-9):.2f} ${d.sum():+.0f}  " +
          " ".join(f"{y}:${d[ya==y].sum():+.0f}" for y in sorted(set(ya))))
print("CORRDONE")
