"""
Follow-up research: feature analysis showed ADX 35+ has 63% WR vs 43% for low ADX.
This is counter-intuitive but makes sense: high ADX + BB extreme = capitulation
at end of strong trend (not continuation). Test requiring MINIMUM ADX at entry.
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, rsi, atr, adx

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

COST = 0.0004; SL_M = 3.0; TP_M = 5.0; BAL = 10_000.0; RISK = 0.02; MH = 48

def run(pre, adx_min=0, vol_filter=True):
    close=pre["close"]; high=pre["high"]; low=pre["low"]; volume=pre["volume"]
    bb_pos=pre["bb_pos"]; atr_v=pre["atr"]; adx_v=pre["adx"]; vol_ma=pre["vol_ma"]
    n=len(close); warmup=60
    balance=BAL; open_t=None; trades=[]
    for i in range(warmup,n):
        if np.isnan(atr_v[i]) or atr_v[i]<=0: continue
        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]; sl=open_t["sl"]; tp=open_t["tp"]
            qty=open_t["qty"]; held=i-open_t["i"]
            ep=None; reason=None
            if d==1:
                if low[i]<=sl: ep,reason=sl,"sl"
                elif high[i]>=tp: ep,reason=tp,"tp"
            else:
                if high[i]>=sl: ep,reason=sl,"sl"
                elif low[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=MH: ep,reason=close[i],"mh"
            if ep is not None:
                balance += d*(ep-entry)*qty - (entry+ep)*qty*COST
                trades.append({"ts":pre["index"][i],"dir":d,"entry":entry,"exit":ep,
                               "pnl":d*(ep-entry)*qty-(entry+ep)*qty*COST,"reason":reason,"hold":held})
                open_t=None
            continue
        bpos=bb_pos[i]
        if np.isnan(bpos): continue
        long_ok=bpos<0; short_ok=bpos>1
        if not long_ok and not short_ok: continue
        direction=1 if long_ok else -1
        if vol_filter and not np.isnan(vol_ma[i]) and volume[i]<vol_ma[i]: continue
        if adx_min>0 and not np.isnan(adx_v[i]) and adx_v[i]<adx_min: continue
        a=atr_v[i]; ep=close[i]
        sl_d=SL_M*a; tp_d=TP_M*a
        slp=ep-direction*sl_d; tpp=ep+direction*tp_d
        qty=round((balance*RISK)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
        if qty<0.001: continue
        open_t={"i":i,"ts":pre["index"][i],"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}
    return trades

def score(trades, split=None):
    t = [x for x in trades if split is None or x["ts"]<split] if split else trades
    t2 = [x for x in trades if x["ts"]>=split] if split else []
    def s(tt):
        if not tt: return dict(n=0,wr=0,pnl=0,pf=0,dd=0)
        p=np.array([x["pnl"] for x in tt])
        pos=p[p>0].sum(); neg=-p[p<0].sum()
        pf=pos/neg if neg>0 else float("inf")
        eq=BAL+np.cumsum(p); peak=np.maximum.accumulate(eq)
        return dict(n=len(p),wr=(p>0).mean(),pnl=p.sum(),pf=pf,dd=((peak-eq)/peak).max())
    return s(t), s(t2)

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    close=df_1h["close"]; high=df_1h["high"]; low=df_1h["low"]; vol=df_1h["volume"]
    upper,middle,lower=bollinger_bands(close,20,2.0)
    rsi_s=rsi(close,14); atr_s=atr(high,low,close,14); adx_s=adx(high,low,close,14)
    vol_ma=vol.rolling(20).mean()
    bb_pos=(close-lower)/(upper-lower).replace(0,np.nan)
    pre=dict(close=close.values,high=high.values,low=low.values,volume=vol.values,
             upper=upper.values,lower=lower.values,middle=middle.values,
             bb_pos=bb_pos.values,rsi=rsi_s.values,atr=atr_s.values,
             adx=adx_s.values,vol_ma=vol_ma.values,index=df_1h.index)

    split=pd.Timestamp("2026-01-01")
    print("="*100)
    print("ADX MINIMUM FILTER TEST — vol filter already applied, requiring MIN ADX at entry")
    print("Hypothesis: high ADX + BB extreme = capitulation/exhaustion = stronger signal")
    print("="*100)
    print(f"{'Variant':<35s}  ALL  |  TRAIN WR PF $  |  TEST WR PF $  | maxDD")
    for amin in [0,20,22,25,27,30]:
        trades=run(pre,adx_min=amin,vol_filter=True)
        tr,te=score(trades,split)
        tot=tr["pnl"]+te["pnl"]
        print(f"ADX min={amin:>3d} (vol filter on)    {tr['n']+te['n']:>3d}t {tot/100:>+5.1f}%  |  "
              f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
              f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
              f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

    print()
    print("--- Monthly: ADX min=25 vs baseline+vol ---")
    base = run(pre, adx_min=0, vol_filter=True)
    best = run(pre, adx_min=25, vol_filter=True)
    def monthly(trades):
        m={}
        for t in trades: m.setdefault(t["ts"].strftime("%Y-%m"),[]).append(t["pnl"])
        return m
    mb=monthly(base); mw=monthly(best)
    print(f"{'Month':<10s}  {'Base n':>6s} {'Base $':>8s}  {'ADX25 n':>7s} {'ADX25 $':>8s}  {'Delta':>8s}")
    for month in sorted(set(list(mb)+list(mw))):
        bp=np.array(mb.get(month,[0])); wp=np.array(mw.get(month,[0]))
        print(f"  {month}   {len(bp):>5d}t {bp.sum():>+8.1f}    {len(wp):>6d}t {wp.sum():>+8.1f}   {wp.sum()-bp.sum():>+8.1f}")

if __name__=="__main__":
    main()
