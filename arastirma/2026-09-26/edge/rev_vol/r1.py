import pandas as pd, numpy as np, json
from scipy import stats
B='/home/user/Bot2/'
OUT='/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/edge/rev_vol/'
def load(f):
    d=pd.read_csv(B+f)
    s=d.strategy_scores.apply(json.loads)
    d['ie']=s.apply(lambda x:x['intended_entry']); d['sl0']=s.apply(lambda x:x['sl0'])
    d['et']=pd.to_datetime(d.entry_time,utc=True); d['xt']=pd.to_datetime(d.exit_time,utc=True)
    d['risk_px']=(d.ie-d.sl0).abs()
    d['Rn']=d.pnl_usdt/(d.quantity*d.risk_px)
    sgn=np.where(d.side=='long',1,-1)
    d['gross']=sgn*(d.exit_price-d.entry_price)/d.risk_px  # price move from fill
    d['slipR']=sgn*(d.entry_price-d.ie)/d.risk_px
    d['stop_pct']=d.risk_px/d.ie
    d['coin']=d.symbol.str.split('/').str[0]
    d['half']=np.where(d.xt<pd.Timestamp('2025-01-01',tz='UTC'),'TRAIN','TEST')
    return d
new=load('ikiz_k25_cap25_islemler.csv'); old=load('ikiz_k25_eski_islemler.csv')
print('R col vs Rn max diff new', (new.R-new.Rn).abs().max(), 'old', (old.R-old.Rn).abs().max())
# volume ratio
vr={}
for c in ['SOL','ETH','ADA','NEAR','BCH','ICP','BNB']:
    h=pd.read_csv(B+f'data/{c}_fut_1h.csv'); h['ts']=pd.to_datetime(h.ts,utc=True); h=h.set_index('ts').sort_index()
    # check completeness
    full=pd.date_range(h.index[0],h.index[-1],freq='1h')
    miss=len(full)-len(h.index.unique())
    v4=h.volume.resample('4h').agg(['sum','count'])
    v4['ratio']=v4['sum']/v4['sum'].shift(1).rolling(20).mean()
    v4['close_t']=v4.index+pd.Timedelta(hours=4)
    vr[c]=(v4.set_index('close_t'),miss)
    print(c,'missing 1h bars',miss,'4h bars with count<4',(v4['count']<4).sum())
def addvr(d):
    d=d.copy(); r=[];cnt=[]
    for _,x in d.iterrows():
        t=vr[x.coin][0]
        if x.et in t.index: r.append(t.loc[x.et,'ratio']); cnt.append(t.loc[x.et,'count'])
        else: r.append(np.nan); cnt.append(np.nan)
    d['vr']=r; d['cnt']=cnt; return d
nd=addvr(new[new.kol=='donchian']); od=addvr(old[old.kol=='donchian'])
print('new donchian',len(nd),'min vr',nd.vr.min(),'n<2.5',(nd.vr<2.5).sum(),'nan',nd.vr.isna().sum())
print('old donchian',len(od),'n vr<2.5',(od.vr<2.5).sum(),'nan',od.vr.isna().sum(), 'cnt<4 old', (od.cnt<4).sum())
key=['symbol','side','entry_time']
m=od.merge(nd[key+['Rn']],on=key,how='left',suffixes=('','_new'),indicator=True)
od['in_new']=(m['_merge']=='both').values
print('matched R maxdiff', (m.Rn-m.Rn_new).abs().max())
m2=nd.merge(od[key],on=key,how='left',indicator=True); nd['in_old']=(m2['_merge']=='both').values
print('both',od.in_new.sum(),'old only',(~od.in_new).sum(),'new only',(~nd.in_old).sum())
od['grp']=np.where(od.vr<2.5,'removed',np.where(od.in_new,'kept','displaced'))
print(od.groupby(['half','grp']).size().unstack())
print('new-only by half', nd[~nd.in_old].half.value_counts().to_dict())
# old-only with vr>=2.5 : any exit-time overlaps? 
od.to_pickle(OUT+'od.pkl'); nd.to_pickle(OUT+'nd.pkl'); new.to_pickle(OUT+'new.pkl'); old.to_pickle(OUT+'old.pkl')
