import numpy as np, pandas as pd
from scipy import stats
exec(open('rev.py').read().split("# --- trades")[0])   # rebuild bars/lvl/L
exec("def ols"+open('rev.py').read().split("def ols")[1].split("def f(")[0])
def f(b,se,p,tc): return f'{b:+.3f} [{b-tc*se:+.3f},{b+tc*se:+.3f}] p={p:.3g}'
d=pd.read_pickle(f'{OUT}/d.pkl')
# ---- own-coin fixed horizon decomposition
lr=np.log1p(r)
beta={}
for c in COINS:
    y=lr[c]; x=np.log1p(r[[o for o in COINS if o!=c]].mean(axis=1)); ok=y.notna()&x.notna()
    beta[c]=np.cov(y[ok],x[ok])[0,1]/x[ok].var()
d['beta']=d.coin.map(beta)
print('betas',{k:round(v,2) for k,v in beta.items()})
for h in [24,48]:
    T=d.et+pd.Timedelta(f'{h}h')
    own=np.array([L('OWN_'+c,[t])[0] for c,t in zip(d.coin,T)])-np.array([L('OWN_'+c,[t])[0] for c,t in zip(d.coin,d.et)])
    loo=np.array([L('LOO_'+c,[t])[0] for c,t in zip(d.coin,T)])-np.array([L('LOO_'+c,[t])[0] for c,t in zip(d.coin,d.et)])
    so=d.sg*own/d.sp; sm=d.sg*d.beta*loo/d.sp; si=so-sm
    slip=np.log(d.entry_price/d.ie).abs()/d.sp   # slippage cost in stop units
    for sub in ['ALL','TRAIN','TEST']:
        m=np.ones(len(d),bool) if sub=='ALL' else (d.split==sub).values
        out=[]
        for nm,v in [('own',so),('mkt',sm),('idio',si),('own-net-slip',so-slip)]:
            b,se,r2,G,p,tc=ols(v.values[m],None,d.em.values[m]); out.append(f'{nm} {f(b[0],se[0],p[0],tc)}')
        print(f'h={h} {sub}: '+' | '.join(out))
    if h==48:
        for k in ['donchian','squeeze','mean_rev']:
            m=(d.kol==k).values
            print('   ',k,' | '.join(f'{nm} {ols(v.values[m],None,d.em.values[m])[0][0]:+.3f} p={ols(v.values[m],None,d.em.values[m])[4][0]:.2g}' for nm,v in [('own',so),('mkt',sm),('idio',si)]))
# ---- placebo: random entry time, same coin/side/stop/RR/maxhold, simulate exits on 1h bars -> signed index move over life
Hh=H.values; Ll=Lo.values; Cc=Cl.values; Oo=O.values; cidx={c:i for i,c in enumerate(Cl.columns)}
IDXlvl=np.log1p(idx_r.fillna(0)).cumsum().values   # level after close of bar i
tsi=pd.DatetimeIndex(full)
def mh_of(r_):
    return {'donchian':120,'squeeze':48,'mean_rev':48}[r_.kol]
RR={'donchian':2.5,'squeeze':2.5,'mean_rev':1.667}
valid_lo=np.searchsorted(tsi,d.et.min()); valid_hi=np.searchsorted(tsi,d.et.max())
K=30; plc=[]; plcR=[]
for _,t in d.iterrows():
    ci=cidx[t.coin]; mh=mh_of(t); rr=RR[t.kol]
    starts=rng.integers(valid_lo,valid_hi-mh-2,K)
    for s0 in starts:
        # entry at open of bar s0 (= close of s0-1), index level at start = IDXlvl[s0-1]
        e=Cc[s0-1,ci]
        if np.isnan(e): continue
        if t.sg>0: sl=e*(1-t.sp); tp=e*(1+rr*t.sp)
        else: sl=e*(1+t.sp); tp=e*(1-rr*t.sp)
        hi=Hh[s0:s0+mh,ci]; lo=Ll[s0:s0+mh,ci]
        if t.sg>0: slh=lo<=sl; tph=hi>=tp
        else: slh=hi>=sl; tph=lo<=tp
        any_=slh|tph
        if any_.any():
            j=np.argmax(any_); R_=-1 if slh[j] else rr
        else:
            j=mh-1; R_=t.sg*(Cc[s0+j,ci]-e)/(e*t.sp)
        plc.append(t.sg*(IDXlvl[s0+j]-IDXlvl[s0-1])*100); plcR.append(R_)
plc=np.array(plc); plcR=np.array(plcR)
print(f'placebo random-time trades (same coin/side/stop/RR/maxhold, K={K}/trade, n={len(plc)}): mean signed idx move over life {plc.mean():+.3f}% (se {plc.std()/np.sqrt(len(plc)):.3f}); mean gross R {plcR.mean():+.3f}')
# null distribution of a 936-trade mean: resample one placebo per trade
P=plc.reshape(len(d),-1) if len(plc)==len(d)*K else None
if P is not None:
    sims=P[np.arange(len(d))[:,None],rng.integers(0,K,(len(d),5000))].mean(0)
    print(f'  null 936-trade mean: median {np.median(sims):+.3f}%, 95% [{np.percentile(sims,2.5):+.3f},{np.percentile(sims,97.5):+.3f}] ; observed C {100*d.mi_C.mean():+.3f}% -> one-sided p {np.mean(sims>=100*d.mi_C.mean()):.3f} (iid; ignores clustering)')
# regression slope/R2 for placebo trades: R_gross ~ signed move
X=np.column_stack([np.ones(len(plc)),plc]); b=np.linalg.lstsq(X,plcR,rcond=None)[0]; e=plcR-X@b
print(f'  placebo R ~ move: alpha {b[0]:+.3f} slope {b[1]:.3f} R2 {1-e.var()/plcR.var():.3f} share {b[1]*plc.sum()/plcR.sum():.2f} (meanR {plcR.mean():+.3f})')
np.save(f'{OUT}/plc.npy',np.vstack([plc,plcR]))
