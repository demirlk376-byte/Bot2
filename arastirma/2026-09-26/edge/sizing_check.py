import json, numpy as np, pandas as pd
ROOT="/home/user/Bot2"
def load(fn):
    d=pd.read_csv(f"{ROOT}/{fn}"); s=d.strategy_scores.apply(json.loads)
    d["ie"]=s.apply(lambda x:x["intended_entry"]); d["sl0"]=s.apply(lambda x:x["sl0"])
    d["et"]=pd.to_datetime(d.entry_time,utc=True); d["xt"]=pd.to_datetime(d.exit_time,utc=True)
    rp=(d.ie-d.sl0).abs(); d["stop_pct"]=rp/d.ie; d["Rnet"]=d.pnl_usdt/(d.quantity*rp)
    return d
def sim(d, risk, cap, E0=10000.0):
    # event sim: size at entry on realized equity, book pnl at exit
    ev=[(t,1,i) for i,t in enumerate(d.et)]+[(t,0,i) for i,t in enumerate(d.xt)]
    ev.sort(key=lambda x:(x[0],x[1]))  # exits before entries at same timestamp
    E=E0; size={}; path=[]
    R=d.Rnet.values; sp=d.stop_pct.values
    for t,typ,i in ev:
        if typ==1: size[i]=E*min(risk,cap*sp[i])
        else:
            E+=R[i]*size.pop(i); path.append((t,E))
    return E, pd.Series([p[1] for p in path],index=[p[0] for p in path])
for fn,risk,cap in [("ikiz_k25_cap25_islemler.csv",.035,2.5),("ikiz_k25_eski_islemler.csv",.028,1.5),("ikiz_k25_cap15_islemler.csv",.035,1.5)]:
    d=load(fn); E,p=sim(d,risk,cap)
    act=10000+d.sort_values("xt").pnl_usdt.cumsum()
    print(fn, f"actual final={10000+d.pnl_usdt.sum():,.0f}  entry-sized sim={E:,.0f}")
    # implied risk fraction actually used
    d=d.sort_values("et")
print()
for fn,risk,cap in [("ikiz_k25_cap25_islemler.csv",.035,2.5),("ikiz_k25_eski_islemler.csv",.028,1.5)]:
    d=load(fn).reset_index(drop=True)
    # realized equity at each entry time from actual pnl
    x=d.sort_values("xt"); ce=pd.Series(10000+x.pnl_usdt.cumsum().values,index=pd.DatetimeIndex(x.xt))
    def eq_at(t):
        s=ce[ce.index<=t]; return 10000.0 if len(s)==0 else s.iloc[-1]
    d["E"]=d.et.apply(eq_at)
    d["f"]=d.quantity*(d.ie-d.sl0).abs()/d.E
    d["fpred"]=np.minimum(risk,cap*d.stop_pct)
    d["ratio"]=d.f/d.fpred
    print(fn); print(d.groupby("kol").ratio.describe().round(3))
    print("ratio<0.95 share by year:", d.assign(y=d.et.dt.year).groupby("y").ratio.apply(lambda r:(r<0.95).mean()).round(3).to_dict())
