"""
research_trailing_intraday.py — ORB & Asia BO için çıkış stratejisi taraması

Mevcut: sabit 2:1 TP, 6h max hold. Soru: kazananları koşturmak (trailing
stop) PF'yi artırır mı? Her sleeve izole, 3 dönemde (2023/2024/2025-26).

Çıkış modları (R = giriş risk mesafesi = |entry - SL|):
  fixed2     : sabit TP = 2R (MEVCUT)
  fixed3     : sabit TP = 3R
  be_trail1  : 1R kârda SL→entry, sonra peak−1×ATR trailing (TP yok)
  be_trail2  : 1R kârda SL→entry, sonra peak−2×ATR trailing (TP yok)
  be_trailR  : 1R kârda SL→entry, sonra peak−1R trailing (TP yok)

Bar-içi pesimistik: önce mevcut SL kontrol, sonra trailing güncelle (look-ahead yok).
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import atr

COST_TAKER=0.0001; LEVERAGE=10; MIN_LOT=0.001; START=200.0
ORB_RISK=0.05; ORB_HOUR=14; ORB_MH=6
ASIA_RISK=0.03; ASIA_SL=1.0; ASIA_MH=6


def load_period(yms):
    frames=[]
    for ym in yms:
        for f in sorted(glob.glob(f"/home/user/Bot2/BTCUSDT-1m-{ym}.csv")):
            df=pd.read_csv(f)
            df.columns=["ts","open","high","low","close","volume","ct","qv","count","tbv","tbqv","ign"]
            frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    if not frames: return pd.DataFrame()
    full=pd.concat(frames,ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index=pd.to_datetime(full["ts"],unit="ms",utc=True)
    return full.drop(columns=["ts"])


def resample_1h(df):
    return df.resample("1h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()


def size_qty(risk_pct,balance,ep,sl_dist):
    if sl_dist<=0: return 0.0
    qty=(balance*risk_pct)/sl_dist
    qty=min(qty,balance*LEVERAGE/ep); qty=round(qty,3)
    return qty if qty>=MIN_LOT else 0.0


def simulate_exit(entry, direction, sl, R, atr_val, mode,
                  bars_high, bars_low, bars_close, max_hold):
    """Bar bar çıkış simülasyonu. Döner: (exit_price, reason, bars_held)."""
    peak = entry
    cur_sl = sl
    tp = None
    if mode == "fixed2": tp = entry + direction * 2*R
    elif mode == "fixed3": tp = entry + direction * 3*R
    trail_after = entry + direction * R   # 1R kâr eşiği
    be_done = False
    trail_dist = {"be_trail1":1*atr_val, "be_trail2":2*atr_val, "be_trailR":R}.get(mode)

    for k in range(len(bars_high)):
        h=bars_high[k]; l=bars_low[k]
        # 1) Önce mevcut SL kontrol (pesimistik)
        if direction==1:
            if l<=cur_sl: return cur_sl, ("sl" if cur_sl<=entry else "trail"), k+1
            if tp is not None and h>=tp: return tp, "tp", k+1
        else:
            if h>=cur_sl: return cur_sl, ("sl" if cur_sl>=entry else "trail"), k+1
            if tp is not None and l<=tp: return tp, "tp", k+1
        # 2) Trailing güncelle (sadece be_* modlar)
        if trail_dist is not None:
            if direction==1:
                peak=max(peak,h)
                if not be_done and h>=trail_after:
                    cur_sl=max(cur_sl, entry); be_done=True
                if be_done:
                    cur_sl=max(cur_sl, peak-trail_dist)
            else:
                peak=min(peak,l)
                if not be_done and l<=trail_after:
                    cur_sl=min(cur_sl, entry); be_done=True
                if be_done:
                    cur_sl=min(cur_sl, peak+trail_dist)
        if k+1>=max_hold:
            return bars_close[k], "mh", k+1
    return bars_close[-1], "mh", len(bars_high)


def run_intraday(df_1m, strat, mode):
    df=resample_1h(df_1m)
    if len(df)<100: return []
    high_v=df["high"].values; low_v=df["low"].values; close=df["close"].values
    idx=df.index
    atr_a=atr(df["high"],df["low"],df["close"],14).values
    n=len(close); warmup=60
    dates_a=np.array([ts.date() for ts in idx])
    hours_a=np.array([ts.hour for ts in idx])

    orb_by_date={}; asia_by_date={}
    for j in range(n):
        d=dates_a[j]; h=hours_a[j]
        if h==ORB_HOUR: orb_by_date[d]={"high":high_v[j],"low":low_v[j]}
        if h<8:
            if d not in asia_by_date: asia_by_date[d]={"high":high_v[j],"low":low_v[j],"cnt":1}
            else:
                asia_by_date[d]["high"]=max(asia_by_date[d]["high"],high_v[j])
                asia_by_date[d]["low"]=min(asia_by_date[d]["low"],low_v[j])
                asia_by_date[d]["cnt"]+=1

    balance=START; traded=set(); trades=[]
    mh = ORB_MH if strat=="orb" else ASIA_MH

    for i in range(warmup,n):
        a_val=atr_a[i]
        if np.isnan(a_val) or a_val<=0: continue
        cd=dates_a[i]; ch=hours_a[i]
        if cd in traded: continue

        entry=direction=sl=R=None
        if strat=="orb" and ch>ORB_HOUR:
            orb=orb_by_date.get(cd)
            if orb:
                oh=orb["high"]; ol=orb["low"]; rng=oh-ol
                if rng>0:
                    cp=close[i]
                    if cp>oh: entry,direction,sl,R = oh,1,ol,rng
                    elif cp<ol: entry,direction,sl,R = ol,-1,oh,rng
        elif strat=="asia" and ch>=8:
            asia=asia_by_date.get(cd)
            if asia and asia["cnt"]>=4:
                ah=asia["high"]; al=asia["low"]; sl_dist=ASIA_SL*a_val; cp=close[i]
                if cp>ah: entry,direction,sl,R = ah,1,ah-sl_dist,sl_dist
                elif cp<al: entry,direction,sl,R = al,-1,al+sl_dist,sl_dist

        if entry is None: continue
        qty=size_qty(ORB_RISK if strat=="orb" else ASIA_RISK, balance, entry, abs(entry-sl))
        if qty<=0: continue

        # sonraki barlar (max_hold kadar)
        end=min(i+mh, n)
        bh=high_v[i:end]; bl=low_v[i:end]; bc=close[i:end]
        ep_exit,reason,held=simulate_exit(entry,direction,sl,R,a_val,mode,bh,bl,bc,mh)
        pnl = direction*(ep_exit-entry)*qty - ep_exit*qty*COST_TAKER
        balance+=pnl
        traded.add(cd)
        trades.append({"pnl":pnl,"reason":reason})
    return trades


def stats(trades):
    if not trades: return {"n":0,"wr":0,"pf":0,"net":0}
    p=[t["pnl"] for t in trades]
    pos=sum(x for x in p if x>0); neg=sum(-x for x in p if x<0)
    return {"n":len(p),"wr":sum(1 for x in p if x>0)/len(p),"pf":pos/neg if neg>0 else 999,"net":sum(p)}


def main():
    print("Veri yükleniyor…",flush=True)
    periods=[
        ("2023",   load_period([f"2023-{m:02d}" for m in range(1,13)])),
        ("2024",   load_period([f"2024-{m:02d}" for m in range(1,13)])),
        ("2025-26",load_period([f"2025-{m:02d}" for m in range(5,13)]+[f"2026-{m:02d}" for m in range(1,5)])),
    ]
    modes=["fixed2","fixed3","be_trail1","be_trail2","be_trailR"]

    for strat in ("orb","asia"):
        print("\n"+"="*84)
        print(f"  {strat.upper()} — ÇIKIŞ MODU TARAMASI (PF / net$, 3 dönem)  [fixed2 = MEVCUT]")
        print("="*84)
        print(f"  {'Mod':<12s}"+"".join(f"  {pn+' PF':>9s} {'net$':>9s}" for pn,_ in periods)+f"  {'ORT PF':>7s}")
        print("  "+"-"*82)
        for mode in modes:
            row=f"  {mode:<12s}"; pfs=[]
            for pn,dfp in periods:
                s=stats(run_intraday(dfp,strat,mode))
                pfs.append(s["pf"] if s["n"]>0 else 0)
                flag="✓" if s["pf"]>=1.0 else " "
                row+=f"  {s['pf']:>7.2f}{flag} {s['net']:>+9.0f}"
            row+=f"  {sum(pfs)/len(pfs):>7.2f}"
            tag=" ← MEVCUT" if mode=="fixed2" else ""
            print(row+tag,flush=True)
    print("\n  Not: net$ izole sleeve (compound yok), sadece mod karşılaştırması için.")


if __name__=="__main__":
    main()
