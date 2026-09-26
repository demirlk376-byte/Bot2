import numpy as np, pandas as pd
from scipy import stats
exec(open('rev.py').read().split("# --- trades")[0])
exec("def ols"+open('rev.py').read().split("def ols")[1].split("def f(")[0])
def f(b,se,p,tc): return f'{b:+.3f} [{b-tc*se:+.3f},{b+tc*se:+.3f}] p={p:.3g}'
d=pd.read_pickle(f'{OUT}/d.pkl')
END=d.xt.max()
# monthly index return: log level at first hour of next month minus first hour of month (wall clock)
months=pd.period_range('2023-04','2026-07',freq='M')
def lv(col,t): return L(col,[t])[0]
start=pd.Timestamp(d.et.min()).floor('D')
rows=[]
for m in months:
    a=max(m.start_time.tz_localize('UTC'),start); b=min((m+1).start_time.tz_localize('UTC'),END.floor('h'))
    # daily log returns of index for ER
    days=pd.date_range(a,b,freq='1D')
    if days[-1]<b: days=days.append(pd.DatetimeIndex([b]))
    dl=np.diff(L('IDX',days))
    rows.append(dict(m=m,idx=lv('IDX',b)-lv('IDX',a),btc=lv('BTC',b)-lv('BTC',a),er=abs(dl.sum())/np.abs(dl).sum(),ndays=len(dl),vol=dl.std()*np.sqrt(30)))
M=pd.DataFrame(rows).set_index('m')
# book monthly return by exit month, equity at month start
eq=10000+d.pnl_usdt.cumsum()
for m in months:
    ms=m.start_time.tz_localize('UTC')
    eq0=10000+d.pnl_usdt[d.xt<ms].sum(); pn=d.pnl_usdt[(d.xt>=ms)&(d.xt<(m+1).start_time.tz_localize('UTC'))].sum()
    M.loc[m,'ret']=pn/eq0
g=d.groupby('em'); M['nR']=g.R.size(); M['meanR']=g.R.mean(); M['WR']=g.R.apply(lambda z:(z>0).mean())
M['split']=np.where(M.index.to_timestamp()<pd.Timestamp('2025-01-01'),'TRAIN','TEST')
print(M.round(3).to_string())
print('index total log', L('IDX',[END.floor('h')])[0]-L('IDX',[start])[0], 'BTC', L('BTC',[END.floor('h')])[0]-L('BTC',[start])[0])
# ---- (2) long/short x up/down
d=d.join(M.idx.rename('midx'),on='em'); d['up']=d.midx>0; d['L']=d.sg>0
def mbm(g_,col='R',B=4000):
    gs=[x[col].values for _,x in g_.groupby('em')]
    return np.percentile([np.concatenate([gs[i] for i in rng.integers(0,len(gs),len(gs))]).mean() for _ in range(B)],[2.5,97.5])
print('\nlong/short x up/down months (entry-month index sign):')
for (u,l),g_ in d.groupby(['up','L']):
    ci=mbm(g_); print(f'  {"UP" if u else "DOWN"} {"long" if l else "short"} n={len(g_)} R={g_.R.mean():+.3f} [{ci[0]:+.3f},{ci[1]:+.3f}] WR={(g_.R>0).mean():.3f}')
print('  months UP/DOWN', d.groupby('up').em.nunique().to_dict(), 'long share', d.groupby('up').L.mean().round(3).to_dict())
for sub in ['ALL','TRAIN','TEST']:
    g_=d if sub=='ALL' else d[d.split==sub]
    al=(g_.L==g_.up).astype(float).values
    b,se,r2,G,p,tc=ols(g_.R.values,al,g_.em.values); print(f'  {sub} aligned-vs-against diff {f(b[1],se[1],p[1],tc)} (aligned {g_.R[al==1].mean():+.3f} n={int(al.sum())}, against {g_.R[al==0].mean():+.3f})')
