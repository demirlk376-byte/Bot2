"""
research_bb_weekend_impact.py — BB_WEEKDAY_ENABLED'in portföye etkisi

Tam 3-sleeve portföyü (BB + ORB + Asia BO) iki şekilde çalıştırır:
  A) MEVCUT      : BB her gün açık
  B) HAFTA SONU  : BB sadece Cmt-Paz (BB_WEEKDAY_ENABLED=false)

Her dönem için son bakiye, net kâr, max DD ve aylık ortalama karşılaştırılır.
Diğer her şey research_2year.py ile birebir aynı.
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as _adx_ind

COST_MAKER=0.0; COST_TAKER=0.0001; LEVERAGE=10; MIN_LOT=0.001
START=200.0; MONTHLY_ADD=100.0
BB_RISK=0.08; BB_SL=3.0; BB_TP=5.0; BB_MH=48
ORB_RISK=0.05; ORB_RR=2.0; ORB_MH=6; ORB_HOUR=14
ASIA_RISK=0.03; ASIA_RR=2.0; ASIA_SL=1.0; ASIA_MH=6
ADX_TRENDING=28.0; DAILY_MAX_LOSS=0.35; CONSEC_LIMIT=2; COOLDOWN_HOURS=4


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


def size_qty(risk_pct,balance,free_margin,ep,sl_dist):
    if sl_dist<=0 or free_margin<=0: return 0.0,0.0
    qty=(balance*risk_pct)/sl_dist
    qty=min(qty,free_margin*LEVERAGE/ep); qty=round(qty,3)
    if qty<MIN_LOT: return 0.0,0.0
    margin=qty*ep/LEVERAGE
    if margin>free_margin+1e-9: return 0.0,0.0
    return qty,margin


def run_sim(df_1m, bb_weekend_only=False, monthly_add=MONTHLY_ADD):
    df=resample_1h(df_1m)
    if len(df)<100: return [], {}
    close=df["close"].values; high_v=df["high"].values; low_v=df["low"].values
    vol=df["volume"].values; idx=df.index
    upper_s,_,lower_s=bollinger_bands(df["close"],20,2.0)
    atr_s=atr(df["high"],df["low"],df["close"],14)
    adx_s=_adx_ind(df["high"],df["low"],df["close"],14)
    vol_ma=df["volume"].rolling(20).mean()
    bb_pos=((df["close"]-lower_s)/(upper_s-lower_s).replace(0,np.nan))
    atr_a=atr_s.values; adx_a=adx_s.values; volma_a=vol_ma.values; bb_a=bb_pos.values
    n=len(close); warmup=60
    dates_a=np.array([ts.date() for ts in idx])
    hours_a=np.array([ts.hour for ts in idx])
    wday_a=np.array([ts.weekday() for ts in idx])
    month_a=np.array([ts.to_period("M") for ts in idx])

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

    balance=START; used_margin=0.0; daily_start=START; daily_date=None
    bb_o=orb_o=asia_o=None; orb_traded=set(); asia_traded=set()
    consec={"bb":0,"orb":0,"asia":0}; cooldown={"bb":None,"orb":None,"asia":None}
    trades=[]; monthly_pnl={}
    def free(): return balance-used_margin

    for i in range(warmup,n):
        a_val=atr_a[i]
        if np.isnan(a_val) or a_val<=0: continue
        cd=dates_a[i]; ch=hours_a[i]; cm=month_a[i]; now_ts=idx[i]
        if cd!=daily_date:
            daily_date=cd; daily_start=balance+used_margin
            if monthly_add>0 and ch==0 and cd.day==1: balance+=monthly_add

        for slot,pos in [("bb",bb_o),("orb",orb_o),("asia",asia_o)]:
            if pos is None: continue
            d=pos["dir"]; entry=pos["entry"]; sl=pos["sl"]; tp=pos["tp"]
            qty=pos["qty"]; mh=pos["mh"]; held=i-pos["i"]
            ep_exit=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep_exit,reason=sl,"sl"
                elif high_v[i]>=tp: ep_exit,reason=tp,"tp"
            else:
                if high_v[i]>=sl: ep_exit,reason=sl,"sl"
                elif low_v[i]<=tp: ep_exit,reason=tp,"tp"
            if ep_exit is None and held>=mh: ep_exit,reason=close[i],"mh"
            if ep_exit is not None:
                raw=d*(ep_exit-entry)*qty
                fee=entry*qty*COST_MAKER+ep_exit*qty*COST_TAKER
                pnl=raw-fee; balance+=pnl; used_margin-=pos["margin"]
                trades.append({"pnl":pnl,"strat":slot,"month":cm,"reason":reason})
                monthly_pnl.setdefault(cm,0.0); monthly_pnl[cm]+=pnl
                if pnl<0:
                    consec[slot]+=1
                    if consec[slot]>=CONSEC_LIMIT: cooldown[slot]=now_ts+pd.Timedelta(hours=COOLDOWN_HOURS)
                else: consec[slot]=0
                if slot=="bb": bb_o=None
                elif slot=="orb": orb_o=None
                else: asia_o=None

        equity=balance+used_margin
        if daily_start>0 and (daily_start-equity)/daily_start>=DAILY_MAX_LOSS: continue
        adx_val=adx_a[i]; trending=not np.isnan(adx_val) and adx_val>=ADX_TRENDING
        is_weekend=wday_a[i]>=5

        # BB
        bb_day_ok = (not bb_weekend_only) or is_weekend
        if bb_o is None and bb_day_ok:
            if (not trending and cooldown["bb"] is None) or (cooldown["bb"] is not None and now_ts>=cooldown["bb"]):
                if cooldown["bb"] is not None and now_ts>=cooldown["bb"]: cooldown["bb"]=None
                bpos=bb_a[i]; vm=volma_a[i]
                if not np.isnan(bpos) and (bpos<0.0 or bpos>1.0) and not trending:
                    if np.isnan(vm) or vol[i]>=vm:
                        direction=1 if bpos<0.0 else -1; ep=close[i]; sl_dist=BB_SL*a_val
                        qty,mg=size_qty(BB_RISK,balance,free(),ep,sl_dist)
                        if qty>0:
                            used_margin+=mg
                            bb_o={"i":i,"dir":direction,"entry":ep,"sl":ep-direction*sl_dist,
                                  "tp":ep+direction*BB_TP*a_val,"qty":qty,"margin":mg,"mh":BB_MH}

        # ORB
        if orb_o is None and cd not in orb_traded and ch>ORB_HOUR:
            if cooldown["orb"] is None or now_ts>=cooldown["orb"]:
                if cooldown["orb"] is not None and now_ts>=cooldown["orb"]: cooldown["orb"]=None
                orb=orb_by_date.get(cd)
                if orb:
                    oh=orb["high"]; ol=orb["low"]; rng=oh-ol
                    if rng>0:
                        cp=close[i]
                        if cp>oh:
                            ep=oh; sl=ol; tp=oh+ORB_RR*rng
                            qty,mg=size_qty(ORB_RISK,balance,free(),ep,rng)
                            if qty>0:
                                used_margin+=mg; orb_traded.add(cd)
                                orb_o={"i":i,"dir":1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ORB_MH}
                        elif cp<ol:
                            ep=ol; sl=oh; tp=ol-ORB_RR*rng
                            qty,mg=size_qty(ORB_RISK,balance,free(),ep,rng)
                            if qty>0:
                                used_margin+=mg; orb_traded.add(cd)
                                orb_o={"i":i,"dir":-1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ORB_MH}

        # Asia BO
        if asia_o is None and cd not in asia_traded and ch>=8:
            if cooldown["asia"] is None or now_ts>=cooldown["asia"]:
                if cooldown["asia"] is not None and now_ts>=cooldown["asia"]: cooldown["asia"]=None
                asia=asia_by_date.get(cd)
                if asia and asia["cnt"]>=4:
                    ah=asia["high"]; al=asia["low"]; sl_dist=ASIA_SL*a_val; cp=close[i]
                    if cp>ah:
                        ep=ah; sl=ah-sl_dist; tp=ah+ASIA_RR*sl_dist
                        qty,mg=size_qty(ASIA_RISK,balance,free(),ep,sl_dist)
                        if qty>0:
                            used_margin+=mg; asia_traded.add(cd)
                            asia_o={"i":i,"dir":1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ASIA_MH}
                    elif cp<al:
                        ep=al; sl=al+sl_dist; tp=al-ASIA_RR*sl_dist
                        qty,mg=size_qty(ASIA_RISK,balance,free(),ep,sl_dist)
                        if qty>0:
                            used_margin+=mg; asia_traded.add(cd)
                            asia_o={"i":i,"dir":-1,"entry":ep,"sl":sl,"tp":tp,"qty":qty,"margin":mg,"mh":ASIA_MH}

    return trades, monthly_pnl


def stats(trades):
    if not trades: return {"n":0,"wr":0,"pf":0,"net":0}
    p=[t["pnl"] for t in trades]
    pos=sum(x for x in p if x>0); neg=sum(-x for x in p if x<0)
    return {"n":len(p),"wr":sum(1 for x in p if x>0)/len(p),"pf":pos/neg if neg>0 else 999,"net":sum(p)}


def equity_curve(trades,start=START,monthly_add=MONTHLY_ADD):
    bal=start; peak=start; max_dd=0.0; cm=None
    for t in trades:
        m=t["month"]
        if monthly_add>0 and cm is not None and m!=cm: bal+=monthly_add
        cm=m; bal+=t["pnl"]
        if bal>peak: peak=bal
        dd=(peak-bal)/peak if peak>0 else 0.0
        if dd>max_dd: max_dd=dd
    return bal,max_dd


def main():
    print("Veri yükleniyor…",flush=True)
    periods=[
        ("2023",   load_period([f"2023-{m:02d}" for m in range(1,13)])),
        ("2024",   load_period([f"2024-{m:02d}" for m in range(1,13)])),
        ("2025-26",load_period([f"2025-{m:02d}" for m in range(5,13)]+[f"2026-{m:02d}" for m in range(1,5)])),
    ]
    print()
    print("="*84)
    print("  BB HER GÜN  vs  BB HAFTA SONU  — TAM PORTFÖY ($200 + aylık $100)")
    print("="*84)
    print(f"\n  {'Dönem':<10s}  {'Senaryo':<14s}  {'Son bakiye':>14s}  {'Net kâr':>12s}  {'maxDD':>6s}  {'BB PF':>6s}")
    print("  "+"-"*78)
    for pn,dfp in periods:
        for label,wknd in [("BB her gün",False),("BB hafta sonu",True)]:
            t,_=run_sim(dfp,bb_weekend_only=wknd)
            fb,dd=equity_curve(t)
            bb_pf=stats([x for x in t if x["strat"]=="bb"])["pf"]
            inv=START+MONTHLY_ADD*11
            print(f"  {pn:<10s}  {label:<14s}  ${fb:>12,.0f}  ${fb-inv:>+10,.0f}  {dd:>5.1%}  {bb_pf:>6.2f}",flush=True)
        print("  "+"-"*78)

    # Aylık ortalama (gerçekçi: ilk 6 ay düşük bakiye dönemi)
    print("\n  AYLIK GERÇEKÇİ GETİRİ (2024 OOS, ilk aylar — bakiye küçükken):")
    t_wd,mp_wd=run_sim(periods[1][1],bb_weekend_only=False)
    t_we,mp_we=run_sim(periods[1][1],bb_weekend_only=True)
    months=sorted(mp_wd.keys())[:6]
    print(f"  {'Ay':<9s}  {'BB her gün':>12s}  {'BB hafta sonu':>14s}")
    print("  "+"-"*40)
    for m in months:
        print(f"  {str(m):<9s}  {mp_wd[m]:>+11.0f}$  {mp_we.get(m,0):>+13.0f}$")


if __name__=="__main__":
    main()
