"""
eth_swap_test.py — ETH'yi donchian'dan çıkarıp pairs'e açmak net pozitif mi? (RİSK-NÖTR)

Çakışma engeli: netted modda coin başına tek pozisyon. ETH donchian'da → BTC/ETH ve ETC/ETH
çiftleri kullanılamıyor. ETH donchian'da zayıf halka (PF1.39) ama iki güçlü çiftte geçiyor.

RİSK-NÖTRLÜK ŞART: pairs ham haliyle sermayenin ~tamamını nominal kullanıyor (ret=(r_a+r_b)/2),
kitap ise %2.25 risk. Adil karşılaştırma için pairs, ÇIKARILAN ETH-donchian'ın aylık PnL
standart sapmasına eşitlenerek ölçeklenir → "ETH'nin risk bütçesini pairs'e devret".

baseline : donchian7 (ETH dahil) + squeeze4
variant  : donchian6 (ETH YOK) + squeeze4 + k×(BTC/ETH + ETC/ETH)
Karar: toplam VE yıl-yıl VE en kötü ay iyileşmeli. Aksi halde ETH donchian'da kalsın.
"""
import numpy as np, pandas as pd, heapq
import fast_bt, deployed_backtest as DB, pairs_spread as PS

def book_monthly(donch_coins):
    tr = []
    for c in donch_coins: tr += DB.gen("donchian", fast_bt.load(c, source="local"))
    for c in DB.SQZ:      tr += DB.gen("squeeze",  fast_bt.load(c, source="local"))
    taken = DB.seat_select(tr)
    r = np.array([R for _,R,_ in taken]); sl = np.array([s for _,_,s in taken])
    pnl = r * np.minimum(DB.RISKF, DB.CAP*sl) * DB.BAL0
    return pd.Series(pnl, index=[pd.Timestamp(x).to_period("M") for x,_,_ in taken]).groupby(level=0).sum()

def eth_only_monthly():
    tr = DB.gen("donchian", fast_bt.load("ETH", source="local"))
    r = np.array([t[2] for t in tr]); sl = np.array([t[3] for t in tr])
    pnl = r * np.minimum(DB.RISKF, DB.CAP*sl) * DB.BAL0
    return pd.Series(pnl, index=[pd.Timestamp(t[1]).to_period("M") for t in tr]).groupby(level=0).sum()

def pairs_monthly(pairs):
    px = PS.load_px("local", "1d"); allr = []
    for a,b in pairs:
        allr += PS.run_pair(px, a, b, 2.0, 0.5, 3.5, 20)
    return pd.Series([t["ret"]*PS.BAL0 for t in allr],
                     index=[pd.Timestamp(t["ts"]).to_period("M") for t in allr]).groupby(level=0).sum()

def report(name, s):
    ya = np.array([p.year for p in s.index])
    yrs = {y: s.values[ya==y].sum() for y in sorted(set(ya))}
    eq = np.cumsum(s.values); pk = np.maximum.accumulate(np.concatenate([[0],eq]))
    mdd = (pk - np.concatenate([[0],eq])).max()
    print(f"  {name:26s} toplam ${s.sum():>+7.0f}  en kötü ay ${s.min():>+6.0f}  maxDD ${mdd:>5.0f}  " +
          " ".join(f"{y}:${v:+.0f}" for y,v in yrs.items()))
    return yrs

base = book_monthly(DB.DONCH)
d6   = book_monthly([c for c in DB.DONCH if c != "ETH"])
ethm = eth_only_monthly()
prm  = pairs_monthly([("BTC","ETH"), ("ETC","ETH")])

# RİSK-NÖTR ölçek: pairs aylık std = ETH-donchian aylık std
j = pd.concat({"e": ethm, "p": prm}, axis=1).dropna()
k = j["e"].std() / max(j["p"].std(), 1e-9)
print(f"\n{'='*104}\n=== ETH TAKASI (risk-nötr: pairs ×{k:.3f} → aylık std ETH-donchian'a eşit) ===")
print(f"  ETH-donchian aylık std ${ethm.std():.2f} | ham pairs aylık std ${prm.std():.2f} → ölçek {k:.3f}")
prm_s = prm * k
print()
by = report("baseline (donchian7+sqz)", base)
report("  bundan: ETH-donchian", ethm)
report("  ham pairs BTC/ETH+ETC/ETH", prm)
report("  risk-nötr pairs", prm_s)
print()
var = d6.add(prm_s, fill_value=0.0)
vy = report("VARIANT (d6 + pairs)", var)
hurt = [y for y in vy if vy[y] < by.get(y,0) - 1e-6]
print(f"\n  fark: ${var.sum()-base.sum():+.0f}  |  " +
      ("HER YIL İYİ ✓" if not hurt else f"BOZULAN YIL: {sorted(hurt)}"))
print("ETHDONE")
