"""
Test TP multiplier: higher WR comes from tighter TP (smaller target), but at the
cost of lower per-trade profit. Find the sweet spot.
Current: SL=3xATR, TP=5xATR → WR≈47%, PF≈1.18

This also tests SL multiplier: tighter SL = more frequent hits but smaller loss.
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

COST=0.0004; BAL=10_000.0; RISK=0.02; MH=48

def run(df_1h, sl_m=3.0, tp_m=5.0, vol_filter=True):
    close=df_1h["close"]; high=df_1h["high"]; low=df_1h["low"]; vol=df_1h["volume"]
    upper,middle,lower=bollinger_bands(close,20,2.0)
    atr_s=atr(high,low,close,14)
    vol_ma=vol.rolling(20).mean()
    bb_pos=((close-lower)/(upper-lower).replace(0,np.nan)).values
    c_v=close.values; h_v=high.values; l_v=low.values
    vol_v=vol.values; vol_ma_v=vol_ma.values; atr_v=atr_s.values
    n=len(c_v); warmup=60
    balance=BAL; open_t=None; trades=[]
    for i in range(warmup,n):
        if np.isnan(atr_v[i]) or atr_v[i]<=0: continue
        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]; sl=open_t["sl"]; tp=open_t["tp"]
            qty=open_t["qty"]; held=i-open_t["i"]
            ep=None; reason=None
            if d==1:
                if l_v[i]<=sl: ep,reason=sl,"sl"
                elif h_v[i]>=tp: ep,reason=tp,"tp"
            else:
                if h_v[i]>=sl: ep,reason=sl,"sl"
                elif l_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=MH: ep,reason=c_v[i],"mh"
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
        a=atr_v[i]; ep=c_v[i]
        sl_d=sl_m*a; tp_d=tp_m*a
        slp=ep-direction*sl_d; tpp=ep+direction*tp_d
        rr=tp_d/sl_d
        if rr<1.0: continue  # skip if R:R < 1.0
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
    print(f"{label:<35s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    split=pd.Timestamp("2026-01-01")
    print("="*105)
    print("TP/SL MULTIPLIER TEST (volume filter ON, BB std=2.0)")
    print("="*105)
    print(f"{'SL×TP config':<35s}  ALL  |  TRAIN WR PF $  |  TEST WR PF $  | maxDD")
    # Test different TP with fixed SL=3.0
    print("\n--- Varying TP with SL=3.0 ---")
    for tp_m in [2.0,2.5,3.0,3.5,4.0,4.5,5.0,6.0]:
        rr=tp_m/3.0
        trades=run(df_1h,sl_m=3.0,tp_m=tp_m)
        tr,te=sc(trades,split)
        pr(f"SL=3.0 TP={tp_m:.1f} (R:R={rr:.2f})",tr,te)

    # Test different SL with fixed TP ratio
    print("\n--- Varying SL (TP = 5/3 × SL to maintain R:R 1.67) ---")
    for sl_m in [1.5,2.0,2.5,3.0,3.5,4.0]:
        tp_m=sl_m*(5.0/3.0)
        trades=run(df_1h,sl_m=sl_m,tp_m=tp_m)
        tr,te=sc(trades,split)
        pr(f"SL={sl_m:.1f} TP={tp_m:.1f} (R:R=1.67)",tr,te)

    print("\n--- Best alternatives (top 5 by test PF, min 25 test trades) ---")
    results=[]
    for sl_m in [1.5,2.0,2.5,3.0,3.5,4.0]:
        for tp_m in [2.0,2.5,3.0,3.5,4.0,4.5,5.0,5.5,6.0]:
            if tp_m <= sl_m: continue
            trades=run(df_1h,sl_m=sl_m,tp_m=tp_m)
            tr,te=sc(trades,split)
            if te["n"]>=25:
                results.append((sl_m,tp_m,tr,te))
    results.sort(key=lambda x: x[3]["pf"],reverse=True)
    for sl_m,tp_m,tr,te in results[:5]:
        pr(f"SL={sl_m:.1f} TP={tp_m:.1f} (R:R={(tp_m/sl_m):.2f})",tr,te)

if __name__=="__main__":
    main()
