import json, numpy as np, pandas as pd
ROOT='/home/user/Bot2'
d=pd.read_csv(f'{ROOT}/ikiz_k25_cap25_islemler.csv')
s=d.strategy_scores.apply(json.loads)
d['ie']=s.map(lambda z:z['intended_entry']); d['sl0']=s.map(lambda z:z['sl0']); d['mh']=s.map(lambda z:z.get('max_hold'))
d['strat']=s.map(lambda z:z['strategy'])
d['coin']=d.symbol.str.split('/').str[0]
d['et']=pd.to_datetime(d.entry_time,utc=True); d['xt']=pd.to_datetime(d.exit_time,utc=True)
print(d.kol.value_counts().to_dict(), (d.strat==d.kol).mean())
print('entry hour mod 4 by kol:'); print(d.groupby('kol').apply(lambda g:(g.et.dt.hour%4).value_counts().to_dict()))
print('exit minute nonzero', (d.xt.dt.minute!=0).sum(), (d.et.dt.minute!=0).sum())
Rn=d.pnl_usdt/(d.quantity*(d.ie-d.sl0).abs())
print('Rn vs R col max abs diff', (Rn-d.R).abs().max())
bars={}
for c in d.coin.unique():
    x=pd.read_csv(f'{ROOT}/data/{c}_fut_1h.csv'); x['ts']=pd.to_datetime(x.ts,utc=True); bars[c]=x.set_index('ts')
# intended entry vs close of bar et-1h, open of bar et
r1=[];r2=[]
for c,e,ie in zip(d.coin,d.et,d.ie):
    b=bars[c]
    r1.append(b.close.get(e-pd.Timedelta('1h'),np.nan)/ie-1); r2.append(b.open.get(e,np.nan)/ie-1)
r1=np.array(r1);r2=np.array(r2)
print('ie vs close(et-1h): median |diff| bp', np.nanmedian(abs(r1))*1e4, 'share exact(<1bp)', np.nanmean(abs(r1)<1e-4), 'nan', np.isnan(r1).sum())
print('ie vs open(et): median |diff| bp', np.nanmedian(abs(r2))*1e4, 'share exact', np.nanmean(abs(r2)<1e-4))
print('entry_price/ie -1 (bp) median by side', d.groupby('side').apply(lambda g:((g.entry_price/g.ie-1)*1e4).median()).to_dict())
# exit bar check: first bar (ts>=et) touching sl0/tp
lag=[]
for i,r in d.iterrows():
    b=bars[r.coin]; w=b[(b.index>=r.et)&(b.index<=r.xt+pd.Timedelta('6h'))]
    if r.exit_reason=='sl_hit':
        # use current sl_price (could be trailed?) use sl_price col
        sl=r.sl_price
        hit = w.low<=sl*(1+1e-9) if r.side=='long' else w.high>=sl*(1-1e-9)
    elif r.exit_reason=='tp_hit':
        tp = r.ie + 2.5*abs(r.ie-r.sl0)*(1 if r.side=='long' else -1) if r.kol!='mean_rev' else r.ie+1.667*abs(r.ie-r.sl0)*(1 if r.side=='long' else -1)
        hit = w.high>=tp*(1-1e-4) if r.side=='long' else w.low<=tp*(1+1e-4)
    else:
        lag.append((r.exit_reason, r.kol, (r.xt-r.et)/pd.Timedelta('1h'), r.mh)); continue
    if hit.any():
        t=hit.idxmax(); lag.append((r.exit_reason, r.kol, (r.xt-t)/pd.Timedelta('1h'), r.mh))
    else: lag.append((r.exit_reason,r.kol,np.nan,r.mh))
L=pd.DataFrame(lag,columns=['why','kol','lag','mh'])
print(L.groupby(['why','kol']).lag.describe())
print(L[L.why!='max_hold'].groupby('why').lag.value_counts().head(20))
print('sl_price == sl0 share', np.mean(np.isclose(d.sl_price,d.sl0)))
