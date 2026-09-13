"""KARSI-OLGU: 2025-10-10 cokus barinin fitilleri budanirsa ankor ne olur?
Uretim dosyalarina DOKUNMAZ - veri bellekte degistirilir, fast_bt.load monkeypatch edilir."""
import sys, heapq, copy
import numpy as np, pandas as pd
sys.path.insert(0,"/home/user/Bot2")
import fast_bt, deployed_backtest as A

COINS = A.DONCH + A.SQZ + A.BB_COINS
HAM = {c: fast_bt.load(c, source="local") for c in COINS}
_orig = fast_bt.load

def kos(veri, etiket):
    fast_bt.load = lambda c, source=None: veri[c]
    tr=[]
    for c in A.DONCH: tr+=A.gen("donchian", veri[c])
    for c in A.SQZ:   tr+=A.gen("squeeze",  veri[c])
    for c in A.BB_COINS: tr+=A.gen_bb(veri[c])
    taken=A.seat_select(tr)
    r=np.array([R for _,R,_ in taken]); slp=np.array([s for _,_,s in taken])
    eff=np.minimum(A.RISKF, A.CAP*slp); pnl=(r*eff*A.BAL0)
    effc=np.minimum(A.CANLI_RISKF, A.CANLI_CAP*slp); pnlc=(r*effc*A.BAL0)
    print(f"{etiket:34s} n={len(r):5d}  ortR {r.mean():+.4f}  ankor ${pnl.sum():+9.2f}  canli ${pnlc.sum():+9.2f}")
    return len(r), r.mean(), pnl.sum(), pnlc.sum()

print("=== TABAN ===")
b=kos(HAM,"degismemis")

# --- senaryo 1: 2025-10-10 fitilleri budanmis (bar ici hareket max %15) ---
def buda(veri, gun, lim):
    out={}
    for c,d in veri.items():
        d2=d.copy()
        m=(d2.index>=pd.Timestamp(gun+" 00:00",tz="UTC"))&(d2.index<pd.Timestamp(gun+" 23:59",tz="UTC"))
        o=d2.loc[m,"open"].values; c_=d2.loc[m,"close"].values
        hi=d2.loc[m,"high"].values; lo=d2.loc[m,"low"].values
        ref=np.maximum(o,c_); refl=np.minimum(o,c_)
        d2.loc[m,"high"]=np.minimum(hi, ref*(1+lim))
        d2.loc[m,"low"] =np.maximum(lo, refl*(1-lim))
        out[c]=d2
    return out

print("\n=== SENARYO: 2025-10-10 barlarinin fitilleri budandi ===")
for lim in (0.15,0.30):
    s=kos(buda(HAM,"2025-10-10",lim), f"2025-10-10 fitil <= %{lim*100:.0f}")
    print(f"     -> ankor farki ${s[2]-b[2]:+.2f} ({(s[2]-b[2])/b[2]*100:+.2f}%), ortR farki {s[1]-b[1]:+.4f}R")

print("\n=== SENARYO: 2023-08-26 kesinti barlari SILINDI ===")
v2={}
for c,d in HAM.items():
    d2=d[~((d.index>=pd.Timestamp("2023-08-26 18:00",tz="UTC"))&(d.index<=pd.Timestamp("2023-08-26 22:00",tz="UTC")))]
    v2[c]=d2
s=kos(v2,"kesinti barlari yok"); print(f"     -> ankor farki ${s[2]-b[2]:+.2f} ({(s[2]-b[2])/b[2]*100:+.2f}%)")

print("\n=== SENARYO: tum coinler AYNI pencereye kirpildi (ortak baslangic/bitis) ===")
b0=max(d.index[0] for d in HAM.values()); b1=min(d.index[-1] for d in HAM.values())
print(f"     ortak pencere: {b0} -> {b1}")
v3={c:d.loc[b0:b1] for c,d in HAM.items()}
s=kos(v3,"ortak pencere"); print(f"     -> ankor farki ${s[2]-b[2]:+.2f} ({(s[2]-b[2])/b[2]*100:+.2f}%)")
fast_bt.load=_orig
