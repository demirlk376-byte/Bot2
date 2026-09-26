import numpy as np, pandas as pd
from scipy import stats
exec(open('rev.py').read().split("# --- trades")[0])
exec("def ols"+open('rev.py').read().split("def ols")[1].split("def f(")[0])
def f(b,se,p,tc): return f'{b:+.3f} [{b-tc*se:+.3f},{b+tc*se:+.3f}] p={p:.3g}'
d=pd.read_pickle(f'{OUT}/d.pkl')
for off in [0,1,2]:
    T=d.xt-pd.Timedelta(f'{off}h')
    mv=d.sg*(L('IDX',T)-L('IDX',d.et)); x=mv/d.sp
    b,se,r2,G,p,tc=ols(mv.values*100,None,d.em.values)
    nz=d[(x.abs()<0.25).values]; b2,se2,_,_,p2,tc2=ols(nz.R.values,None,nz.em.values)
    b3,se3,r23,_,p3,tc3=ols(d.R.values,mv.values*100,d.em.values)
    q=pd.qcut(x,5,labels=False)
    print(f'exit level at xt-{off}h: mean tailwind {f(b[0],se[0],p[0],tc)}% | |x|<0.25: n={len(nz)} R {f(b2[0],se2[0],p2[0],tc2)} | alpha(pct) {f(b3[0],se3[0],p3[0],tc3)} R2 {r23:.3f} | quintiles {d.R.groupby(q).mean().round(2).tolist()}')
    print('    by exit reason median/mean move %:', d.assign(mv=mv*100).groupby('exit_reason').mv.agg(['median','mean']).round(2).to_dict('index'))
# bucket |x|<0.25 composition by exit reason under A vs C
for off in [0,1]:
    T=d.xt-pd.Timedelta(f'{off}h'); x=d.sg*(L('IDX',T)-L('IDX',d.et))/d.sp
    print(off, d[(x.abs()<0.25).values].groupby('exit_reason').R.agg(['size','mean']).round(3).to_dict('index'))
# forward-24h regressor
T=d.et+pd.Timedelta('24h'); fw=d.sg*(L('IDX',T)-L('IDX',d.et))/d.sp
b,se,r2,G,p,tc=ols(d.R.values,fw.values,d.em.values); print(f'R ~ fwd24 idx move/stop: slope {b[1]:.3f} R2={r2:.3f} share {b[1]*fw.sum()/d.R.sum():.2%}')
# mean R itself, cluster-robust
b,se,r2,G,p,tc=ols(d.R.values,None,d.em.values); print('mean R all',f(b[0],se[0],p[0],tc))
for k in ['TRAIN','TEST']:
    g=d[d.split==k]; b,se,r2,G,p,tc=ols(g.R.values,None,g.em.values); print(' mean R',k,f(b[0],se[0],p[0],tc),len(g))
# placebo summary with cluster-free p
P=np.load(f'{OUT}/plc.npy'); plc,plcR=P
sims=np.array([rng.choice(plc,len(d)).mean() for _ in range(5000)])
print(f'placebo 936-trade mean tailwind: median {np.median(sims):+.3f}% 95% [{np.percentile(sims,2.5):+.3f},{np.percentile(sims,97.5):+.3f}]; observed C {100*d.mi_C.mean():+.3f} p1={np.mean(sims>=100*d.mi_C.mean()):.3f} (iid null, anti-conservative)')
