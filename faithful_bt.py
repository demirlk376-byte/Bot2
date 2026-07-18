"""
faithful_bt.py — ÜRETİM SINIFLARIYLA backtest = canlı botun BİREBİR yapacağı şey.
verify_conformance donchian'ı %99, squeeze'i %50 eşleşme gösterdi → fast_bt
squeeze güvenilmez. Bu script üretim DonchianStrategy/SqueezeStrategy'yi bar-bar
(canlının 120/260-bar penceresiyle) koşar, sinyallerden trade simüle eder.
Yavaş ama CANLIYLA AYNI. Kullanım: python faithful_bt.py [BTC]
"""
import sys, glob
import numpy as np, pandas as pd
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
from indicators import atr as atr_fn
import fast_bt

RISK=0.02; BAL=190.0; FEE=0.0001
coin = sys.argv[1] if len(sys.argv)>1 else "BTC"

def load(c):
    if c=="BTC":
        fr=[]
        for f in sorted(glob.glob("BTCUSDT-1m-*.csv")):
            d=pd.read_csv(f); d.columns=["ts","o","h","l","c","v","ct","qv","n","a","b","g"]
            fr.append(d[["ts","o","h","l","c","v"]].astype(float))
        m=pd.concat(fr).drop_duplicates("ts").sort_values("ts")
        m.index=pd.to_datetime(m["ts"],unit="ms",utc=True)
        return m.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"}).drop(columns=["ts"])
    return fast_bt.load(c)

def simtrades(df, ents, sl_mult, rr, max_hold):
    hi=df["high"].values; lo=df["low"].values; cl=df["close"].values; idx=df.index; n=len(cl)
    a=atr_fn(df["high"],df["low"],df["close"],14).values
    tr=[]; occ=-1
    for (i,d) in ents:
        if i<=occ or i>=n-1: continue
        av=a[i]
        if np.isnan(av) or av<=0: continue
        sld=sl_mult*av; e=cl[i]; sl=e-d*sld; tp=e+d*rr*sld; ep=None; j=i
        for j in range(i+1,min(i+1+max_hold,n)):
            if d==1:
                if lo[j]<=sl: ep=sl; break
                if hi[j]>=tp: ep=tp; break
            else:
                if hi[j]>=sl: ep=sl; break
                if lo[j]<=tp: ep=tp; break
        if ep is None: j=min(i+max_hold,n-1); ep=cl[j]
        tr.append({"r":d*(ep-e)/sld - 2*FEE*e/sld,"year":idx[i].year}); occ=j
    return tr

def prod_donchian(m):
    d4=fast_bt.resample(m,"4h"); s=DonchianStrategy(channel=40,rr=2.0,sl_atr=2.0,ema_trend=200)
    a=atr_fn(d4["high"],d4["low"],d4["close"],14); ents=[]
    for i in range(260,len(d4)):
        av=a.iloc[i]
        if np.isnan(av) or av<=0: continue
        sg=s.analyze(d4.iloc[max(0,i-259):i+1],float(av))
        if sg.direction!=0: ents.append((i,sg.direction))
    return simtrades(d4,ents,2.0,2.0,30)

def prod_squeeze(m):
    d1=fast_bt.resample(m,"1h"); s=SqueezeStrategy(kc_mult=1.5,min_squeeze_bars=5,sl_atr=2.0,rr=2.5,mtf_filter=True)
    a=atr_fn(d1["high"],d1["low"],d1["close"],14); ents=[]
    for i in range(260,len(d1)):
        av=a.iloc[i]
        if np.isnan(av) or av<=0: continue
        sg=s.analyze(d1.iloc[max(0,i-119):i+1],float(av))
        if sg.direction!=0: ents.append((i,sg.direction))
    return simtrades(d1,ents,2.0,2.5,48)

def rep(name,tr):
    if not tr: print(f"  {name}: sinyal yok"); return
    df=pd.DataFrame(tr); r=df["r"].values
    gp=r[r>0].sum(); gl=-r[r<0].sum(); pf=gp/gl if gl>0 else 9.99
    print(f"  {name:10s} n={len(r):>3d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+7.2f}  [CANLI-BİREBİR]")
    for yr in sorted(df.year.unique()):
        ry=df[df.year==yr]["r"].values; g1=ry[ry>0].sum(); g2=-ry[ry<0].sum()
        print(f"      {yr} n={len(ry):>3d} WR{(ry>0).mean():>3.0%} PF{(g1/g2 if g2>0 else 9.99):4.2f} {ry.sum()*BAL*RISK:+7.2f}$")

print(f"faithful_bt (ÜRETİM SINIFI = canlı birebir) @ {coin} — yükleniyor...")
m=load(coin)
print(f"  {len(m)} bar")
print(f"\n=== {coin} — CANLI BOTUN BİREBİR YAPACAĞI ===")
rep("donchian",prod_donchian(m))
rep("squeeze",prod_squeeze(m))
