import pandas as pd, numpy as np
from sim import *
rng=np.random.default_rng(7)
O=prep(others); D=prep(od); D['pas']=(od.vr>=2.5).values; D['coin']=od.coin.values
res={}
for seg,(s,e) in {'TRAIN':(pd.Timestamp('2023-01-01',tz='UTC'),T0),'TEST':(T0,pd.Timestamp('2027-01-01',tz='UTC'))}.items():
    Ds=D[(D.et>=s)&(D.et<e)]; Os=O[(O.et>=s)&(O.et<e)]
    k=Ds.pas.sum()
    obs=metrics(pd.concat([Ds[Ds.pas],Os]),seg); unf=metrics(pd.concat([Ds,Os]),seg)
    null=[];nullc=[]
    for b in range(2000):
        idx=rng.choice(len(Ds),k,replace=False)
        null.append(metrics(pd.concat([Ds.iloc[idx],Os]),seg))
        # coin-stratified: same count per coin
        parts=[]
        for c,g in Ds.groupby('coin'):
            kc=g.pas.sum(); parts.append(g.iloc[rng.choice(len(g),kc,replace=False)])
        nullc.append(metrics(pd.concat(parts+[Os]),seg))
    null=np.array(null); nullc=np.array(nullc)
    for nm,nl in [('iid',null),('coin-strat',nullc)]:
        print(f'{seg} n_keep={k}/{len(Ds)} [{nm}] filter: logret={obs[0]:.2f} DD={obs[1]:.3f} MAR={obs[2]:.2f} | null median logret={np.median(nl[:,0]):.2f} DD={np.median(nl[:,1]):.3f} MAR={np.median(nl[:,2]):.2f} | P(null>=obs) logret={np.mean(nl[:,0]>=obs[0]):.3f} MAR={np.mean(nl[:,2]>=obs[2]):.3f} P(null DD<=obs DD)={np.mean(nl[:,1]<=obs[1]):.3f} | frac null DD<unfilt DD={np.mean(nl[:,1]<unf[1]):.3f} frac null MAR>unfilt={np.mean(nl[:,2]>unf[2]):.3f}')
