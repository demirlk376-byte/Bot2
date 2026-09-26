import json, numpy as np, pandas as pd
ROOT='/home/user/Bot2'
d=pd.read_csv(f'{ROOT}/ikiz_k25_cap25_islemler.csv')
s=d.strategy_scores.apply(json.loads)
d['ie']=s.map(lambda z:z['intended_entry']); d['sl0']=s.map(lambda z:z['sl0'])
d['coin']=d.symbol.str.split('/').str[0]
d['et']=pd.to_datetime(d.entry_time,utc=True); d['xt']=pd.to_datetime(d.exit_time,utc=True)
d['Rn']=d.pnl_usdt/(d.quantity*(d.ie-d.sl0).abs())
d['Rn2']=d.pnl_usdt/(d.quantity*(d.entry_price-d.sl0).abs())
diff=(d.Rn-d.R)
print(diff.describe()); print('corr', np.corrcoef(d.Rn,d.R)[0,1], 'sum Rn', d.Rn.sum(), 'sum R', d.R.sum(), 'sum Rn2', d.Rn2.sum())
print(d.loc[diff.abs().nlargest(5).index,['symbol','side','entry_price','ie','sl0','exit_price','quantity','pnl_usdt','R','Rn','exit_reason','kol']])
# gross R check: sign*(exit-entry)*qty
gross=np.where(d.side=='long',1,-1)*(d.exit_price-d.entry_price)*d.quantity
print('pnl - gross (costs+funding) median', (d.pnl_usdt-gross).median(), 'sum', (d.pnl_usdt-gross).sum())
bars={}
for c in d.coin.unique():
    x=pd.read_csv(f'{ROOT}/data/{c}_fut_1h.csv'); x['ts']=pd.to_datetime(x.ts,utc=True); bars[c]=x.set_index('ts')
mh=d[d.exit_reason=='max_hold']
out=[]
for _,r in mh.iterrows():
    b=bars[r.coin]
    out.append({k:(r.exit_price/b[col].get(r.xt+pd.Timedelta(f'{o}h'),np.nan)-1)*1e4 for k,(col,o) in
      {'close_xt-2':('close',-2),'close_xt-1':('close',-1),'open_xt-1':('open',-1),'open_xt':('open',0),'close_xt':('close',0)}.items()})
print('max_hold exit_price vs bars (median bp):'); print(pd.DataFrame(out).abs().median())
