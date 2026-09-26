import json, numpy as np, pandas as pd
from scipy import stats
ROOT='/home/user/Bot2'
OUT='/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/rev2'
COINS=['SOL','ETH','ADA','NEAR','BCH','ICP','BNB','XRP','DOGE','XLM','LTC']
SPLIT=pd.Timestamp('2025-01-01',tz='UTC')
rng=np.random.default_rng(7)
# --- bars
O={};H={};Lo={};Cl={}
for c in COINS+['BTC']:
    x=pd.read_csv(f'{ROOT}/data/{c}_fut_1h.csv'); x['ts']=pd.to_datetime(x.ts,utc=True); x=x.set_index('ts').sort_index()
    x=x[~x.index.duplicated()]
    O[c]=x.open;H[c]=x.high;Lo[c]=x.low;Cl[c]=x.close
full=pd.date_range(min(v.index.min() for v in Cl.values()),max(v.index.max() for v in Cl.values()),freq='1h')
Cl=pd.DataFrame(Cl).reindex(full).ffill(); O=pd.DataFrame(O).reindex(full); H=pd.DataFrame(H).reindex(full); Lo=pd.DataFrame(Lo).reindex(full)
print('missing bars per coin', Cl.isna().sum().to_dict())
r=Cl/Cl.shift(1)-1   # return of bar ts (close_ts / close_{ts-1})
idx_r=r[COINS].mean(axis=1)
# level at wall clock T = cum log up to close of bar T-1h ; store series indexed by bar ts then shift +1h
lvl=pd.DataFrame(index=full)
lvl['IDX']=np.log1p(idx_r.fillna(0)).cumsum()
lvl['BTC']=np.log(Cl.BTC).ffill()
for c in COINS:
    lvl['LOO_'+c]=np.log1p(r[[o for o in COINS if o!=c]].mean(axis=1).fillna(0)).cumsum()
    lvl['OWN_'+c]=np.log(Cl[c]).ffill()
lvl.index=lvl.index+pd.Timedelta('1h')
def L(col,T):
    T=pd.DatetimeIndex(T); pos=lvl.index.get_indexer(T)
    v=lvl[col].values[np.clip(pos,0,None)].astype(float); v[pos<0]=np.nan; return v
def Lc(cols,T):
    T=pd.DatetimeIndex(T); pos=lvl.index.get_indexer(T); assert (pos>=0).all()
    ci=[lvl.columns.get_loc(c) for c in cols]; return lvl.values[pos,ci]
# --- trades
d=pd.read_csv(f'{ROOT}/ikiz_k25_cap25_islemler.csv')
s=d.strategy_scores.apply(json.loads)
d['ie']=s.map(lambda z:z['intended_entry']); d['sl0']=s.map(lambda z:z['sl0']); d['mh']=s.map(lambda z:z.get('max_hold',np.nan))
d['coin']=d.symbol.str.split('/').str[0]
d['et']=pd.to_datetime(d.entry_time,utc=True); d['xt']=pd.to_datetime(d.exit_time,utc=True)
d['sg']=np.where(d.side=='long',1,-1)
d['sp']=(d.ie-d.sl0).abs()/d.ie
d['R']=d.pnl_usdt/(d.quantity*(d.ie-d.sl0).abs())
d=d.sort_values(['xt','et']).reset_index(drop=True)
d['eqb']=10000+d.pnl_usdt.cumsum().shift(fill_value=0); d['req']=d.pnl_usdt/d.eqb
d['split']=np.where(d.xt<SPLIT,'TRAIN','TEST')
d['em']=d.et.dt.tz_convert(None).dt.to_period('M'); d['xm']=d.xt.dt.tz_convert(None).dt.to_period('M')
d['xa']=d.xt-pd.Timedelta('1h')   # actual exit wall-clock (max_hold fill = open of bar xt-1h; SL/TP touched in bar xt-2h)
for tag,T in [('A',d.xt),('C',d.xa)]:
    d['mi_'+tag]=d.sg*(L('IDX',T)-L('IDX',d.et))
    d['mb_'+tag]=d.sg*(L('BTC',T)-L('BTC',d.et))
    d['ml_'+tag]=d.sg*(Lc(['LOO_'+c for c in d.coin],T).diagonal() if False else np.array([L('LOO_'+c,[t])[0] for c,t in zip(d.coin,T)])-np.array([L('LOO_'+c,[t])[0] for c,t in zip(d.coin,d.et)]))
print('n',len(d),'sumR',d.R.sum().round(2),'meanR',d.R.mean().round(4),'long share',(d.sg>0).mean().round(3))

def ols(y,X,g):
    y=np.asarray(y,float); ok=~np.isnan(y)
    if X is not None: ok&=~np.isnan(np.asarray(X,float)).reshape(len(y),-1).any(1); X=np.asarray(X,float)[ok]
    y=y[ok]; g=np.asarray(g)[ok]
    X=np.column_stack([np.ones(len(y))]+([X] if X is not None and np.ndim(X)==1 else ([] if X is None else [X]))); y=np.asarray(y,float)
    XtXi=np.linalg.pinv(X.T@X); b=XtXi@X.T@y; e=y-X@b
    gi=pd.factorize(g)[0]; G=gi.max()+1; k=X.shape[1]; n=len(y)
    meat=np.zeros((k,k))
    for j in range(G):
        sj=X[gi==j].T@e[gi==j]; meat+=np.outer(sj,sj)
    V=XtXi@meat@XtXi*G/(G-1)*(n-1)/(n-k); se=np.sqrt(np.diag(V))
    r2=1-e@e/((y-y.mean())@(y-y.mean())) if y.std()>0 else np.nan
    tc=stats.t.ppf(.975,G-1); p=2*stats.t.sf(abs(b/se),G-1)
    return b,se,r2,G,p,tc
