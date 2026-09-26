"""Reviewer: change-point sensitivity to min segment length (research only)."""
import numpy as np, pandas as pd
o=pd.read_pickle('/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/review/o_ikiz_k25_cap25_islemler.pkl')
R=o.Rme.values; n=len(R); rng=np.random.default_rng(9)
day=pd.factorize(o.et.dt.strftime('%Y-%m-%d'),sort=True)[0]; blocks=[np.flatnonzero(day==q) for q in range(day.max()+1)]
def cp(x,ms):
    c=np.cumsum(x); k=np.arange(ms,len(x)-ms+1); m1=c[k-1]/k; m2=(c[-1]-c[k-1])/(len(x)-k)
    z=(m1-m2)/np.sqrt(1/k+1/(len(x)-k))/x.std(ddof=1); j=z.argmax(); return z[j],k[j]
for ms in [20,30,50,100]:
    z,k=cp(R,ms)
    A=np.array([cp(R[rng.permutation(n)],ms)[0] for _ in range(3000)])
    B=np.array([cp(R[np.concatenate([blocks[q] for q in rng.permutation(len(blocks))])],ms)[0] for _ in range(3000)])
    print(f'minseg {ms}: z={z:.2f} break at trade {k} ({o.xt.iloc[k].date()}) after n={n-k} mean {R[k:].mean():+.3f}; p A={np.mean(A>=z):.3f} B={np.mean(B>=z):.3f}')
