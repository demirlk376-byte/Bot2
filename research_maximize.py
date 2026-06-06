"""
MAXIMIZE RETURNS — test the biggest legitimate return levers, train/test validated.

The volume filter got us from +13.5% to +20.8%. Now push further WITHOUT overfitting:

1. COST REDUCTION (limit/maker entries):
   - Current model: 0.04% per side = 0.08% round trip (market orders)
   - MEXC maker fee = 0.00% (limit orders). Limit entry + market exit = 0.04% round trip
   - Limit entry + limit exit = ~0.02% round trip
   This is REAL edge — not curve fitting. Lower cost = strictly more profit.

2. DEEPER LIMIT ENTRY (better price + quality filter):
   - Instead of entering at the close beyond the band, place a limit order
     deeper (e.g. close - 0.3xATR for longs). Fills only on further extension.
   - Better entry price AND filters weak signals that revert immediately.

3. RISK PER TRADE (the biggest return multiplier):
   - 2% is conservative. With PF 1.18 and 47% WR, higher risk compounds faster
     but increases drawdown. Show the full risk/return/DD curve.

4. COMPOUNDING vs FIXED — confirm we compound on growing balance.
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

BAL=10_000.0; MH=48; SL_M=3.0; TP_M=5.0

def precompute(df_1h):
    close=df_1h["close"]; high=df_1h["high"]; low=df_1h["low"]; vol=df_1h["volume"]
    upper,middle,lower=bollinger_bands(close,20,2.0)
    atr_s=atr(high,low,close,14)
    vol_ma=vol.rolling(20).mean()
    bb_pos=((close-lower)/(upper-lower).replace(0,np.nan)).values
    return dict(close=close.values,high=high.values,low=low.values,open=df_1h["open"].values,
                volume=vol.values,lower=lower.values,upper=upper.values,
                bb_pos=bb_pos,atr=atr_s.values,vol_ma=vol_ma.values,index=df_1h.index)

def run(pre, cost_side=0.0004, risk=0.02, limit_offset=0.0):
    """
    cost_side    : cost as fraction of notional, per side
    risk         : fraction of CURRENT balance risked per trade (compounding)
    limit_offset : place entry limit this many ATRs beyond the close (deeper).
                   0 = enter at close. 0.3 = wait for 0.3xATR more extension.
                   If next candle doesn't reach the limit, trade is skipped.
    """
    close=pre["close"]; high=pre["high"]; low=pre["low"]
    volume=pre["volume"]; bb_pos=pre["bb_pos"]; atr_v=pre["atr"]; vol_ma=pre["vol_ma"]
    n=len(close); warmup=60
    balance=BAL; open_t=None; trades=[]; pending=None

    for i in range(warmup,n):
        if np.isnan(atr_v[i]) or atr_v[i]<=0: continue

        # --- handle a pending limit order placed last candle ---
        if pending is not None and open_t is None:
            d=pending["dir"]; limit_px=pending["limit"]
            filled=False
            if d==1 and low[i]<=limit_px:
                filled=True
            elif d==-1 and high[i]>=limit_px:
                filled=True
            if filled:
                a=pending["atr"]; ep=limit_px
                sl_d=SL_M*a; tp_d=TP_M*a
                slp=ep-d*sl_d; tpp=ep+d*tp_d
                qty=round((balance*risk)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
                if qty>=0.001:
                    open_t={"i":i,"ts":pre["index"][i],"dir":d,"entry":ep,
                            "sl":slp,"tp":tpp,"qty":qty}
            pending=None
            # fall through to manage if just opened? No — opened this candle, manage next.
            if open_t is not None:
                continue

        # --- manage open trade ---
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
                gross=d*(ep-entry)*qty
                fees=(entry+ep)*qty*cost_side
                net=gross-fees
                balance+=net
                trades.append({"ts":pre["index"][i],"dir":d,"pnl":net,"reason":reason})
                open_t=None
            continue

        # --- look for new signal ---
        bpos=bb_pos[i]
        if np.isnan(bpos): continue
        lo=bpos<0; sh=bpos>1
        if not lo and not sh: continue
        direction=1 if lo else -1
        if not np.isnan(vol_ma[i]) and volume[i]<vol_ma[i]: continue

        a=atr_v[i]; cpx=close[i]
        if limit_offset>0:
            # place limit deeper; fills next candle if reached
            limit_px=cpx - direction*limit_offset*a
            pending={"dir":direction,"limit":limit_px,"atr":a,"i":i}
        else:
            # immediate entry at close (maker assumed via resting order at close)
            ep=cpx; sl_d=SL_M*a; tp_d=TP_M*a
            slp=ep-direction*sl_d; tpp=ep+direction*tp_d
            qty=round((balance*risk)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
            if qty<0.001: continue
            open_t={"i":i,"ts":pre["index"][i],"dir":direction,"entry":ep,
                    "sl":slp,"tp":tpp,"qty":qty}
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
    print(f"{label:<38s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+8.0f}  |  "
          f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+8.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    pre=precompute(df_1h)
    split=pd.Timestamp("2026-01-01")

    print("="*110)
    print("LEVER 1 — COST REDUCTION (limit/maker entries). risk=2%")
    print("="*110)
    for label,cost in [("Market both (0.08% RT) — current",0.0004),
                       ("Maker entry+market exit (0.06% RT)",0.0003),
                       ("Maker entry+market exit (0.04% RT)",0.0002),
                       ("Maker both (0.02% RT)",0.0001),
                       ("Maker both, rebate (0.00% RT)",0.0)]:
        trades=run(pre,cost_side=cost,risk=0.02,limit_offset=0.0)
        tr,te=sc(trades,split); pr(label,tr,te)

    print()
    print("="*110)
    print("LEVER 2 — DEEPER LIMIT ENTRY (wait for more extension; maker cost 0.04% RT)")
    print("="*110)
    for off in [0.0,0.1,0.2,0.3,0.4,0.5]:
        trades=run(pre,cost_side=0.0002,risk=0.02,limit_offset=off)
        tr,te=sc(trades,split); pr(f"limit_offset={off:.1f}xATR deeper",tr,te)

    print()
    print("="*110)
    print("LEVER 3 — RISK PER TRADE (compounding, maker cost 0.04% RT, no deeper limit)")
    print("="*110)
    for risk in [0.01,0.02,0.03,0.04,0.05,0.06,0.08,0.10]:
        trades=run(pre,cost_side=0.0002,risk=risk,limit_offset=0.0)
        tr,te=sc(trades,split); pr(f"risk={risk*100:.0f}% per trade",tr,te)

    print()
    print("="*110)
    print("COMBINED BEST CANDIDATES (maker 0.04% RT)")
    print("="*110)
    for label,risk,off in [
        ("risk3% + maker",0.03,0.0),
        ("risk4% + maker",0.04,0.0),
        ("risk5% + maker",0.05,0.0),
        ("risk4% + maker + limit0.2",0.04,0.2),
        ("risk5% + maker + limit0.2",0.05,0.2),
    ]:
        trades=run(pre,cost_side=0.0002,risk=risk,limit_offset=off)
        tr,te=sc(trades,split); pr(label,tr,te)

if __name__=="__main__":
    main()
