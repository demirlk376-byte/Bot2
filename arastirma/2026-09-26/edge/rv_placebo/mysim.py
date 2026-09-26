import numpy as np, pandas as pd
from base import bars
RRm={"donchian":2.5,"squeeze":2.5,"mean_rev":1.667}
MHm={"donchian":120,"squeeze":48,"mean_rev":48}
SLIPm={"donchian":15.85e-4,"squeeze":15.85e-4,"mean_rev":0.0}
FINm={"donchian":1e-4,"squeeze":1e-4,"mean_rev":0.0}
XSLIP=0.24e-4; FOUT=1e-4
class Arr:
    def __init__(s,c):
        b=bars(c); s.ts=b.index.values.astype("datetime64[s]").astype(np.int64)
        s.o=b.open.values; s.h=b.high.values; s.l=b.low.values; s.c=b.close.values; s.n=len(b)
_A={}
def A(c):
    if c not in _A: _A[c]=Arr(c)
    return _A[c]
def sim(a, k0, s, P, Dp, sleeve, start_off=0, mh=None, costs=True):
    """independent re-implementation. k0: entry bar index (entry at open[k0]=P).
    bars checked: k0+start_off .. k0+start_off+mh-1 ; stop first on double touch.
    returns gross R (price move / Dp), net R, exit code 0=sl 1=tp 2=mh, exit bar"""
    RR=RRm[sleeve]; mh=mh or MHm[sleeve]
    k0=np.asarray(k0); s=np.asarray(s,float); P=np.asarray(P,float); Dp=np.asarray(Dp,float)
    n=len(k0); R=np.empty(n); G=np.empty(n); X=np.empty(n,int); KX=np.empty(n,int)
    step=20000
    for a0 in range(0,n,step):
        sl_=slice(a0,a0+step)
        kk=k0[sl_]; ss=s[sl_]; PP=P[sl_]; DD=Dp[sl_]
        idx=np.clip(kk[:,None]+start_off+np.arange(mh)[None,:],0,a.n-1)
        hi=a.h[idx]; lo=a.l[idx]
        stop=PP-ss*DD; tgt=PP+ss*RR*DD
        # favourable / adverse extremes in trade direction
        adv=np.where(ss[:,None]>0, lo<=stop[:,None], hi>=stop[:,None])
        fav=np.where(ss[:,None]>0, hi>=tgt[:,None], lo<=tgt[:,None])
        big=mh+10
        fa=np.where(adv.any(1), adv.argmax(1), big); ff=np.where(fav.any(1), fav.argmax(1), big)
        isl=(fa<big)&(fa<=ff); itp=(ff<big)&(ff<fa)
        kx=np.where(isl,fa,np.where(itp,ff,mh-1))+kk+start_off
        kx=np.clip(kx,0,a.n-1)
        xraw=np.where(isl,stop,np.where(itp,tgt,a.c[kx]))
        g=ss*(xraw-PP)/DD
        if costs:
            slip=SLIPm[sleeve]; ep=PP*(1+ss*slip)
            xp=np.where(itp,xraw,xraw*(1-ss*XSLIP))
            pnl=ss*(xp-ep)-ep*FINm[sleeve]-xp*FOUT
            r=pnl/DD
        else: r=g
        R[sl_]=r; G[sl_]=g; X[sl_]=np.where(isl,0,np.where(itp,1,2)); KX[sl_]=kx
    return G,R,X,KX
