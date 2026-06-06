"""
Gerçekten test edilmemiş 3 hipotez:
1. RSI diverjansı: fiyat yeni dip ama RSI yükselen dip → güçlü reversal sinyali
2. BB genişliği filtresi: çok dar BB (squeeze) = breakout riski yüksek, al-satma
3. Hacim çarpanı: sadece ortalama > 1 değil, 1.5x/2x/3x gereksin
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, rsi as rsi_fn

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

def run(df_1h, rsi_div=False, bb_width_min=0.0, vol_mult=1.0):
    c=df_1h["close"].values; h=df_1h["high"].values; lo=df_1h["low"].values
    vol=df_1h["volume"].values
    upper,middle,lower=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    rsi_s=rsi_fn(df_1h["close"],14).values
    vol_ma=df_1h["volume"].rolling(20).mean().values
    bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values
    # BB bandwidth = (upper-lower)/middle
    bb_width=((upper-lower)/middle).values
    bb_width_pct=pd.Series(bb_width).rolling(50).rank(pct=True).values  # percentile

    n=len(c); warmup=60
    balance=BAL; open_t=None; trades=[]

    for i in range(warmup,n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue
        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]
            sl=open_t["sl"]; tp=open_t["tp"]; qty=open_t["qty"]; held=i-open_t["i"]
            ep=None; reason=None
            if d==1:
                if lo[i]<=sl: ep,reason=sl,"sl"
                elif h[i]>=tp: ep,reason=tp,"tp"
            else:
                if h[i]>=sl: ep,reason=sl,"sl"
                elif lo[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=MH: ep,reason=c[i],"mh"
            if ep is not None:
                pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST
                balance+=pnl
                trades.append({"ts":df_1h.index[i],"pnl":pnl,"reason":reason})
                open_t=None
            continue

        bpos=bb_pos[i]
        if np.isnan(bpos) or not (bpos<0 or bpos>1): continue
        direction=1 if bpos<0 else -1
        # Hacim filtresi (çarpan ile)
        if not np.isnan(vol_ma[i]) and vol[i] < vol_ma[i]*vol_mult: continue

        # BB genişlik filtresi: çok dar BB'yi atla (squeeze → breakout riski)
        if not np.isnan(bb_width_pct[i]) and bb_width_pct[i] < bb_width_min: continue

        # RSI diverjansı
        if rsi_div and i >= 5:
            rsi_now = rsi_s[i]
            if np.isnan(rsi_now): continue
            if direction == 1:
                # Fiyat dip mi (son 5 mumla karşılaştır)?
                prev_lows = [c[j] for j in range(i-5,i) if c[j]<lower.iloc[j] if not np.isnan(lower.iloc[j])]
                if not prev_lows: continue  # Önceki dip yok → diverjans yok
                prev_low_price = min(prev_lows)
                if c[i] >= prev_low_price: continue  # Fiyat yeni dip değil
                # RSI karşılık gelen değeri
                prev_rsi_at_lows = [rsi_s[j] for j in range(i-5,i) if c[j]<lower.iloc[j] if not np.isnan(lower.iloc[j]) and not np.isnan(rsi_s[j])]
                if not prev_rsi_at_lows: continue
                prev_rsi = min(prev_rsi_at_lows)
                if rsi_now <= prev_rsi: continue  # RSI yeni dip → diverjans yok
            else:
                prev_highs = [c[j] for j in range(i-5,i) if c[j]>upper.iloc[j] if not np.isnan(upper.iloc[j])]
                if not prev_highs: continue
                prev_high_price = max(prev_highs)
                if c[i] <= prev_high_price: continue
                prev_rsi_at_highs = [rsi_s[j] for j in range(i-5,i) if c[j]>upper.iloc[j] if not np.isnan(upper.iloc[j]) and not np.isnan(rsi_s[j])]
                if not prev_rsi_at_highs: continue
                prev_rsi = max(prev_rsi_at_highs)
                if rsi_now >= prev_rsi: continue

        ep=c[i]; sl_d=SL_M*a
        sl=ep-direction*sl_d; tp=ep+direction*TP_M*a
        qty=round((balance*RISK)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
        if qty<0.001: continue
        open_t={"i":i,"ts":df_1h.index[i],"dir":direction,"entry":ep,"sl":sl,"tp":tp,"qty":qty}
    return trades

def sc(trades, split):
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
    print(f"{label:<50s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    split=pd.Timestamp("2026-01-01")
    print("="*115)
    print("SİNYAL KALİTE FİLTRELERİ — RSI diverjansı | BB genişliği | Hacim çarpanı")
    print("="*115)
    configs=[
        ("BASELINE",                              False, 0.0, 1.0),
        ("RSI diverjansı filtresi",               True,  0.0, 1.0),
        ("BB genişlik >20. percentil",            False, 0.2, 1.0),
        ("BB genişlik >40. percentil",            False, 0.4, 1.0),
        ("Hacim >1.5x ortalama",                  False, 0.0, 1.5),
        ("Hacim >2x ortalama",                    False, 0.0, 2.0),
        ("Hacim >2x + BB genişlik >20pct",        False, 0.2, 2.0),
        ("RSI div + BB genişlik >20pct",          True,  0.2, 1.0),
    ]
    for label, rdiv, bbw, vmult in configs:
        trades=run(df_1h, rsi_div=rdiv, bb_width_min=bbw, vol_mult=vmult)
        tr,te=sc(trades,split); pr(label,tr,te)

if __name__=="__main__":
    main()
