import pandas as pd, numpy as np
from scipy import stats
exec(open('market_edge.py').read().split('# ---------------- helpers ----------------')[0])
exec('def ols_cluster' + open('market_edge.py').read().split('def ols_cluster')[1].split('# ============ (1)')[0])
for sp in ['ALL','TRAIN','TEST']:
    g = d if sp=='ALL' else d[d.split==sp]
    for c in ['tw_idx','tw_loo','twR_idx']:
        v = g[c].values*(100 if c.startswith('tw_') else 1)
        b,se,r2,G,_ = ols_cluster(v, np.zeros((len(v),0)), g.ym.values)
        print(sp, c, 'mean', fmt(b[0],se[0],G))
# hold time by outcome and by signed market
print(d.groupby('exit_reason').agg(n=('Rn','size'),hours=('hours','median'),R=('Rn','mean'),tw=('tw_idx',lambda z: 100*z.mean())).round(3))
