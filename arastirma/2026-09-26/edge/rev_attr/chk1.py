import pandas as pd, numpy as np, json
d=pd.read_csv("/home/user/Bot2/ikiz_k25_cap25_islemler.csv")
s=d.strategy_scores.apply(json.loads)
d['ie']=s.apply(lambda x:x['intended_entry']); d['sl0']=s.apply(lambda x:x['sl0'])
d['Rn']=d.pnl_usdt/(d.quantity*(d.ie-d.sl0).abs())
d['R2']=d.pnl_usdt/(d.quantity*(d.entry_price-d.sl0).abs())
sg=np.where(d.side=='long',1,-1)
d['Rpx']=sg*(d.exit_price-d.entry_price)/(d.ie-d.sl0).abs()
for c in ['Rn','R2','Rpx']: print(c, (d.R-d[c]).abs().describe()[['mean','50%','max']].round(4).to_dict())
d['diff']=d.R-d.Rn
print(d.sort_values('diff',key=abs).tail(5)[['kol','exit_reason','R','Rn','R2','Rpx','pnl_usdt']])
print(d.groupby('kol')[['R','Rn','R2','Rpx']].mean())
