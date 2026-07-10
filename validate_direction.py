"""
validate_direction.py — IFVG & Donchian LONG vs SHORT over FULL history.
12-month local data showed their shorts negative (IFVG -3.8R n24, Donchian
-5.4R n59) while longs are strong. Question: is that period noise, or should
these sleeves go LONG-ONLY? Needs full 2023-2026 data -> run on the VPS.

Usage (VPS): venv/bin/python validate_direction.py            # BTC
             venv/bin/python validate_direction.py BTCUSDT BNBUSDT
Decision bar: act (long-only) ONLY if full-history short side is negative
AND per-year shorts are negative in >=3 of 4 years. Otherwise keep both sides.
"""
import io, sys, zipfile
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from indicators import atr as atr_fn
from strategies.ifvg import IfvgStrategy
from strategies.donchian import DonchianStrategy

YEARS=[2023,2024,2025,2026]

def load_1h(sym):
    import requests, glob
    files=sorted(glob.glob(f"{sym}-1m-*.csv"))
    if files and len(files)>=24:
        fr=[]
        for f in files:
            d=pd.read_csv(f,header=None).iloc[:,:6]
            d.columns=["ts","open","high","low","close","volume"]
            d=d[pd.to_numeric(d["ts"],errors="coerce").notna()].astype(float); fr.append(d)
        df=pd.concat(fr).drop_duplicates("ts").sort_values("ts")
        unit="us" if df["ts"].iloc[0]>1e15 else "ms"
        df.index=pd.to_datetime(df["ts"],unit=unit,utc=True)
        return df.drop(columns=["ts"]).resample("1h").agg(
            {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    base="https://data.binance.vision/data/spot/monthly/klines"; fr=[]
    for y in YEARS:
        for mo in range(1,13):
            try:
                r=requests.get(f"{base}/{sym}/1h/{sym}-1h-{y}-{mo:02d}.zip",timeout=30)
                if r.status_code!=200: continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z, z.open(z.namelist()[0]) as fh:
                    d=pd.read_csv(fh,header=None,
                        names=["ts","open","high","low","close","volume","ct","qv","n","a","b","c"])
                d=d[pd.to_numeric(d["ts"],errors="coerce").notna()]; d["ts"]=pd.to_numeric(d["ts"])
                unit="us" if d["ts"].iloc[0]>1e15 else "ms"
                d.index=pd.to_datetime(d["ts"],unit=unit,utc=True)
                fr.append(d[["open","high","low","close","volume"]].astype(float))
            except Exception: continue
    return pd.concat(fr).sort_index() if fr else None

def sim(df,sigs,N):
    H=df["high"].values;L=df["low"].values;C=df["close"].values
    out=[]
    for (i,dr,e,sl,tp,mh) in sigs:
        xp=None
        for j in range(i+1,min(i+1+mh,N)):
            if dr==1:
                if L[j]<=sl: xp=sl;break
                if H[j]>=tp: xp=tp;break
            else:
                if H[j]>=sl: xp=sl;break
                if L[j]<=tp: xp=tp;break
        if xp is None: xp=C[min(i+mh,N-1)]
        R=abs(e-sl)
        if R>0: out.append((df.index[i],dr,dr*(xp-e)/R))
    return out

def rep(res,label):
    for dr,lab in ((1,"LONG"),(-1,"SHORT")):
        rows=[(t,r) for (t,d,r) in res if d==dr]
        if not rows: print(f"  {label:<9}{lab:<6}   0"); continue
        a=np.array([r for _,r in rows])
        yr={}
        for t,r in rows: yr.setdefault(t.year,[]).append(r)
        ys=" ".join(f"{y}:{np.sum(v):+.0f}R" for y,v in sorted(yr.items()))
        neg_years=sum(1 for v in yr.values() if np.sum(v)<0)
        print(f"  {label:<9}{lab:<6}n{len(a):>4} WR{100*(a>0).mean():>3.0f}% tot{a.sum():>+8.1f}R  yr[{ys}]  negYr:{neg_years}/{len(yr)}")

def main():
    coins=[c.upper() for c in sys.argv[1:]] or ["BTCUSDT"]
    for coin in coins:
        print(f"\n# {coin}")
        df=load_1h(coin)
        if df is None or len(df)<5000: print("  insufficient data"); continue
        n=len(df); a1=atr_fn(df["high"],df["low"],df["close"],14).values
        ifv=IfvgStrategy(min_gap_atr=0.75,rr=2.0); sig=[]
        for i in range(n):
            av=a1[i]
            if np.isnan(av) or av<=0: continue
            s=ifv.analyze(df.iloc[max(0,i-260+1):i+1],av)
            if s.direction!=0 and s.sl_price>0 and s.entry_price>0:
                sig.append((i,s.direction,s.entry_price,s.sl_price,s.tp_price,24))
        rep(sim(df,sig,n),"ifvg")
        d4=df.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
        a4=atr_fn(d4["high"],d4["low"],d4["close"],14).values
        don=DonchianStrategy(); dsig=[]
        for j in range(len(d4)):
            av=a4[j]
            if np.isnan(av) or av<=0: continue
            s=don.analyze(d4.iloc[max(0,j-260+1):j+1],float(av))
            if s.direction!=0: dsig.append((j,s.direction,s.entry_price,s.sl_price,s.tp_price,30))
        rep(sim(d4,dsig,len(d4)),"donchian")
    print("\nKARAR: SHORT tarafi tam-gecmiste negatif VE >=3/4 yilda negatifse -> long-only dusun.")
    print("Aksi halde iki yon de kalir (12-aylik zayiflik = donem gurultusu).")

if __name__=="__main__":
    main()
