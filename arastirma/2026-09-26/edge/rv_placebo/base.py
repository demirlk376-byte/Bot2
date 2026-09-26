import json, numpy as np, pandas as pd
DATA="/home/user/Bot2/data"
def trades(path="/home/user/Bot2/ikiz_k25_cap25_islemler.csv"):
    t=pd.read_csv(path)
    j=t.strategy_scores.map(json.loads)
    t["sleeve"]=j.map(lambda x:x["strategy"]); t["ie"]=j.map(lambda x:x["intended_entry"]); t["sl0"]=j.map(lambda x:x["sl0"])
    t["mh"]=j.map(lambda x:x.get("max_hold")); t["feein"]=j.map(lambda x:x.get("entry_fee_rate"))
    t["coin"]=t.symbol.str.split("/").str[0]; t["s"]=np.where(t.side=="long",1.0,-1.0)
    t["Dp"]=(t.ie-t.sl0).abs(); t["sp"]=t.Dp/t.ie
    t["Rn"]=t.pnl_usdt/(t.quantity*t.Dp)
    t["tin"]=pd.to_datetime(t.entry_time,utc=True,format="ISO8601"); t["tout"]=pd.to_datetime(t.exit_time,utc=True,format="ISO8601")
    t["tr"]=t.tout<pd.Timestamp("2025-01-01",tz="UTC")
    return t
_B={}
def bars(c):
    if c not in _B:
        b=pd.read_csv(f"{DATA}/{c}_fut_1h.csv"); b["ts"]=pd.to_datetime(b.ts,utc=True)
        b=b.set_index("ts").sort_index()
        assert b.index.is_unique
        _B[c]=b
    return _B[c]