b,se,r2,G,p,tc=ols(d.R.values,np.column_stack([d.L,d.up,d.L*d.up]).astype(float),d.em.values); print('  interaction',f(b[3],se[3],p[3],tc))
b,se,r2,G,p,tc=ols(d.R.values,d.L.astype(float).values,d.em.values); print('  long - short diff',f(b[1],se[1],p[1],tc))
# does the aligned effect vanish once the trade-life market move is controlled? (mechanical check)
b,se,r2,G,p,tc=ols(d.R.values,np.column_stack([(d.L==d.up).astype(float),d.mi_C/d.sp]),d.em.values); print('  aligned diff controlling trade-life signed move/stop:',f(b[1],se[1],p[1],tc))
# placebo: random-time trades aligned? skip. monthly beta
Mm=M.copy()
b,se,r2,G,p,tc=ols(Mm.ret.values,Mm.idx.values,np.arange(len(Mm))); print(f'\nmonthly ret ~ idx: beta {f(b[1],se[1],p[1],tc)} R2={r2:.3f} n={len(Mm)}; alpha {b[0]:+.3f}')
b,se,r2,G,p,tc=ols(Mm.ret.values,Mm.btc.values,np.arange(len(Mm))); print(f'monthly ret ~ btc: beta {f(b[1],se[1],p[1],tc)} R2={r2:.3f}')
b,se,r2,G,p,tc=ols(Mm.ret.values,np.column_stack([Mm.idx,Mm.idx.abs()]),np.arange(len(Mm))); print(f'monthly ret ~ idx+|idx|: |idx| {f(b[2],se[2],p[2],tc)}')
# ---- (3) ER terciles
cuts=M.er.quantile([1/3,2/3]).values; M['ter']=pd.cut(M.er,[-1,*cuts,2],labels=['CHOP','MID','TREND'])
print('\nER cutoffs',cuts.round(3), 'corr(ER,|idx|)', round(stats.spearmanr(M.er,M.idx.abs())[0],3))
d=d.join(M[['ter','er']],on='em')
for sub in ['ALL','TRAIN','TEST']:
    Ms=M if sub=='ALL' else M[M.split==sub]; ds=d if sub=='ALL' else d[d.split==sub]
    line=[]
    for t in ['CHOP','MID','TREND']:
        gm=Ms[Ms.ter==t]; gt=ds[ds.ter==t]
        ci=mbm(gt,B=2000) if len(gt) else [np.nan]*2
        line.append(f'{t}: {len(gm)}mo {len(gt)}tr R={gt.R.mean():+.3f}[{ci[0]:+.2f},{ci[1]:+.2f}] WR={(gt.R>0).mean():.3f} ret={100*gm.ret.mean():+.1f}%')
    rs=stats.spearmanr(Ms.er,Ms.ret); kw=stats.kruskal(*[Ms.ret[Ms.ter==t] for t in ['CHOP','MID','TREND'] if (Ms.ter==t).sum()>0])
    print(f'  {sub}: '+' | '.join(line)+f' | rho(ER,ret)={rs[0]:+.3f} p={rs[1]:.2f} KW p={kw.pvalue:.2f}')
for k in ['donchian','squeeze','mean_rev']:
    ds=d[d.kol==k]; b,se,r2,G,p,tc=ols(ds.R.values,ds.er.values,ds.em.values)
    print(f'  {k}: tercile R', ds.groupby('ter',observed=False).R.mean().round(3).tolist(), 'slope on ER', f(b[1],se[1],p[1],tc))
# sleeve x ER interaction test (joint)
X=np.column_stack([d.er*(d.kol=='donchian'),d.er*(d.kol=='mean_rev'),(d.kol=='donchian'),(d.kol=='mean_rev'),d.er]).astype(float)
b,se,r2,G,p,tc=ols(d.R.values,X,d.em.values); print('  donchian-vs-squeeze ER slope diff',f(b[1],se[1],p[1],tc),' mean_rev-vs-squeeze',f(b[2],se[2],p[2],tc))
# ---- lagged
M['er_lag']=M.er.shift(1); Ml=M.dropna(subset=['er_lag'])
for y in ['ret','meanR']:
    pr=stats.pearsonr(Ml.er_lag,Ml[y]); sr=stats.spearmanr(Ml.er_lag,Ml[y])
    print(f'\nlag ER vs {y}: r={pr[0]:+.3f} p={pr[1]:.3f}; rho={sr[0]:+.3f} p={sr[1]:.3f}; n={len(Ml)}')
