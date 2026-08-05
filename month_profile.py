import numpy as np, pandas as pd, fast_bt, deployed_backtest as A
tr=[]
for c in A.DONCH: tr+=A.gen("donchian", fast_bt.load(c,source="local"))
for c in A.SQZ:   tr+=A.gen("squeeze",  fast_bt.load(c,source="local"))
for c in A.BB_COINS: tr+=A.gen_bb(fast_bt.load(c,source="local"))
t=A.seat_select(tr)
r=np.array([R for _,R,_ in t]); sp=np.array([s for _,_,s in t])
ex=[pd.Timestamp(x) for x,_,_ in t]
pnl=r*np.minimum(A.RISKF,A.CAP*sp)*A.BAL0
print(f"DOGRULAMA: {len(r)} islem / ${pnl.sum():+.2f}  (1579 / +1420.66 olmali)")
mon=pd.Series(pnl).groupby([x.tz_localize(None).to_period('M') for x in ex]).sum()/A.BAL0*100
m=mon.values; BAL=185.0
print(f"\n=== BIR AY NEYE BENZIYOR ({len(m)} aylik gecmis, ${BAL:.0f} hesap) ===")
print(f"  ortalama ay {m.mean():+6.1f}% = ${m.mean()/100*BAL:+6.0f}   medyan {np.median(m):+.1f}% = ${np.median(m)/100*BAL:+.0f}")
print(f"  pozitif ay orani %{(m>0).mean()*100:.0f}  -> ~5 ayin 1'i ZARARLA kapaniyor")
print("\n  yuzdelikler:")
for q,lbl in ((5,"cok kotu (20 ayda 1)"),(10,"kotu (10 ayda 1)"),(25,"alt ceyrek"),(50,"tipik"),(75,"ust ceyrek"),(90,"iyi"),(95,"cok iyi")):
    v=np.percentile(m,q); print(f"    %{q:>2d} {v:+6.1f}% = ${v/100*BAL:+6.0f}  {lbl}")
print(f"\n  EN KOTU AY {m.min():+.1f}% = ${m.min()/100*BAL:+.0f}   EN IYI AY {m.max():+.1f}% = ${m.max()/100*BAL:+.0f}")
best=cur=0
for v in m:
    cur = cur+1 if v<0 else 0
    best=max(best,cur)
print(f"  en uzun ardisik zarar serisi: {best} ay")
print(f"  -%10'dan kotu ay: %{(m<-10).mean()*100:.0f} ({(m<-10).sum()}/{len(m)})   -%20'den kotu: %{(m<-20).mean()*100:.0f} ({(m<-20).sum()}/{len(m)})")
