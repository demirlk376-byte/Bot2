"""IKI BAGIMSIZ MEXC CEKIMI KARSILASTIRMASI: data/X_fut_1h.csv (ankor) vs data/X_uyum_1h.csv (2026-09-09 cekimi)"""
import glob,os,numpy as np,pandas as pd
print(f"{'coin':6s} {'ortak':>6s} {'o!=':>5s} {'h!=':>5s} {'l!=':>5s} {'c!=':>5s} {'v!=':>5s} {'maxCbp':>8s} {'maxHbp':>8s} {'maxLbp':>8s} {'maxVfark%':>10s}")
tot=dict(n=0,c=0,h=0,l=0,v=0)
worst=[]
for f in sorted(glob.glob("/home/user/Bot2/data/*_uyum_1h.csv")):
    coin=os.path.basename(f).replace("_uyum_1h.csv","")
    a=pd.read_csv(f"/home/user/Bot2/data/{coin}_fut_1h.csv",index_col=0,parse_dates=True)
    b=pd.read_csv(f,index_col=0,parse_dates=True)
    ix=a.index.intersection(b.index)
    A=a.loc[ix]; B=b.loc[ix]
    def bp(x,y): 
        return np.abs(x-y)/np.where(y!=0,np.abs(y),np.nan)*1e4
    dc=bp(A.close.values,B.close.values); dh=bp(A.high.values,B.high.values); dl=bp(A.low.values,B.low.values)
    do=bp(A.open.values,B.open.values)
    dv=np.abs(A.volume.values-B.volume.values)/np.where(B.volume.values!=0,B.volume.values,np.nan)*100
    ne=lambda x,y:int((x!=y).sum())
    print(f"{coin:6s} {len(ix):6d} {ne(A.open.values,B.open.values):5d} {ne(A.high.values,B.high.values):5d} "
          f"{ne(A.low.values,B.low.values):5d} {ne(A.close.values,B.close.values):5d} {ne(A.volume.values,B.volume.values):5d} "
          f"{np.nanmax(dc):8.2f} {np.nanmax(dh):8.2f} {np.nanmax(dl):8.2f} {np.nanmax(dv):10.2f}")
    tot['n']+=len(ix); tot['c']+=ne(A.close.values,B.close.values); tot['h']+=ne(A.high.values,B.high.values)
    tot['l']+=ne(A.low.values,B.low.values); tot['v']+=ne(A.volume.values,B.volume.values)
    k=np.nanargmax(np.nanmax(np.c_[dc,dh,dl],axis=1))
    worst.append((np.nanmax(np.c_[dc,dh,dl]),coin,ix[k],A.iloc[k].to_dict(),B.iloc[k].to_dict()))
print(f"\nTOPLAM ortak bar {tot['n']}  farkli: close {tot['c']} high {tot['h']} low {tot['l']} volume {tot['v']}")
print("\n--- en buyuk 5 sapma ---")
for d,coin,ts,A,B in sorted(worst,reverse=True)[:5]:
    print(f"  {coin} {ts} sapma {d:.2f}bp\n     fut : {A}\n     uyum: {B}")