for sub in ['TRAIN','TEST']:
    g_=Ml[Ml.split==sub]; pr=stats.pearsonr(g_.er_lag,g_.ret); print(f'  {sub}: r={pr[0]:+.3f} p={pr[1]:.3f} n={len(g_)}')
print('ACF1 ER', np.round(stats.pearsonr(Ml.er,Ml.er_lag),3), 'ACF1 ret', np.round(stats.pearsonr(Ml.ret,M.ret.shift(1).dropna()),3))
# ---- dispersion of monthly mean R vs iid
obs=M.meanR.std(); ns=M.nR.values.astype(int); allR=d.R.values
sims=[]
for _ in range(5000):
    p=rng.permutation(allR); c=np.cumsum(np.r_[0,ns]); sims.append(np.std([p[c[i]:c[i+1]].mean() for i in range(len(ns))],ddof=1))
sims=np.array(sims); print(f'\nSD monthly meanR obs {obs:.3f} null median {np.median(sims):.3f} [{np.percentile(sims,2.5):.3f},{np.percentile(sims,97.5):.3f}] p={np.mean(sims>=obs):.3f}')
# same for monthly equity returns? chi2 on WR
w=d.groupby('em').R.apply(lambda z:(z>0).sum()); n_=M.nR; pbar=w.sum()/n_.sum()
chi=(((w-n_*pbar)**2)/(n_*pbar*(1-pbar))).sum(); print(f'monthly WR overdispersion chi2={chi:.1f} df={len(n_)-1} p={stats.chi2.sf(chi,len(n_)-1):.3f}')
# ---- overlapping pairs
e=d.et.values; x=d.xa.values; sg=d.sg.values; R=d.R.values
I,J=np.triu_indices(len(d),1); ov=(e[I]<x[J])&(e[J]<x[I]); I=I[ov];J=J[ov]
same=sg[I]==sg[J]
print(f'\noverlapping pairs (corrected exit) {len(I)}, same-dir share {same.mean():.3f}; corr R same-dir {np.corrcoef(R[I[same]],R[J[same]])[0,1]:+.3f} opp-dir {np.corrcoef(R[I[~same]],R[J[~same]])[0,1]:+.3f}')
# lag-1 autocorrelation by entry order, split by overlap of consecutive trades
o=np.argsort(d.et.values,kind='stable'); Ro=R[o]; eo=e[o]; xo=x[o]
ovl=eo[1:]<xo[:-1]
print(f'lag-1 autocorr (entry order) all {np.corrcoef(Ro[:-1],Ro[1:])[0,1]:+.3f} n={len(Ro)-1}; consecutive overlapping {np.corrcoef(Ro[:-1][ovl],Ro[1:][ovl])[0,1]:+.3f} n={ovl.sum()}; non-overlapping {np.corrcoef(Ro[:-1][~ovl],Ro[1:][~ovl])[0,1]:+.3f} n={(~ovl).sum()} (p={stats.pearsonr(Ro[:-1][~ovl],Ro[1:][~ovl])[1]:.2f})')
# exit-order lag1 (what streaks use)
o2=np.argsort(d.xt.values,kind='stable'); R2_=R[o2]; print('lag-1 autocorr exit order', round(np.corrcoef(R2_[:-1],R2_[1:])[0,1],3))
# bad months
M['bad']=M.ret<0
for c in ['idx','er','vol','nR']:
    print(f'bad vs good {c}: bad mean {M[M.bad][c].mean():.3f} good {M[~M.bad][c].mean():.3f} MWU p={stats.mannwhitneyu(M[M.bad][c],M[~M.bad][c]).pvalue:.2f}')
print('bad months',M.bad.sum(),'of',len(M))
M.to_pickle(f'{OUT}/M.pkl')