def f(b,se,p,tc): return f'{b:+.3f} [{b-tc*se:+.3f},{b+tc*se:+.3f}] p={p:.3g}'

print('\n=== (1) R ~ signed market move over trade life; A=analyst exit level (xt), C=corrected (xt-1h)')
res={}
for sub in ['ALL','TRAIN','TEST']:
    g=d if sub=='ALL' else d[d.split==sub]
    for tag in ['A','C']:
        for mk in ['mi','ml','mb']:
            for unit in ['pct','stop']:
                x=g[f'{mk}_{tag}'].values*100 if unit=='pct' else g[f'{mk}_{tag}'].values/g.sp.values
                b,se,r2,G,p,tc=ols(g.R.values,x,g.em.values)
                share=b[1]*x.sum()/g.R.sum()
                res[(sub,tag,mk,unit)]=(b,se,r2,share)
                if sub=='ALL' or mk=='mi':
                    print(f'{sub:5s} {tag} {mk} {unit:4s} alpha {f(b[0],se[0],p[0],tc)} slope {b[1]:.3f}±{tc*se[1]:.3f} R2={r2:.3f} mkt share {100*share:.0f}%  mean x {x.mean():+.3f}')
# bootstrap CI for market share (month blocks)
def mboot(g,fun,B=3000):
    groups=[gg for _,gg in g.groupby('em')]; out=[]
    for _ in range(B):
        bb=pd.concat([groups[i] for i in rng.integers(0,len(groups),len(groups))]); out.append(fun(bb))
    return np.nanpercentile(out,[2.5,97.5])
def share_fun(tag,mk,unit):
    def fn(g):
        x=g[f'{mk}_{tag}'].values*100 if unit=='pct' else g[f'{mk}_{tag}'].values/g.sp.values
        X=np.column_stack([np.ones(len(x)),x]); b=np.linalg.lstsq(X,g.R.values,rcond=None)[0]
        return b[1]*x.sum()/g.R.sum()
    return fn
for tag in ['A','C']:
    for unit in ['pct','stop']:
        ci=mboot(d,share_fun(tag,'mi',unit),2000)
        print(f'market share {tag} idx {unit}: {100*res[("ALL",tag,"mi",unit)][3]:.0f}%  month-boot 95% CI [{100*ci[0]:.0f}%,{100*ci[1]:.0f}%]')
# equity-return space
for tag in ['A','C']:
    x=d['mi_'+tag].values*100; b,se,r2,G,p,tc=ols(d.req.values*100,x,d.em.values)
    print(f'equity space {tag}: alpha {f(b[0],se[0],p[0],tc)} %/trade slope {b[1]:.3f} R2={r2:.3f} mkt {b[1]*x.sum():.1f} of {100*d.req.sum():.1f} %-pts')
# S-shape
q=pd.qcut(d.mi_C/d.sp,5,labels=False)
print('R by quintile of signed idx move (stop units, corrected):',d.groupby(q).R.mean().round(3).tolist())
nz=d[(d.mi_C/d.sp).abs()<0.25]; b,se,r2,G,p,tc=ols(nz.R.values,None,nz.em.values)
print(f'|move|<0.25 stop (C): n={len(nz)} meanR {f(b[0],se[0],p[0],tc)}')
nz=d[(d.mi_A/d.sp).abs()<0.25]; b,se,r2,G,p,tc=ols(nz.R.values,None,nz.em.values)
print(f'|move|<0.25 stop (A): n={len(nz)} meanR {f(b[0],se[0],p[0],tc)}')

print('\n=== (2a) mean signed move over trade life, cluster by entry month')
for sub in ['ALL','TRAIN','TEST']:
    g=d if sub=='ALL' else d[d.split==sub]
    for c in ['mi_A','mi_C','ml_C','mb_C']:
        b,se,r2,G,p,tc=ols(g[c].values*100,None,g.em.values)
        print(f'  {sub:5s} {c}: {f(b[0],se[0],p[0],tc)} %')
# hours held (corrected) by exit reason
d['hold']=(d.xa-d.et)/pd.Timedelta('1h')
print(d.groupby('exit_reason').agg(n=('R','size'),hold_med=('hold','median'),mv_med=('mi_C',lambda z:100*z.median()),mv_mean=('mi_C',lambda z:100*z.mean())).round(2))
# post-exit signed index move: is there reversal after exits? (tests "TP banks moves before they reverse")
for h in [24,48]:
    pe=d.sg*(L('IDX',d.xa+pd.Timedelta(f'{h}h'))-L('IDX',d.xa))*100
    for why in ['sl_hit','tp_hit','max_hold']:
        m=(d.exit_reason==why).values; b,se,r2,G,p,tc=ols(pe[m],None,d.em.values[m])
        print(f'  post-exit +{h}h signed idx move after {why}: {f(b[0],se[0],p[0],tc)} % n={m.sum()}')
    b,se,r2,G,p,tc=ols(pe,None,d.em.values); print(f'  post-exit +{h}h all: {f(b[0],se[0],p[0],tc)}')
# fixed horizons from entry
print('fixed-horizon signed moves from entry (%):')
for h in [-24,4,24,48,120]:
    for mk in ['IDX','BTC']:
        a=L(mk,d.et+pd.Timedelta(f'{h}h')); b0=L(mk,d.et)
        mv=d.sg*((b0-a) if h<0 else (a-b0))*100
        b,se,r2,G,p,tc=ols(mv.values,None,d.em.values)
        print(f'  {mk} h={h:+d}: {f(b[0],se[0],p[0],tc)}')
d.to_pickle(f'{OUT}/d.pkl'); lvl.to_pickle(f'{OUT}/lvl.pkl')
