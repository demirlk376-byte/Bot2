"""
3 kurumsal price action setup — OHLCV üzerinde tam backtest:
1. SFP (Swing Failure Pattern) — stop hunt / likidite tuzağı tespiti
2. FVG (Fair Value Gap)        — kurumsal dengesizlik retesti
3. Wyckoff Spring              — destek altına sahte dalış + geri dönüş
+ BB mean-rev ile confluence testi
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

COST=0.0002; BAL=10_000.0; RISK=0.03; MH=48

def run_sfp(df_1h, swing_lookback=10, sl_mult=1.5, tp_mult=3.0):
    """
    Swing Failure Pattern:
    - Fiyat son N bar'ın swing high'ını fitil ile geçer
    - AMA mum gövdesi swing high'ın altında kapanır → sahte kırılım = SHORT
    - Fiyat son N bar'ın swing low'unu fitil ile geçer
    - AMA mum gövdesi swing low'un üstünde kapanır → sahte kırılım = LONG
    SL: fitilin ucundan biraz ötesi | TP: karşı swing + yapı ortası
    """
    o=df_1h["open"].values; c=df_1h["close"].values
    h=df_1h["high"].values; lo=df_1h["low"].values; vol=df_1h["volume"].values
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    n=len(c); warmup=swing_lookback+20; balance=BAL; open_t=None; trades=[]

    for i in range(warmup, n):
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

        # Swing levels (son N bar, bu bar hariç)
        recent_high = h[i-swing_lookback:i].max()
        recent_low  = lo[i-swing_lookback:i].min()
        body_high   = max(o[i], c[i])
        body_low    = min(o[i], c[i])

        direction = 0
        wick_tip  = 0.0

        # Bearish SFP: high > recent_high ama kapanış < recent_high
        if h[i] > recent_high and c[i] < recent_high and body_high < recent_high:
            direction = -1
            wick_tip  = h[i]  # fit ucu → SL biraz üstü

        # Bullish SFP: low < recent_low ama kapanış > recent_low
        elif lo[i] < recent_low and c[i] > recent_low and body_low > recent_low:
            direction = 1
            wick_tip  = lo[i]

        if direction == 0: continue

        # Hacim filtresi — en azından ortalamada olsun
        vol_ma = vol[max(0,i-20):i].mean()
        if vol[i] < vol_ma * 0.7: continue  # çok düşük hacimli SFP güvenilmez

        ep = c[i]
        sl_d = abs(ep - wick_tip) + 0.1*a  # SL fitilin ucunun biraz ötesi
        if sl_d < 0.3*a: sl_d = 0.3*a      # minimum sl mesafesi
        tp_d = sl_d * (tp_mult/sl_mult)
        sl = ep - direction*sl_d
        tp = ep + direction*tp_d
        qty = round((balance*RISK)/(ep*(sl_d/ep)), 3)
        qty = min(qty, balance*0.5/ep)
        if qty < 0.001: continue
        open_t={"i":i,"ts":df_1h.index[i],"dir":direction,"entry":ep,"sl":sl,"tp":tp,"qty":qty}
    return trades


def run_fvg(df_1h, sl_mult=2.0, tp_mult=4.0, max_wait=12):
    """
    Fair Value Gap:
    Bullish FVG: bar[i-2].high < bar[i].low → boşluk var
    Fiyat bu boşluğa geri dönünce LONG — giriş boşluğun ortası
    Bearish FVG: bar[i-2].low > bar[i].high → boşluk var
    Fiyat geri dönünce SHORT
    max_wait: kaç bar içinde fill olmazsa iptal
    """
    o=df_1h["open"].values; c=df_1h["close"].values
    h=df_1h["high"].values; lo=df_1h["low"].values; vol=df_1h["volume"].values
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma_s=df_1h["volume"].rolling(20).mean().values
    n=len(c); warmup=30; balance=BAL; open_t=None; trades=[]
    pending_fvgs=[]  # (direction, fvg_low, fvg_high, entry_target, sl, tp, qty, created_i)

    for i in range(warmup, n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue

        # Aktif trade yönet
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
            if open_t is not None: continue

        # Pending FVG'leri güncelle
        new_pending=[]
        for fvg in pending_fvgs:
            d2,fvg_lo,fvg_hi,exp_i=fvg["d"],fvg["flo"],fvg["fhi"],fvg["exp"]
            if i > exp_i: continue  # süresi doldu
            mid=(fvg_lo+fvg_hi)/2
            # Fill kontrolü: fiyat FVG orta noktasına ulaştı mı?
            if d2==1 and lo[i]<=mid and h[i]>=fvg_lo:
                # LONG giriş
                ep=mid; sl_d2=fvg["sl_d"]; tp_d2=sl_d2*(tp_mult/sl_mult)
                sl2=ep-sl_d2; tp2=ep+tp_d2
                qty2=round((balance*RISK)/(ep*(sl_d2/ep)),3); qty2=min(qty2,balance*0.5/ep)
                if qty2>=0.001 and open_t is None:
                    open_t={"i":i,"ts":df_1h.index[i],"dir":1,"entry":ep,"sl":sl2,"tp":tp2,"qty":qty2}
                continue
            elif d2==-1 and h[i]>=mid and lo[i]<=fvg_hi:
                ep=mid; sl_d2=fvg["sl_d"]; tp_d2=sl_d2*(tp_mult/sl_mult)
                sl2=ep+sl_d2; tp2=ep-tp_d2
                qty2=round((balance*RISK)/(ep*(sl_d2/ep)),3); qty2=min(qty2,balance*0.5/ep)
                if qty2>=0.001 and open_t is None:
                    open_t={"i":i,"ts":df_1h.index[i],"dir":-1,"entry":ep,"sl":sl2,"tp":tp2,"qty":qty2}
                continue
            new_pending.append(fvg)
        pending_fvgs=new_pending

        if open_t is not None: continue

        # Yeni FVG tespiti
        if i < 2: continue
        # Bullish FVG: bar[i-2].high < bar[i].low
        if h[i-2] < lo[i]:
            fvg_lo=h[i-2]; fvg_hi=lo[i]
            gap=fvg_hi-fvg_lo
            if gap > 0.1*a:  # anlamsız küçük boşlukları atla
                sl_d2=sl_mult*a
                # Hacim: orta bar güçlü olmalı
                if not np.isnan(vol_ma_s[i]) and vol[i-1]>vol_ma_s[i-1]*1.2:
                    pending_fvgs.append({"d":1,"flo":fvg_lo,"fhi":fvg_hi,
                                         "sl_d":sl_d2,"exp":i+max_wait})
        # Bearish FVG: bar[i-2].low > bar[i].high
        elif lo[i-2] > h[i]:
            fvg_lo=h[i]; fvg_hi=lo[i-2]
            gap=fvg_hi-fvg_lo
            if gap > 0.1*a:
                sl_d2=sl_mult*a
                if not np.isnan(vol_ma_s[i]) and vol[i-1]>vol_ma_s[i-1]*1.2:
                    pending_fvgs.append({"d":-1,"flo":fvg_lo,"fhi":fvg_hi,
                                         "sl_d":sl_d2,"exp":i+max_wait})
    return trades


def run_wyckoff_spring(df_1h, support_lb=20, pct_min=0.001, pct_max=0.04,
                       recover_bars=5, sl_mult=2.0, tp_mult=4.0):
    """
    Wyckoff Spring:
    - Support = son N bar'ın minimumu
    - Fiyat support'un pct_min-%pct_max altına iner
    - recover_bars içinde support'un üstüne kapanır
    - Düşük hacimli spring daha güvenilir → pozitif filtre
    """
    c=df_1h["close"].values; h=df_1h["high"].values; lo=df_1h["low"].values
    vol=df_1h["volume"].values
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma_s=df_1h["volume"].rolling(20).mean().values
    n=len(c); warmup=support_lb+20; balance=BAL; open_t=None; trades=[]
    in_spring=None  # (support, wick_low, bar_i)

    for i in range(warmup, n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue
        if open_t is not None:
            d=open_t["dir"]; entry=open_t["entry"]
            sl=open_t["sl"]; tp=open_t["tp"]; qty=open_t["qty"]; held=i-open_t["i"]
            ep=None; reason=None
            if lo[i]<=sl: ep,reason=sl,"sl"
            elif h[i]>=tp: ep,reason=tp,"tp"
            if ep is None and held>=MH: ep,reason=c[i],"mh"
            if ep is not None:
                pnl=1*(ep-entry)*qty-(entry+ep)*qty*COST
                balance+=pnl
                trades.append({"ts":df_1h.index[i],"pnl":pnl,"reason":reason})
                open_t=None
            if open_t is not None: continue

        # Support seviyesi
        support = lo[i-support_lb:i].min()

        # Spring tespiti: lo < support * (1 - pct_min)
        if lo[i] < support * (1 - pct_min):
            penetration = (support - lo[i]) / support
            if penetration <= pct_max:
                in_spring={"support":support,"wick_low":lo[i],"bar_i":i,
                           "spring_vol":vol[i],"spring_vol_ma":vol_ma_s[i]}
            # Çok derin dalış → gerçek kırılım, spring değil

        # Eğer spring varsa recover kontrolü
        if in_spring and open_t is None:
            sp=in_spring
            bars_since=i-sp["bar_i"]
            if bars_since > recover_bars:
                in_spring=None; continue
            if c[i] > sp["support"]:  # support üstünde kapandı = geri döndü
                # Hacim filtresi: spring bar'ı düşük hacimli ise daha güvenilir
                low_vol_spring = (not np.isnan(sp["spring_vol_ma"]) and
                                  sp["spring_vol"] < sp["spring_vol_ma"]*0.8)
                ep=c[i]; sl_d=abs(ep-sp["wick_low"])+0.1*a
                if sl_d < 0.5*a: sl_d=0.5*a
                tp_d=sl_d*(tp_mult/sl_mult)
                sl=ep-sl_d; tp_p=ep+tp_d
                qty=round((balance*RISK)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
                if qty>=0.001:
                    open_t={"i":i,"ts":df_1h.index[i],"dir":1,"entry":ep,
                            "sl":sl,"tp":tp_p,"qty":qty,"low_vol":low_vol_spring}
                in_spring=None
    return trades


def run_bb_plus_sfp(df_1h, swing_lookback=10):
    """BB sinyali + SFP onayı confluence"""
    o=df_1h["open"].values; c=df_1h["close"].values
    h=df_1h["high"].values; lo=df_1h["low"].values; vol=df_1h["volume"].values
    upper,_,lower=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma=df_1h["volume"].rolling(20).mean().values
    bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values
    SL_M=3.0; TP_M=5.0
    n=len(c); warmup=60; balance=BAL; open_t=None; trades=[]

    for i in range(warmup+swing_lookback, n):
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
        if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue

        # SFP onayı gerekiyor
        recent_high=h[i-swing_lookback:i].max()
        recent_low=lo[i-swing_lookback:i].min()
        body_high=max(o[i],c[i]); body_low=min(o[i],c[i])

        has_sfp=False
        if direction==1 and lo[i]<recent_low and c[i]>recent_low and body_low>recent_low:
            has_sfp=True
        elif direction==-1 and h[i]>recent_high and c[i]<recent_high and body_high<recent_high:
            has_sfp=True
        if not has_sfp: continue

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
    print(f"{label:<48s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  |  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
          f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h"); split=pd.Timestamp("2026-01-01")
    print("="*115)
    print("KURUMSAL PRICE ACTION — SFP | FVG | Wyckoff Spring | BB+SFP Confluence")
    print("="*115)

    # SFP variations
    for lb in [5, 10, 20]:
        t=run_sfp(df_1h, swing_lookback=lb)
        tr,te=sc(t,split); pr(f"SFP (swing lookback={lb}h)", tr, te)

    print()
    # FVG variations
    for mw in [6, 12, 24]:
        t=run_fvg(df_1h, max_wait=mw)
        tr,te=sc(t,split); pr(f"FVG retest (max wait={mw}h)", tr, te)

    print()
    # Wyckoff Spring
    for pmin, pmax in [(0.001,0.02),(0.002,0.04),(0.001,0.05)]:
        t=run_wyckoff_spring(df_1h, pct_min=pmin, pct_max=pmax)
        tr,te=sc(t,split); pr(f"Wyckoff Spring ({pmin*100:.1f}%-{pmax*100:.0f}%)", tr, te)

    print()
    # BB + SFP confluence
    for lb in [5, 10]:
        t=run_bb_plus_sfp(df_1h, swing_lookback=lb)
        tr,te=sc(t,split); pr(f"BB extreme + SFP onayı (swing lb={lb}h)", tr, te)

    print()
    print("REFERANS — mevcut sistem:")
    from indicators import bollinger_bands as bb_fn
    def run_baseline(df_1h):
        c=df_1h["close"].values; h=df_1h["high"].values; lo=df_1h["low"].values; vol=df_1h["volume"].values
        upper,_,lower=bb_fn(df_1h["close"],20,2.0); atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
        vol_ma=df_1h["volume"].rolling(20).mean().values
        bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values
        n=len(c); warmup=60; balance=BAL; open_t=None; trades=[]
        for i in range(warmup,n):
            a=atr_s.iloc[i]
            if np.isnan(a) or a<=0: continue
            if open_t is not None:
                d=open_t["dir"]; entry=open_t["entry"]; sl=open_t["sl"]; tp=open_t["tp"]; qty=open_t["qty"]; held=i-open_t["i"]
                ep=None; reason=None
                if d==1:
                    if lo[i]<=sl: ep,reason=sl,"sl"
                    elif h[i]>=tp: ep,reason=tp,"tp"
                else:
                    if h[i]>=sl: ep,reason=sl,"sl"
                    elif lo[i]<=tp: ep,reason=tp,"tp"
                if ep is None and held>=MH: ep,reason=c[i],"mh"
                if ep is not None:
                    pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST; balance+=pnl
                    trades.append({"ts":df_1h.index[i],"pnl":pnl,"reason":reason}); open_t=None
                continue
            bpos=bb_pos[i]
            if np.isnan(bpos) or not (bpos<0 or bpos>1): continue
            direction=1 if bpos<0 else -1
            if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue
            ep=c[i]; sl_d=3.0*a; sl=ep-direction*sl_d; tp=ep+direction*5.0*a
            qty=round((balance*RISK)/(ep*(sl_d/ep)),3); qty=min(qty,balance*0.5/ep)
            if qty<0.001: continue
            open_t={"i":i,"ts":df_1h.index[i],"dir":direction,"entry":ep,"sl":sl,"tp":tp,"qty":qty}
        return trades
    t=run_baseline(df_1h); tr,te=sc(t,split); pr("BB mean reversion (mevcut +28.2%)", tr, te)

if __name__=="__main__":
    main()
