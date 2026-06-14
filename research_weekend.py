"""
research_weekend.py — Hafta içi vs hafta sonu trade başarısı

Her trade'i GİRİŞ gününün haftanın gününe göre etiketler, strateji bazında
win-rate / PnL / profit-factor hesaplar. Hafta sonu (Cmt+Paz) ayrı raporlanır.
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST=0.0002; LEVERAGE=10; MIN_LOT=0.001; START=200.0
BB_SL=3.0; BB_TP=5.0; BB_MH=48
ORB_RR=2.0; ORB_MH=6; ORB_HOUR=14
ASIA_RR=2.0; ASIA_SL_MULT=1.0; ASIA_MH=6
# Agresif profil
SIZING={"bb":0.08,"orb":0.05,"asia":0.03}

def load_all():
    files=sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames=[]
    for f in files:
        df=pd.read_csv(f)
        df.columns=["ts","open","high","low","close","volume","ct","qv","count","tbv","tbqv","ign"]
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full=pd.concat(frames,ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index=pd.to_datetime(full["ts"],unit="ms")
    return full.drop(columns=["ts"])

def resample(df,rule):
    return df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def size(risk_pct,balance,free,ep,sl_dist):
    risk_amt=balance*risk_pct
    qty=risk_amt/sl_dist if sl_dist>0 else 0.0
    margin=qty*ep/LEVERAGE
    if margin>free:
        qty=free*LEVERAGE/ep; margin=free
    qty=round(qty,3)
    if qty<MIN_LOT: return 0.0,0.0
    margin=qty*ep/LEVERAGE
    if margin>free+1e-9: return 0.0,0.0
    return qty,margin

def run(df_1h):
    close=df_1h["close"].values; high=df_1h["high"].values; low_v=df_1h["low"].values
    vol=df_1h["volume"].values; idx=df_1h.index
    upper_s,_,lower_s=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma=df_1h["volume"].rolling(20).mean()
    bb_pos=((df_1h["close"]-lower_s)/(upper_s-lower_s).replace(0,np.nan))
    atr_arr=atr_s.values; volma_arr=vol_ma.values; bb_arr=bb_pos.values
    n=len(close); warmup=60
    dates_arr=np.array([ts.date() for ts in idx]); hours_arr=np.array([ts.hour for ts in idx])
    orb_by_date={}; asia_by_date={}
    for j in range(n):
        d=dates_arr[j]; h=hours_arr[j]
        if h==ORB_HOUR: orb_by_date[d]={"high":high[j],"low":low_v[j]}
        if h<8:
            if d not in asia_by_date: asia_by_date[d]={"high":high[j],"low":low_v[j],"count":1}
            else:
                asia_by_date[d]["high"]=max(asia_by_date[d]["high"],high[j])
                asia_by_date[d]["low"]=min(asia_by_date[d]["low"],low_v[j])
                asia_by_date[d]["count"]+=1
    balance=START; used=0.0
    bb_o=orb_o=asia_o=None; trades=[]; orb_t=set(); asia_t=set()
    def free(): return balance-used
    for i in range(warmup,n):
        a=atr_arr[i]
        if np.isnan(a) or a<=0: continue
        cd=dates_arr[i]; ch=hours_arr[i]
        bb_c=orb_c=asia_c=False
        for slot,pos in (("bb",bb_o),("orb",orb_o),("asia",asia_o)):
            if pos is None: continue
            d=pos["dir"]; entry=pos["entry"]; sl=pos["sl"]; tp=pos["tp"]; qty=pos["qty"]; mh=pos["mh"]; held=i-pos["i"]
            ep=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep,reason=sl,"sl"
                elif high[i]>=tp: ep,reason=tp,"tp"
            else:
                if high[i]>=sl: ep,reason=sl,"sl"
                elif low_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=mh: ep,reason=close[i],"mh"
            if ep is not None:
                pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST
                balance+=pnl; used-=pos["margin"]
                trades.append({"entry_ts":pos["ets"],"pnl":pnl,"strat":slot})
                if slot=="bb": bb_o=None; bb_c=True
                elif slot=="orb": orb_o=None; orb_c=True
                else: asia_o=None; asia_c=True
        if bb_o is None and not bb_c:
            bpos=bb_arr[i]
            if not np.isnan(bpos) and (bpos<0.0 or bpos>1.0):
                direction=1 if bpos<0.0 else -1; vm=volma_arr[i]
                if np.isnan(vm) or vol[i]>=vm:
                    ep=close[i]; sl_d=BB_SL*a
                    qty,m=size(SIZING["bb"],balance,free(),ep,sl_d)
                    if qty>0:
                        used+=m; bb_o={"i":i,"ets":idx[i],"dir":direction,"entry":ep,"sl":ep-direction*sl_d,"tp":ep+direction*BB_TP*a,"qty":qty,"margin":m,"mh":BB_MH}
        if orb_o is None and not orb_c and cd not in orb_t and ch>ORB_HOUR:
            orb=orb_by_date.get(cd)
            if orb is not None:
                oh=orb["high"]; ol=orb["low"]; rng=oh-ol
                if rng>0:
                    cp=close[i]; direction=1 if cp>oh else (-1 if cp<ol else 0)
                    if direction!=0:
                        ep=oh if direction==1 else ol
                        qty,m=size(SIZING["orb"],balance,free(),ep,rng)
                        if qty>0:
                            used+=m; orb_t.add(cd)
                            orb_o={"i":i,"ets":idx[i],"dir":direction,"entry":ep,"sl":ep-direction*rng,"tp":ep+direction*ORB_RR*rng,"qty":qty,"margin":m,"mh":ORB_MH}
        if asia_o is None and not asia_c and cd not in asia_t and ch>=8:
            asia=asia_by_date.get(cd)
            if asia is not None and asia["count"]>=4:
                ah=asia["high"]; al=asia["low"]
                cp=close[i]; direction=1 if cp>ah else (-1 if cp<al else 0)
                if direction!=0:
                    sl_d=ASIA_SL_MULT*a; ep=ah if direction==1 else al
                    qty,m=size(SIZING["asia"],balance,free(),ep,sl_d)
                    if qty>0:
                        used+=m; asia_t.add(cd)
                        asia_o={"i":i,"ets":idx[i],"dir":direction,"entry":ep,"sl":ep-direction*sl_d,"tp":ep+direction*ASIA_RR*sl_d,"qty":qty,"margin":m,"mh":ASIA_MH}
    return trades

def stats(tt):
    if not tt: return (0,0,0,0)
    p=np.array([t["pnl"] for t in tt])
    pos=p[p>0].sum(); neg=-p[p<0].sum()
    pf=pos/neg if neg>0 else 999
    return (len(p),(p>0).mean(),p.sum(),pf)

def main():
    print("Veri yükleniyor…")
    df=resample(load_all(),"1h")
    trades=run(df)
    days=["Pzt","Sal","Çar","Per","Cum","Cmt","Paz"]
    print(f"\nToplam {len(trades)} trade (agresif profil)\n")

    print("="*72)
    print("HAFTANIN GÜNÜNE GÖRE (giriş günü) — TÜM STRATEJİLER")
    print("="*72)
    print(f"{'Gün':<6s} {'Trade':>6s} {'WinRate':>8s} {'PF':>6s} {'Net PnL':>10s}")
    print("-"*72)
    for wd in range(7):
        dt=[t for t in trades if t['entry_ts'].weekday()==wd]
        n,wr,pnl,pf=stats(dt)
        we=" 🔵 hafta sonu" if wd>=5 else ""
        print(f"{days[wd]:<6s} {n:>6d} {wr:>7.0%} {pf:>6.2f} {pnl:>+9.0f}${we}")

    print("\n"+"="*72)
    print("HAFTA İÇİ vs HAFTA SONU")
    print("="*72)
    wk=[t for t in trades if t['entry_ts'].weekday()<5]
    we=[t for t in trades if t['entry_ts'].weekday()>=5]
    for label,grp in [("Hafta içi (Pzt-Cum)",wk),("Hafta sonu (Cmt-Paz)",we)]:
        n,wr,pnl,pf=stats(grp)
        share=n/len(trades)*100 if trades else 0
        print(f"  {label:<24s}: {n:>4d}t ({share:>4.1f}%)  WR{wr:>4.0%}  PF{pf:.2f}  net {pnl:>+8.0f}$")

    print("\n"+"="*72)
    print("STRATEJİ × HAFTA SONU")
    print("="*72)
    for strat in ["bb","orb","asia"]:
        st=[t for t in trades if t["strat"]==strat]
        wk=[t for t in st if t['entry_ts'].weekday()<5]
        we=[t for t in st if t['entry_ts'].weekday()>=5]
        nw,wrw,pw,pfw=stats(wk); ne,wre,pe,pfe=stats(we)
        print(f"  {strat.upper():<5s} hafta içi: {nw:>3d}t WR{wrw:>3.0%} PF{pfw:.2f} {pw:>+7.0f}$  |  "
              f"hafta sonu: {ne:>3d}t WR{wre:>3.0%} PF{pfe:.2f} {pe:>+7.0f}$")

if __name__=="__main__":
    main()
