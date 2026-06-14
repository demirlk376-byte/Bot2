"""
research_hybrid_exit.py — ORB/Asia için ORTA YOL çıkış stratejileri

Tam portföy (BB hafta sonu sabit), ORB/Asia çıkış modu değişiyor. 3 dönem.
Trailing trend piyasasında kazanıyor ama choppy'de scratch oluyor — bunun
orta yolunu arıyoruz. Modlar:

  fixed       : sabit 2:1 TP (config B — referans, choppy'de iyi)
  trail       : be@1R + trailing (config C — trend'de iyi, choppy'de kötü)
  partial50   : %50 @2:1 kapat + kalan %50 trailing (be@1R)  ← orta yol 1
  partial33   : %33 @2:1 kapat + kalan %67 trailing
  trail_after2: 2R'ye kadar sabit gibi, 2R sonrası trailing (erken BE yok) ← orta yol 2
  fixed3      : sabit 3:1 TP ← basit orta yol

Trailing close-bazlı (canlı koda sadık). ORB trail 2×ATR, Asia 1×ATR.
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


def run_sim(df_1m, exit_mode, monthly_add=MONTHLY_ADD):
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

    # exit_mode parametreleri
    is_trail = exit_mode in ("trail","partial50","partial33","trail_after2")
    partial_frac = {"partial50":0.5,"partial33":0.33}.get(exit_mode, 0.0)
    early_be = exit_mode in ("trail","partial50","partial33")  # 1R'de breakeven
    fixed_rr = {"fixed":2.0,"fixed3":3.0}.get(exit_mode, None)

    def realize(slot, pos, qty_part, ep_exit, reason, cm, now_ts, final):
        nonlocal balance, used_margin, bb_o, orb_o, asia_o
        d=pos["dir"]; entry=pos["entry"]
        raw=d*(ep_exit-entry)*qty_part
        fee=entry*qty_part*COST_MAKER+ep_exit*qty_part*COST_TAKER
        pnl=raw-fee; balance+=pnl
        # margin orantılı serbest bırak
        mg_part = pos["margin"] * (qty_part/pos["qty0"])
        used_margin-=mg_part
        trades.append({"pnl":pnl,"strat":slot,"month":cm,"reason":reason})
        monthly_pnl.setdefault(cm,0.0); monthly_pnl[cm]+=pnl
        if final:
            if pnl<0 or pos.get("net_neg",False):
                consec[slot]+=1
                if consec[slot]>=CONSEC_LIMIT: cooldown[slot]=now_ts+pd.Timedelta(hours=COOLDOWN_HOURS)
            else: consec[slot]=0

    for i in range(warmup,n):
        a_val=atr_a[i]
        if np.isnan(a_val) or a_val<=0: continue
        cd=dates_a[i]; ch=hours_a[i]; cm=month_a[i]; now_ts=idx[i]; cp=close[i]
        if cd!=daily_date:
            daily_date=cd; daily_start=balance+used_margin
            if monthly_add>0 and ch==0 and cd.day==1: balance+=monthly_add

        for slot in ("bb","orb","asia"):
            pos = bb_o if slot=="bb" else (orb_o if slot=="orb" else asia_o)
            if pos is None: continue
            d=pos["dir"]; entry=pos["entry"]; held=i-pos["i"]; mh=pos["mh"]
            qty=pos["qty"]

            # BB: her zaman sabit (değişmez)
            if slot=="bb":
                sl=pos["sl"]; tp=pos["tp"]; ep_exit=None; reason=None
                if d==1:
                    if low_v[i]<=sl: ep_exit,reason=sl,"sl"
                    elif high_v[i]>=tp: ep_exit,reason=tp,"tp"
                else:
                    if high_v[i]>=sl: ep_exit,reason=sl,"sl"
                    elif low_v[i]<=tp: ep_exit,reason=tp,"tp"
                if ep_exit is None and held>=mh: ep_exit,reason=cp,"mh"
                if ep_exit is not None:
                    realize("bb",pos,qty,ep_exit,reason,cm,now_ts,True)
                    bb_o=None
                continue

            # ORB/Asia
            sl=pos["sl"]; R=pos["R"]; tm=pos["trail_mult"]

            # 1) hard SL kontrol
            ep_exit=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep_exit,reason=sl,("sl" if sl<=entry else "trail")
            else:
                if high_v[i]>=sl: ep_exit,reason=sl,("sl" if sl>=entry else "trail")

            # 2) fixed TP modu
            if ep_exit is None and fixed_rr is not None:
                tp = entry + d*fixed_rr*R
                if (d==1 and high_v[i]>=tp) or (d==-1 and low_v[i]<=tp):
                    ep_exit,reason=tp,"tp"

            # 3) partial: %X @2R kapat (bir kez)
            if ep_exit is None and partial_frac>0 and not pos["partial_done"]:
                tp2 = entry + d*2.0*R
                if (d==1 and high_v[i]>=tp2) or (d==-1 and low_v[i]<=tp2):
                    q_part = round(qty*partial_frac,3)
                    if q_part>=MIN_LOT and q_part<qty:
                        realize(slot,pos,q_part,tp2,"tp_partial",cm,now_ts,False)
                        pos["qty"]-=q_part
                        pos["partial_done"]=True
                        pos["net_neg"]=False
                        # kalan için breakeven
                        pos["sl"]=entry; pos["be"]=True
                        qty=pos["qty"]

            if ep_exit is not None:
                realize(slot,pos,qty,ep_exit,reason,cm,now_ts,True)
                if slot=="orb": orb_o=None
                else: asia_o=None
                continue
            if held>=mh:
                realize(slot,pos,qty,cp,"mh",cm,now_ts,True)
                if slot=="orb": orb_o=None
                else: asia_o=None
                continue

            # 4) trailing güncelle (close-bazlı)
            if is_trail:
                if d==1:
                    pos["peak"]=max(pos["peak"],cp)
                    if early_be and not pos["be"] and cp>=entry+R:
                        pos["sl"]=max(pos["sl"],entry); pos["be"]=True
                    if exit_mode=="trail_after2" and not pos["be"] and cp>=entry+2.0*R:
                        pos["be"]=True
                    if pos["be"]:
                        pos["sl"]=max(pos["sl"],pos["peak"]-tm*a_val)
                else:
                    pos["peak"]=min(pos["peak"],cp)
                    if early_be and not pos["be"] and cp<=entry-R:
                        pos["sl"]=min(pos["sl"],entry); pos["be"]=True
                    if exit_mode=="trail_after2" and not pos["be"] and cp<=entry-2.0*R:
                        pos["be"]=True
                    if pos["be"]:
                        pos["sl"]=min(pos["sl"],pos["peak"]+tm*a_val)

        equity=balance+used_margin
        if daily_start>0 and (daily_start-equity)/daily_start>=DAILY_MAX_LOSS: continue
        adx_val=adx_a[i]; trending=not np.isnan(adx_val) and adx_val>=ADX_TRENDING
        is_weekend=wday_a[i]>=5

        def mkpos(slot,i,direction,ep,sl,qty,mg,mh,R,tm):
            return {"i":i,"dir":direction,"entry":ep,"sl":sl,"qty":qty,"qty0":qty,
                    "margin":mg,"mh":mh,"R":R,"trail_mult":tm,"peak":ep,"be":False,
                    "partial_done":False,"net_neg":True}

        # BB hafta sonu sabit
        if bb_o is None and is_weekend and not trending:
            if cooldown["bb"] is None or now_ts>=cooldown["bb"]:
                if cooldown["bb"] is not None and now_ts>=cooldown["bb"]: cooldown["bb"]=None
                bpos=bb_a[i]; vm=volma_a[i]
                if not np.isnan(bpos) and (bpos<0.0 or bpos>1.0):
                    if np.isnan(vm) or vol[i]>=vm:
                        direction=1 if bpos<0.0 else -1; ep=cp; sl_dist=BB_SL*a_val
                        qty,mg=size_qty(BB_RISK,balance,free(),ep,sl_dist)
                        if qty>0:
                            used_margin+=mg
                            bb_o=mkpos("bb",i,direction,ep,ep-direction*sl_dist,qty,mg,BB_MH,sl_dist,0)
                            bb_o["tp"]=ep+direction*BB_TP*a_val

        # ORB
        if orb_o is None and cd not in orb_traded and ch>ORB_HOUR:
            if cooldown["orb"] is None or now_ts>=cooldown["orb"]:
                if cooldown["orb"] is not None and now_ts>=cooldown["orb"]: cooldown["orb"]=None
                orb=orb_by_date.get(cd)
                if orb:
                    oh=orb["high"]; ol=orb["low"]; rng=oh-ol
                    if rng>0:
                        if cp>oh:
                            qty,mg=size_qty(ORB_RISK,balance,free(),oh,rng)
                            if qty>0:
                                used_margin+=mg; orb_traded.add(cd)
                                orb_o=mkpos("orb",i,1,oh,ol,qty,mg,ORB_MH,rng,2.0)
                        elif cp<ol:
                            qty,mg=size_qty(ORB_RISK,balance,free(),ol,rng)
                            if qty>0:
                                used_margin+=mg; orb_traded.add(cd)
                                orb_o=mkpos("orb",i,-1,ol,oh,qty,mg,ORB_MH,rng,2.0)

        # Asia BO
        if asia_o is None and cd not in asia_traded and ch>=8:
            if cooldown["asia"] is None or now_ts>=cooldown["asia"]:
                if cooldown["asia"] is not None and now_ts>=cooldown["asia"]: cooldown["asia"]=None
                asia=asia_by_date.get(cd)
                if asia and asia["cnt"]>=4:
                    ah=asia["high"]; al=asia["low"]; sl_dist=ASIA_SL*a_val
                    if cp>ah:
                        qty,mg=size_qty(ASIA_RISK,balance,free(),ah,sl_dist)
                        if qty>0:
                            used_margin+=mg; asia_traded.add(cd)
                            asia_o=mkpos("asia",i,1,ah,ah-sl_dist,qty,mg,ASIA_MH,sl_dist,1.0)
                    elif cp<al:
                        qty,mg=size_qty(ASIA_RISK,balance,free(),al,sl_dist)
                        if qty>0:
                            used_margin+=mg; asia_traded.add(cd)
                            asia_o=mkpos("asia",i,-1,al,al+sl_dist,qty,mg,ASIA_MH,sl_dist,1.0)

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
    modes=["fixed","trail","partial50","partial33","trail_after2","fixed3"]

    print("\n"+"="*92)
    print("  ORTA YOL TARAMASI — Son bakiye / maxDD (BB hafta sonu sabit, 3 dönem)")
    print("="*92)
    print(f"  {'Mod':<14s}"+"".join(f"  {pn:>11s} {'DD':>5s}" for pn,_ in periods)+f"  {'min$':>11s}")
    print("  "+"-"*90)
    results={}
    for mode in modes:
        row=f"  {mode:<14s}"; finals=[]
        for pn,dfp in periods:
            t,_=run_sim(dfp,mode)
            fb,dd=equity_curve(t)
            finals.append(fb)
            row+=f"  ${fb:>10,.0f} {dd:>4.0%}"
        row+=f"  ${min(finals):>10,.0f}"
        tag=""
        if mode=="fixed": tag=" ← config B"
        elif mode=="trail": tag=" ← config C (canlı)"
        print(row+tag,flush=True)
        results[mode]=finals

    print("\n  'min$' = en kötü dönemdeki son bakiye (sağlamlık göstergesi — yüksek = iyi).")
    print("  Hedef: 3 dönemde de fixed'i geçen, en kötü dönemi en yüksek olan mod.")


if __name__=="__main__":
    main()
