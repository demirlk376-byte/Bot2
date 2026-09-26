import pandas as pd, numpy as np
od=pd.read_pickle('od.pkl'); nd=pd.read_pickle('nd.pkl'); new=pd.read_pickle('new.pkl')
others=new[new.kol!='donchian']
T0=pd.Timestamp('2025-01-01',tz='UTC')
def prep(df):
    df=df[['et','xt','Rn','stop_pct']].copy()
    df['f']=np.minimum(0.035,2.5*df.stop_pct)
    return df
def sim(df, start=None, end=None):
    """realized equity; size at entry on realized equity; book at exit. Exits before entries on ties."""
    if start is not None:
        df=df[(df.et>=start)&(df.et<end)]  # trades entering in the segment
    ev=[]
    for i,(et,xt,R,f) in enumerate(zip(df.et.values,df.xt.values,df.Rn.values,df.f.values)):
        ev.append((et,1,i)); ev.append((xt,0,i))
    ev.sort(key=lambda x:(x[0],x[1]))
    E=1.0; size={}; peak=1.0; mdd=0.0; R=df.Rn.values; F=df.f.values
    for t,typ,i in ev:
        if typ==1: size[i]=E*F[i]
        else:
            E+=size.pop(i)*R[i]; peak=max(peak,E); mdd=max(mdd,1-E/peak)
    return E, mdd
def metrics(df,seg):
    if seg=='TRAIN': s,e=pd.Timestamp('2023-01-01',tz='UTC'),T0
    else: s,e=T0,pd.Timestamp('2027-01-01',tz='UTC')
    E,m=sim(df,s,e)
    sub=df[(df.et>=s)&(df.et<e)]
    yrs=(sub.xt.max()-sub.et.min()).total_seconds()/(365.25*86400)
    cagr=E**(1/yrs)-1
    return np.log(E),m,cagr/m if m>0 else np.nan
if __name__=='__main__':
    O=prep(others)
    full_live=prep(new)
    E,m=sim(full_live); print('live whole sim final x10000',E*1e4,'maxDD',m)
    var={'unfiltered':pd.concat([prep(od),O]),'live_filtered':pd.concat([prep(nd),O]),
         'passed_subset':pd.concat([prep(od[od.vr>=2.5]),O]),'kept_only':pd.concat([prep(od[od.grp=='kept']),O]),
         'others_only':O}
    for seg in ['TRAIN','TEST']:
        for k,v in var.items():
            lr,mdd,mar=metrics(v,seg); print(f'{seg} {k:14s} logret={lr:.2f} maxDD={mdd:.3f} MAR={mar:.2f}')
