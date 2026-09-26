import sys; sys.path.insert(0,".")
import numpy as np, pandas as pd
tag=sys.argv[1]; clus=sys.argv[2] if len(sys.argv)>2 else "month"
t=pd.read_pickle(f"{tag}_t.pkl"); P=dict(np.load(f"{tag}_P.npz"))
rng=np.random.default_rng(5)
if clus=="month": t["cl"]=t.tin.dt.strftime("%Y-%m")
elif clus=="week": t["cl"]=t.tin.dt.strftime("%G-%V")
elif clus=="xmonth": t["cl"]=t.tout.dt.strftime("%Y-%m")
elif clus=="quarter": t["cl"]=t.tin.dt.year.astype(str)+"Q"+t.tin.dt.quarter.astype(str)
E={"act":t.R.values,"a":(t.R.values+t.Ropp.values)/2}
for k,v in P.items(): E[k]=v.mean(1)
def cb(x,cl,B=4000):
    u,inv=np.unique(cl,return_inverse=True); s=np.bincount(inv,weights=x); c=np.bincount(inv)
    I=rng.integers(0,len(u),size=(B,len(u))); bm=s[I].sum(1)/c[I].sum(1)
    lo,hi=np.percentile(bm,[2.5,97.5]); p=2*min((bm<=0).mean(),(bm>=0).mean()); return x.mean(),lo,hi,max(p,1/B)
groups=[("ALL",t.index)]+[(f"ALL/{n}",t.index[t.tr==(n=="TRAIN")]) for n in ("TRAIN","TEST")]
for sv in ("donchian","squeeze","mean_rev"):
    groups.append((sv,t.index[t.sleeve==sv]))
    for n in ("TRAIN","TEST"): groups.append((f"{sv}/{n}",t.index[(t.sleeve==sv)&(t.tr==(n=="TRAIN"))]))
comps=[("act",None),("c","geometry+cost"),("d-c","drift"),("a-c","time,no-dir"),("act-a","direction"),("bf-d","late-regime"),("act-bf","act-late"),("b-d","sym regime"),("act-b","act-sym"),("bb-d","bwd regime"),("act-d","act-d")]
print(f"cluster={clus}")
for gn,ix in groups:
    cl=t.loc[ix,"cl"].values; out=[]
    for nm,_ in comps:
        if "-" in nm: x1,x0=nm.split("-"); v=E[x1][ix]-E[x0][ix]
        else: v=E[nm][ix]
        m,lo,hi,p=cb(v,cl); out.append(f"{nm}={m:+.3f}[{lo:+.3f},{hi:+.3f}]p{p:.3f}")
    print(f"{gn:15s} n={len(ix):4d} "+" ".join(out))
