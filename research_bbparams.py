"""
Test BB parameters: wider bands → fewer trades, higher quality extremes → higher WR?
Also test combined: different std + vol filter.
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

def load_all():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts","open","high","low","close","volume","ct","qv","count","tbv","tbqv","ign"]
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])

def resample(df, rule):
    return df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

COST=0.0004; SL_M=3.0; TP_M=5.0; BAL=10_000.0; RISK=0.02; MH=48

def run(df_1h, bb_std=2.0, bb_period=20, vol_filter=True):
    close=df_1h["close"]; high=df_1h["high"]; low=df_1h["low"]; vol=df_1h["volume"]
    upper,middle,lower=bollinger_bands(close,bb_period,bb_std)
    atr_s=atr(high,low,close,14)
    vol_ma=vol.rolling(20).mean()
    bb_pos=((close-lower)/(upper-lower).replace(0,np.nan)).values

    close_v=close.values; high_v=high.values; low_v=low.values
    vol_v=vol.values; vol_ma_v=vol_ma.values; atr_v=atr_s.values
    n=len(close_v); warmup=60

    balance=BAL; open_t=None; trades=[]
    for i in range(warmup,n):
        if np.isnan(atr_v[i]) or atr_v[i]<=0: continue
        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]; sl=open_t["sl"]; tp=open_t["tp"]
            qty=open_t["qty"]; held=i-open_t["i"]
            ep=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep,reason=sl,"sl"
                elif high_v[i]>=tp: ep,reason=tp,"tp"
            else:
                if high_v[i]>=sl: ep,reason=sl,"sl"
                elif low_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=MH: ep,reason=close_v[i],"mh"
            if ep is not None:
                balance+=d*(ep-entry)*qty-(entry+ep)*qty*COST
                trades.append({"ts":df_1h.index[i],"pnl":d*(ep-entry)*qty-(entry+ep)*qty*COST,"reason":reason})
                open_t=None
            continue
        bpos=bb_pos[i]
        if np.isnan(bpos): continue
        lo=bpos<0; sh=bpos>1
        if not lo and not sh: continue
        direction=1 if lo else -1
        if vol_filter and not np.isnan(vol_ma_v[i]) and vol_v[i]<vol_ma_v[i]: continue
        a=atr_v[i]; ep=close_v[i]
        sl_d=SL_M*a; tp_d=TP_M*a
        slp=ep-direction*sl_d; tpp=ep+direction*tp_d
        qty=round((balance*RISK)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
        if qty<0.001: continue
        open_t={"i":i,"ts":df_1h.index[i],"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}
    return trades

def sc(trades,split):
    tr=[t for t in trades if t["ts"]<split]
    te=[t for t in trades if t["ts"]>=split]
    def s(tt):
        if not tt: return dict(n=0,wr=0,pnl=0,pf=0,dd=0)
        p=np.array([t["pnl"] for t in tt])
        pos=p[p>0].sum(); neg=-p[p<0].sum()
        pf=pos/neg if neg>0 else float("inf")
        eq=BAL+np.cumsum(p); peak=np.maximum.accumulate(eq)
        return dict(n=len(p),wr=(p>0).mean(),pnl=p.sum(),pf=pf,dd=((peak-eq)/peak).max())
    return s(tr), s(te)

def pr(label,tr,te):
    tot=tr["pnl"]+te["pnl"]
    print(f"{label:<45s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    split=pd.Timestamp("2026-01-01")
    print("="*112)
    print("BB PARAMETER TEST — period=20, varying std (with & without volume filter)")
    print("="*112)
    for std in [1.8,2.0,2.2,2.5,2.8,3.0]:
        for vf in [False,True]:
            label=f"BB std={std:.1f}  vol={'ON' if vf else 'OFF'}"
            trades=run(df_1h,bb_std=std,vol_filter=vf)
            tr,te=sc(trades,split)
            pr(label,tr,te)
        print()

    print()
    print("--- Best out-of-sample combinations ---")
    # Focus on test PF
    best = []
    for std in [1.8,2.0,2.2,2.5,2.8,3.0]:
        for vf in [False,True]:
            trades=run(df_1h,bb_std=std,vol_filter=vf)
            tr,te=sc(trades,split)
            if te["n"] >= 20:  # enough test trades
                best.append((std,vf,tr,te))
    best.sort(key=lambda x: x[3]["pf"], reverse=True)
    print(f"\nTop 5 by TEST profit factor (min 20 test trades):")
    for std,vf,tr,te in best[:5]:
        label=f"BB std={std:.1f} vol={'ON' if vf else 'OFF'}"
        pr(label,tr,te)

if __name__=="__main__":
    main()
