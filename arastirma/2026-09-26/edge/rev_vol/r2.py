import pandas as pd, numpy as np
from scipy import stats
def proportion_confint(k,n,method='wilson'):
    z=1.959964; p=k/n; den=1+z*z/n; c=(p+z*z/(2*n))/den; h=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den; return c-h,c+h
O='/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/rev_vol/'
od=pd.read_pickle(O+'od.pkl'); nd=pd.read_pickle(O+'nd.pkl')
rng=np.random.default_rng(1)
d=od
print('R col - Rn: describe'); print((d.R-d.Rn).describe())
print('corr R col vs gross', np.corrcoef(d.R,d.gross)[0,1], 'R - gross max', (d.R-d.gross).abs().max())
def boot(x,n=20000):
    x=np.asarray(x); b=rng.choice(x,(n,len(x))).mean(1); return np.percentile(b,[2.5,97.5])
def wkclust(x,wk,n=10000):
    df=pd.DataFrame({'x':x,'w':wk}); g=df.groupby('w').x.agg(['sum','count'])
    s=g['sum'].values;c=g['count'].values;k=len(g)
    idx=rng.integers(0,k,(n,k)); return np.percentile(s[idx].sum(1)/c[idx].sum(1),[2.5,97.5])
d['wk']=d.et.dt.to_period('W').astype(str)
d['pas']=d.vr>=2.5
for h in ['TRAIN','TEST','ALL']:
    s=d if h=='ALL' else d[d.half==h]
    for g,ss in [('removed',s[~s.pas]),('passed',s[s.pas]),('kept',s[s.grp=='kept'])]:
        x=ss.Rn.values; ci=boot(x); wc=wkclust(x,ss.wk.values)
        w=(x>0).sum(); wl=proportion_confint(w,len(x),method='wilson')
        t=stats.ttest_1samp(x,0,alternative='greater')
        print(f'{h:5s} {g:8s} n={len(x):4d} mean={x.mean():+.3f} iidCI[{ci[0]:+.3f},{ci[1]:+.3f}] wkCI[{wc[0]:+.3f},{wc[1]:+.3f}] WR={w/len(x):.3f}[{wl[0]:.3f},{wl[1]:.3f}] sum={x.sum():+.1f} p>0={t.pvalue:.4f} slipR={ss.slipR.mean():.4f} medstop={ss.stop_pct.median():.4f} gross={ss.gross.mean():+.3f}')
    # permutation test removed - passed
    x=s.Rn.values; lab=(~s.pas).values
    obs=x[lab].mean()-x[~lab].mean()
    perm=np.array([ (lambda p: x[p].mean()-x[~p].mean())(rng.permutation(lab)) for _ in range(20000)])
    p1=(perm<=obs).mean()
    # week-cluster bootstrap of the diff
    wks=s.wk.unique(); diffs=[]
    gw={w:grp for w,grp in s.groupby('wk')}
    for _ in range(4000):
        sm=pd.concat([gw[w] for w in rng.choice(wks,len(wks))])
        a=sm.Rn[~sm.pas]; b=sm.Rn[sm.pas]
        if len(a) and len(b): diffs.append(a.mean()-b.mean())
    mw=stats.mannwhitneyu(x[lab],x[~lab],alternative='less')
    sp=stats.spearmanr(s.vr,s.Rn)
    # win-rate fisher
    tab=[[ (x[lab]>0).sum(), (x[lab]<=0).sum()],[(x[~lab]>0).sum(),(x[~lab]<=0).sum()]]
    fp=stats.fisher_exact(tab,alternative='less').pvalue
    print(f'{h} removed-passed={obs:+.3f} perm p(one-sided, <=obs)={p1:.3f} two-sided={(np.abs(perm)>=abs(obs)).mean():.3f} wkclusterCI={np.percentile(diffs,[2.5,97.5]).round(3)} MW p={mw.pvalue:.3f} spearman={sp.statistic:+.3f} p={sp.pvalue:.3f} fisher p={fp:.3f}')
    # MDE
    sd=x.std(ddof=1); n1=lab.sum(); n2=(~lab).sum()
    mde=(stats.norm.ppf(0.95)+stats.norm.ppf(0.8))*sd*np.sqrt(1/n1+1/n2)
    print(f'   MDE80 one-sided={mde:.3f}  sd={sd:.2f}')
# sums
for h in ['TRAIN','TEST']:
    a=d[d.half==h]; b=nd[nd.half==h]
    print(h,'unfilt sum',round(a.Rn.sum(),1),len(a),'filt sum',round(b.Rn.sum(),1),len(b),
          'removed',round(a[a.grp=='removed'].Rn.sum(),1),'displaced',round(a[a.grp=='displaced'].Rn.sum(),1),'newonly',round(b[~b.in_old].Rn.sum(),1),(~b.in_old).sum())
no=nd[~nd.in_old].Rn.values; print('new-only mean',no.mean(),boot(no),len(no), 'min vr newonly', nd[~nd.in_old].vr.min())
rem=d[d.grp=='removed']
print('removed slip total R',rem.slipR.sum(),'fees+fund total', (rem.gross-rem.Rn).sum()-0, 'gross total', rem.gross.sum(), 'net total', rem.Rn.sum())
print('total cost per trade (gross-Rn) mean', (d.gross+d.slipR-d.Rn).mean(), ' (gross from fill) - Rn:', (d.gross-d.Rn).mean())
