import sys; sys.path.insert(0,".")
from base import *; from mysim import *
import time
path=sys.argv[1]; tag=sys.argv[2]; K=int(sys.argv[3])
t=trades(path).reset_index(drop=True)
t["k"]=[bars(c).index.get_indexer([x])[0] for c,x in zip(t.coin,t.tin)]
assert (t.k>0).all()
rng=np.random.default_rng(777)
SPL=int(pd.Timestamp("2025-01-01",tz="UTC").timestamp())
N=len(t); P={}
names=["c","d","b","bf","bb","c_nc","a_nc"]
for nm in names: P[nm]=np.full((N,K),np.nan)
t["R"]=np.nan; t["Ropp"]=np.nan; t["G"]=np.nan; t["Gopp"]=np.nan
delays=[1,2,3,4,6,8,12,24,48,-1,-2,-4,-8,-24]
for dl in delays: t[f"dl{dl}"]=np.nan
t0=time.time()
for (c,sv),g in t.groupby(["coin","sleeve"]):
    a=A(c); ix=g.index.values; n=len(ix); mh=MHm[sv]
    k=g.k.values; s=g.s.values; sp=g.sp.values
    G,R,X,KX=sim(a,k,s,g.ie.values,g.Dp.values,sv); t.loc[ix,"R"]=R; t.loc[ix,"G"]=G
    G2,R2,_,_=sim(a,k,-s,g.ie.values,g.Dp.values,sv); t.loc[ix,"Ropp"]=R2; t.loc[ix,"Gopp"]=G2
    lo0=250; hi0=a.n-mh-2
    def run(kn,dn,costs=True):
        kn=np.clip(kn,lo0,hi0).ravel(); dn=np.broadcast_to(dn,(n,K)).ravel() if np.ndim(dn)==2 else dn.ravel()
        Pn=a.o[kn]; Dn=np.repeat(sp,K)*Pn
        Gx,Rx,_,_=sim(a,kn,dn,Pn,Dn,sv,costs=costs)
        return Rx.reshape(n,K)
    for dl in delays:
        kn=np.clip(k+dl,lo0,hi0)
        _,Rd,_,_=sim(a,kn,s,a.o[kn],sp*a.o[kn],sv); t.loc[ix,f"dl{dl}"]=Rd
    ksp=np.searchsorted(a.ts,SPL)
    tr=g.tr.values
    lo=np.where(tr,lo0,ksp); hi=np.where(tr,ksp-mh,hi0)
    kr=(lo[:,None]+rng.random((n,K))*(hi-lo)[:,None]).astype(int)
    rd=rng.choice([-1.0,1.0],size=(n,K)); sK=np.repeat(s[:,None],K,1)
    P["c"][ix]=run(kr,rd); P["d"][ix]=run(kr,sK); P["c_nc"][ix]=run(kr,rd,costs=False)
    sh=rng.integers(24,721,size=(n,K))
    P["bf"][ix]=run(k[:,None]+sh,sK)
    P["bb"][ix]=run(k[:,None]-sh,sK)
    sgn=rng.choice([-1,1],size=(n,K)); P["b"][ix]=run(k[:,None]+sgn*sh,sK)
    # cost-free random direction at actual time (a without costs): exact
    print(c,sv,n,round(time.time()-t0,1),flush=True)
t.to_pickle(f"{tag}_t.pkl"); np.savez_compressed(f"{tag}_P.npz",**P)
