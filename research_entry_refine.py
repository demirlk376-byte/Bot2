"""
Giriş kalitesini artırmak için 3 hipotez:
1. Sonraki mum onayı: BB sinyali ateşlendi → bir sonraki mumun yönü onaylarsa gir
2. Mum formasyonları: Hammer (uzun alt fitil) / Shooting star (uzun üst fitil) onayı
3. Yapısal SL: ATR yerine son swing low/high'a dayalı stop
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

def run(df_1h, mode="baseline", sl_mode="atr", sl_mult=SL_M, confirm_candles=1):
    """
    mode: 'baseline' | 'next_candle' (1 sonraki mumun yönü) | 'candle_pattern' (hammer/ss)
          | 'next_N' (N mum içinde ilk reversal mumu)
    sl_mode: 'atr' | 'structural' (swing low/high)
    """
    o=df_1h["open"].values; c=df_1h["close"].values
    h=df_1h["high"].values; lo=df_1h["low"].values; vol=df_1h["volume"].values
    upper,middle,lower=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma=df_1h["volume"].rolling(20).mean().values
    bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values
    n=len(c); warmup=60
    balance=BAL; open_t=None; trades=[]
    pending=None  # (direction, entry_i, sl, tp, qty) waiting for next candle confirm

    for i in range(warmup,n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue

        # --- Handle pending next-candle entries ---
        if pending is not None:
            direction, orig_i, orig_entry, sl, tp, qty, wait_until = pending
            # Check confirmation in current candle
            confirmed = False
            if mode == "next_candle":
                # Mum yön onayı: uzun için bullish mum (close > open), kısa için bearish
                if direction == 1 and c[i] > o[i]: confirmed = True
                elif direction == -1 and c[i] < o[i]: confirmed = True
            elif mode == "next_N":
                if direction == 1 and c[i] > o[i]: confirmed = True
                elif direction == -1 and c[i] < o[i]: confirmed = True

            if confirmed:
                ep = c[i]  # enter at close of confirmation candle
                sl_d = sl_mult * a
                if sl_mode == "structural":
                    lookback = 10
                    if direction == 1:
                        sl = min(lo[max(0,i-lookback):i+1]) - 0.1*a
                    else:
                        sl = max(h[max(0,i-lookback):i+1]) + 0.1*a
                    tp = ep + direction * abs(ep - sl) * (TP_M/SL_M)
                else:
                    sl = ep - direction * sl_d
                    tp = ep + direction * TP_M * a
                qty = round((balance*RISK)/(ep*(abs(ep-sl)/ep)),3)
                qty = min(qty, balance*0.5/ep)
                if qty >= 0.001:
                    open_t = {"i":i,"ts":df_1h.index[i],"dir":direction,"entry":ep,"sl":sl,"tp":tp,"qty":qty}
                pending = None
            elif i >= wait_until:
                pending = None  # timed out, skip trade
            continue

        # --- Manage open trade ---
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

        # --- Look for signal ---
        bpos=bb_pos[i]
        if np.isnan(bpos) or not (bpos<0 or bpos>1): continue
        direction=1 if bpos<0 else -1
        if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue

        # Mum formasyon onayı
        if mode == "candle_pattern":
            body = abs(c[i] - o[i])
            candle_range = h[i] - lo[i]
            if candle_range < 1e-6: continue
            if direction == 1:  # long → hammer mumu
                lower_wick = min(c[i],o[i]) - lo[i]
                if lower_wick < 1.5 * body: continue  # alt fitil yetersiz
                if c[i] < (h[i]+lo[i])/2: continue   # kapanış alt yarıda
            else:  # short → shooting star
                upper_wick = h[i] - max(c[i],o[i])
                if upper_wick < 1.5 * body: continue
                if c[i] > (h[i]+lo[i])/2: continue

        # Bir sonraki mum onayı modu
        if mode in ("next_candle", "next_N"):
            a_now = a; ep_sig = c[i]
            sl_d = sl_mult * a_now
            pending = (direction, i, ep_sig, ep_sig - direction*sl_d,
                       ep_sig + direction*TP_M*a_now,
                       round((balance*RISK)/(ep_sig*(sl_d/ep_sig)),3),
                       i + confirm_candles)  # wait_until
            continue

        # Baseline giriş (şu anki mum kapanışında)
        ep=c[i]; sl_d=sl_mult*a; tp_d=TP_M*a
        if sl_mode == "structural":
            lookback = 10
            if direction == 1:
                sl = min(lo[max(0,i-lookback):i+1]) - 0.1*a
            else:
                sl = max(h[max(0,i-lookback):i+1]) + 0.1*a
            tp = ep + direction * abs(ep - sl) * (TP_M/SL_M)
        else:
            sl = ep - direction*sl_d
            tp = ep + direction*tp_d
        qty=round((balance*RISK)/(ep*(abs(ep-sl)/ep)),3)
        qty=min(qty,balance*0.5/ep)
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
    print("GİRİŞ KALİTESİ — Sonraki mum onayı | Mum formasyonu | Yapısal SL")
    print("="*115)

    configs=[
        ("BASELINE (vol+maker+%3 risk)",         "baseline",      "atr",        SL_M, 1),
        ("Hammer/Shooting star onayı",           "candle_pattern","atr",        SL_M, 1),
        ("Sonraki mum onayı (1 mum bekle)",      "next_candle",   "atr",        SL_M, 1),
        ("Sonraki mum onayı (2 mum bekle)",      "next_N",        "atr",        SL_M, 2),
        ("Sonraki mum onayı (3 mum bekle)",      "next_N",        "atr",        SL_M, 3),
        ("Yapısal SL (swing low/high, N=10)",    "baseline",      "structural", SL_M, 1),
        ("Yapısal SL + hammer onayı",            "candle_pattern","structural", SL_M, 1),
        ("Sonraki mum + Yapısal SL",             "next_candle",   "structural", SL_M, 1),
    ]
    for label, mode, sl_mode, sl_mult, nc in configs:
        trades=run(df_1h, mode=mode, sl_mode=sl_mode, sl_mult=sl_mult, confirm_candles=nc)
        tr,te=sc(trades,split); pr(label,tr,te)

    # SL hit reason breakdown for baseline vs next_candle
    print()
    print("--- SL çarpma oranları: BASELINE vs SONRAKI MUM ONAY ---")
    for label, mode in [("BASELINE", "baseline"), ("Sonraki Mum Onayı", "next_candle")]:
        trades=run(df_1h, mode=mode)
        reasons={}
        for t in trades: reasons[t["reason"]]=reasons.get(t["reason"],0)+1
        n=len(trades)
        print(f"  {label}: {n}t  SL={reasons.get('sl',0)/n:.0%}  TP={reasons.get('tp',0)/n:.0%}  MH={reasons.get('mh',0)/n:.0%}")

if __name__=="__main__":
    main()
