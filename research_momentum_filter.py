"""
SL analizinin kilit bulgusu: Peş peşe yön mumu sayısı WR'ı etkiliyor.
  0 ardışık mum (ani kırılım) : WR %54 — fiyat yükselirken ani düşüş
  1 ardışık mum               : WR %42 — en kötü, trendin erken safhası
  3+ ardışık mum              : WR %50-75 — uzun düşüş = tükenme

Test: "1 ardışık mum" girişlerini filtrele (YA ani kırılım YA en az 2 ardışık)

Ayrıca: "ani kırılım" tek başına filtresi (sadece 0-ardışık al)
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

COST=0.0002; SL_M=3.0; TP_M=5.0; BAL=10_000.0; RISK=0.03; MH=48

def run(df_1h, skip_n_consec=None, require_min_consec=0):
    """
    skip_n_consec    : skip entries with exactly this many consecutive candles (None = no filter)
    require_min_consec: require at least this many consecutive candles (0 = no minimum)
    """
    close=df_1h["close"].values; high=df_1h["high"].values; low=df_1h["low"].values
    vol=df_1h["volume"].values
    upper,middle,lower=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma=df_1h["volume"].rolling(20).mean().values
    bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values

    n=len(close); warmup=60
    balance=BAL; open_t=None; trades=[]

    for i in range(warmup,n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue

        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]
            sl=open_t["sl"]; tp=open_t["tp"]
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
                balance+=d*(ep-entry)*qty-(entry+ep)*qty*COST
                trades.append({"ts":df_1h.index[i],"pnl":d*(ep-entry)*qty-(entry+ep)*qty*COST,"reason":reason})
                open_t=None
            continue

        bpos=bb_pos[i]
        if np.isnan(bpos): continue
        if not (bpos<0 or bpos>1): continue
        direction=1 if bpos<0 else -1
        if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue

        # Count consecutive directional candles before entry
        consec=0
        for j in range(i-1,max(i-15,-1),-1):
            if j<1: break
            if direction==1 and close[j]<close[j-1]: consec+=1
            elif direction==-1 and close[j]>close[j-1]: consec+=1
            else: break

        if skip_n_consec is not None and consec==skip_n_consec:
            continue
        if consec < require_min_consec:
            continue

        ep=close[i]; sl_d=SL_M*a; tp_d=TP_M*a
        slp=ep-direction*sl_d; tpp=ep+direction*tp_d
        qty=round((balance*RISK)/(ep*(sl_d/ep)),3)
        qty=min(qty,balance*0.5/ep)
        if qty<0.001: continue
        open_t={"i":i,"ts":df_1h.index[i],"dir":direction,
                "entry":ep,"sl":slp,"tp":tpp,"qty":qty}
    return trades

def sc(trades,split):
    tr=[t for t in trades if t["ts"]<split]
    te=[t for t in trades if t["ts"]>=split]
    def s(tt):
        if not tt: return dict(n=0,wr=0,pnl=0,pf=0,dd=0)
        p=np.array([t["pnl"] for t in tt])
        pos=p[p>0].sum(); neg=-p[p<0].sum()
        pf=pos/neg if neg>0 else float("inf")
        eq=BAL+np.cumsum(p); pk=np.maximum.accumulate(eq)
        return dict(n=len(p),wr=(p>0).mean(),pnl=p.sum(),pf=pf,dd=((pk-eq)/pk).max())
    return s(tr),s(te)

def pr(label,tr,te):
    tot=tr["pnl"]+te["pnl"]
    print(f"{label:<45s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    split=pd.Timestamp("2026-01-01")

    print("="*108)
    print("MOMENTUM FİLTRE TESTİ — ardışık mum sayısına göre filtreler")
    print("Teori: 0 ardışık (ani kırılım)=iyi | 1 ardışık=kötü | 3+=iyi")
    print("="*108)
    configs=[
        ("BASELINE (filtre yok)",           None, 0),
        ("1 ardışık atla (kötü WR)",         1,    0),
        ("Min 2 ardışık zorunlu",            None, 2),
        ("Min 3 ardışık zorunlu",            None, 3),
        ("Min 2 VEYA 0 (1'i atla = skip=1)", 1,    0),  # same as skip_n=1
        ("0 ardışık SADECE (ani kırılım)",   None, 0),  # we'll test manually
    ]

    # First 5 from configs list
    for label, skip, req in configs[:5]:
        trades=run(df_1h, skip_n_consec=skip, require_min_consec=req)
        tr,te=sc(trades,split); pr(label,tr,te)

    # Special: only 0-consecutive (sudden break)
    t0=run(df_1h); t0_filtered=[t for t in run(df_1h)]
    # Rebuild with consec=0 only
    close=df_1h["close"].values
    upper,_,lower=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma=df_1h["volume"].rolling(20).mean().values
    bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values
    n=len(close); warmup=60
    balance=BAL; open_t=None; only0=[]
    high=df_1h["high"].values; low_v=df_1h["low"].values; vol=df_1h["volume"].values

    for i in range(warmup,n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue
        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]; sl=open_t["sl"]; tp=open_t["tp"]
            qty=open_t["qty"]; held=i-open_t["i"]
            ep=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep,reason=sl,"sl"
                elif high[i]>=tp: ep,reason=tp,"tp"
            else:
                if high[i]>=sl: ep,reason=sl,"sl"
                elif low_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=MH: ep,reason=close[i],"mh"
            if ep is not None:
                balance+=d*(ep-entry)*qty-(entry+ep)*qty*COST
                only0.append({"ts":df_1h.index[i],"pnl":d*(ep-entry)*qty-(entry+ep)*qty*COST,"reason":reason})
                open_t=None
            continue
        bpos=bb_pos[i]
        if np.isnan(bpos) or not (bpos<0 or bpos>1): continue
        direction=1 if bpos<0 else -1
        if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue
        consec=0
        for j in range(i-1,max(i-10,-1),-1):
            if j<1: break
            if direction==1 and close[j]<close[j-1]: consec+=1
            elif direction==-1 and close[j]>close[j-1]: consec+=1
            else: break
        if consec!=0: continue  # only fresh breaks
        ep=close[i]; sl_d=SL_M*a; tp_d=TP_M*a
        slp=ep-direction*sl_d; tpp=ep+direction*tp_d
        qty=round((balance*RISK)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
        if qty<0.001: continue
        open_t={"i":i,"ts":df_1h.index[i],"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}

    tr0,te0=sc(only0,split)
    pr("Sadece 0 ardışık (ani kırılım)",tr0,te0)

    # Monthly detail for skip=1 vs baseline
    print()
    print("--- Aylık: BASELINE vs '1 ardışık atla' ---")
    base=run(df_1h,None,0)
    filt=run(df_1h,1,0)
    def monthly(tt):
        m={}
        for t in tt: m.setdefault(t["ts"].strftime("%Y-%m"),[]).append(t["pnl"])
        return m
    mb=monthly(base); mf=monthly(filt)
    print(f"{'Ay':<10s}  {'Temel':>7s} {'Temel$':>8s}  {'Filt':>7s} {'Filt$':>8s}  {'Delta':>8s}")
    for m in sorted(set(list(mb)+list(mf))):
        bp=np.array(mb.get(m,[0])); fp=np.array(mf.get(m,[0]))
        print(f"  {m}   {len(bp):>5d}t {bp.sum():>+8.1f}    {len(fp):>5d}t {fp.sum():>+8.1f}   {fp.sum()-bp.sum():>+8.1f}")

if __name__=="__main__":
    main()
