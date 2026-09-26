import json, numpy as np, pandas as pd
from scipy import stats as ss
rng=np.random.default_rng(3)
d=pd.read_csv('/home/user/Bot2/ikiz_k25_cap25_islemler.csv')
s=d.strategy_scores.apply(json.loads)
d['ie']=s.apply(lambda x:x['intended_entry']); d['sl0']=s.apply(lambda x:x['sl0'])
d['Rn']=d.pnl_usdt/(d.quantity*(d.ie-d.sl0).abs())
d['xt']=pd.to_datetime(d.exit_time); d['et']=pd.to_datetime(d.entry_time)
o=d.sort_values(['xt','et']).reset_index(drop=True)
eqb=10000+o.pnl_usdt.cumsum().shift(fill_value=0); o['r']=o.pnl_usdt/eqb
R=o.Rn.values; n=len(R); lr=np.log1p(o.r.values)
eq=np.r_[0,np.cumsum(lr)]; pk=np.maximum.accumulate(eq); dd=eq-pk
# underwater segments
uw=[];i=0
while i<n:
    if dd[i+1]<0:
        j=i+1
        while j<=n and dd[j]<0: j+=1
        t=i+int(np.argmin(dd[i:j])); uw.append((j-i, i, t, j, 1-np.exp(dd[t]))); i=j
    else: i+=1
uw.sort(reverse=True)
for L,p,t,j,dep in uw[:3]:
    print(f'underwater {L} trades: peak after trade {p} ({o.xt.iloc[p-1] if p>0 else "start"}), trough {o.xt.iloc[t-1]}, '
          f'recovery {"trade "+str(j)+" "+str(o.xt.iloc[j-1]) if j<=n else "OPEN"}, depth {dep:.1%}, trough->recovery {j-t if j<=n else "censored"} trades')
day=o.et.dt.tz_localize(None).dt.floor('D'); dc,_=pd.factorize(day,sort=True)
blocks=[np.flatnonzero(dc==k) for k in range(dc.max()+1)]
fullWR=(R>0).mean()
def scan(mask,label,NP=5000):
    x=R[mask]; k=len(x); srt=x.sum(); w=int((x>0).sum())
    cA=cB=0
    for g in ('A','B'):
        cnt=0
        for _ in range(NP):
            idx=rng.permutation(n) if g=='A' else np.concatenate([blocks[q] for q in rng.permutation(len(blocks))])
            c=np.r_[0,np.cumsum(R[idx])]
            if (c[k:]-c[:-k]).min()<=srt+1e-12: cnt+=1
        if g=='A': cA=(cnt+1)/(NP+1)
        else: cB=(cnt+1)/(NP+1)
    sub=o[mask]
    wins=x[x>0]
    print(f'{label}: n={k} meanR={x.mean():+.3f} WR={w/k:.3f} ({w}/{k}) avgWin={wins.mean() if len(wins) else np.nan:+.2f} '
          f'exit={sub.exit_reason.value_counts().to_dict()} kol={sub.kol.value_counts().to_dict()} | '
          f'fixed-window z={(x.mean()-R.mean())/(R.std(ddof=1)/np.sqrt(k)):+.2f} naive p={ss.norm.cdf((x.mean()-R.mean())/(R.std(ddof=1)/np.sqrt(k))):.4f} '
          f'| scan p(any {k}-window sumR<=obs) A={cA:.3f} B={cB:.3f}')
xt=o.xt
scan(((xt>='2026-02-06')&(xt<='2026-05-04 23:59')).values,'EP1 2026-02-06..05-04')
scan(((xt>='2026-06-08')).values,'EP2 2026-06-08..07-19')
scan(((xt>='2026-02-01')).values,'2026-02..07 whole')
scan(((xt>='2026-01-01')).values,'2026 YTD')
te=o[xt>='2025-01-01'].Rn.values
print('TEST alone mean', te.mean().round(4), 't-CI', (te.mean()+np.array([-1,1])*1.966*te.std(ddof=1)/np.sqrt(len(te))).round(3))
g=o[xt>='2025-01-01'].assign(day=day).groupby('day').Rn.agg(['sum','count']); idx=rng.integers(0,len(g),(10000,len(g)))
b=g['sum'].values[idx].sum(1)/g['count'].values[idx].sum(1); print('TEST day-cluster CI',np.percentile(b,[2.5,97.5]).round(3))
