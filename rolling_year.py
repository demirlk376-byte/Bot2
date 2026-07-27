"""Kayan 12-aylık pencereler: bir 'yıl' ne kadar kötü olabilir + kötü dönemin anatomisi."""
import numpy as np, pandas as pd, heapq, fast_bt
import deployed_backtest as DB

tr = []
for c in DB.DONCH: tr += DB.gen("donchian", fast_bt.load(c, source="local"))
for c in DB.SQZ:   tr += DB.gen("squeeze",  fast_bt.load(c, source="local"))
taken = DB.seat_select(tr)
r = np.array([R for _,R,_ in taken]); slp = np.array([s for _,_,s in taken])
pnl = r * np.minimum(DB.RISKF, DB.CAP*slp) * DB.BAL0
ex = [pd.Timestamp(x) for x,_,_ in taken]
m = pd.Series(pnl, index=[x.to_period("M") for x in ex]).groupby(level=0).sum().sort_index()
# eksik ayları 0 ile doldur
full = pd.period_range(m.index.min(), m.index.max(), freq="M")
m = m.reindex(full, fill_value=0.0)

roll = m.rolling(12).sum().dropna()
print(f"\n{'='*78}\n=== KAYAN 12-AYLIK PENCERELER ({len(roll)} pencere, taban ${DB.BAL0:.0f}) ===")
print(f"  en KÖTÜ 12 ay : ${roll.min():+7.0f}  ({roll.idxmin()-11} → {roll.idxmin()})")
print(f"  en İYİ  12 ay : ${roll.max():+7.0f}  ({roll.idxmax()-11} → {roll.idxmax()})")
print(f"  medyan        : ${roll.median():+7.0f}   ortalama: ${roll.mean():+7.0f}")
print(f"  NEGATİF olan 12-ay penceresi sayısı: {(roll<0).sum()}/{len(roll)}")
print(f"\n  --- tüm 12-aylık pencereler (bitiş ayına göre) ---")
for p, v in roll.items():
    bar = "#" * max(1, int(abs(v)/25))
    print(f"    ...→{p}: ${v:+7.0f} {bar}")

# en kötü pencerenin anatomisi
w_end = roll.idxmin(); w = m[(m.index > w_end-12) & (m.index <= w_end)]
print(f"\n  --- EN KÖTÜ 12 AYIN İÇİ ({w_end-11} → {w_end}) ---")
print("    " + " ".join(f"{p.strftime('%y-%m')}:${v:+.0f}" for p,v in w.items()))
print(f"    negatif ay: {(w<0).sum()}/12 | en kötü ay ${w.min():+.0f} | pozitif ay ${w[w>0].sum():+.0f} / negatif ${w[w<0].sum():+.0f}")
print("ROLLDONE")
