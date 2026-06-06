"""
DERİN SL ANALİZİ — Neden stop-loss vuruyor?

İki farklı SL türü var:
  A) "Haklı SL": Price hit SL then CONTINUED lower — trend devam etti,
     giriş yanlış yerdi. Bu kaçınılabilir.
  B) "Haksız SL": Price hit SL but then RECOVERED above our entry — noise.
     Daha geniş SL yardım eder ama o da test edildi, işe yaramıyor.

Bu script şunları analiz eder:
  1. SL sonrası 5-20 candle'da fiyat ne yaptı? (A mı B mi)
  2. Entry öncesi kaç peş peşe bearish/bullish mum var?
  3. SL streak pattern — art arda SL sonrası bir sonraki işlem?
  4. SL öncesi fiyat hızlanması (momentum) var mı?
  5. Hangi saat diliminde SL daha çok vuruyor?
  6. Streak-based cool-down: art arda 2+ SL sonrası X mum bekle
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

def run_full(df_1h):
    """Run the canonical strategy (vol filter + maker cost) and return rich trade records."""
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
                gross=d*(ep-entry)*qty
                fees=(entry+ep)*qty*COST
                net=gross-fees
                balance+=net
                t=dict(open_t)
                t.update({"exit_i":i,"exit":ep,"pnl":net,"reason":reason,"held":held})
                trades.append(t)
                open_t=None
            continue

        bpos=bb_pos[i]
        if np.isnan(bpos): continue
        if not (bpos<0 or bpos>1): continue
        direction=1 if bpos<0 else -1
        if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue

        ep=close[i]; sl_d=SL_M*a; tp_d=TP_M*a
        slp=ep-direction*sl_d; tpp=ep+direction*tp_d
        qty=round((balance*RISK)/(ep*(sl_d/ep)),3)
        qty=min(qty,balance*0.5/ep)
        if qty<0.001: continue

        # entry features
        consec_bearish=0  # consecutive bearish candles before entry (for longs)
        for j in range(i-1,max(i-10,-1),-1):
            if direction==1 and close[j]<close[j-1]: consec_bearish+=1
            elif direction==-1 and close[j]>close[j-1]: consec_bearish+=1
            else: break

        # price velocity: % change over last 5 candles (direction-adjusted)
        vel5=(close[i]-close[i-5])/close[i-5]*direction if i>=5 else 0

        # ATR rank
        atr_hist=atr_s.iloc[max(0,i-50):i]
        atr_rank=float(a/atr_hist.mean()) if len(atr_hist)>5 else 1.0

        open_t={"i":i,"entry_i":i,"ts":df_1h.index[i],"dir":direction,
                "entry":ep,"sl":slp,"tp":tpp,"qty":qty,
                "consec":consec_bearish,"vel5":vel5,"atr_rank":atr_rank,
                "bb_pos":bpos,"hour":df_1h.index[i].hour}

    return trades, close, high, low, df_1h.index

def analyze_post_sl(trades, close, high, low, idx):
    """For SL hits: check how far price went & if it recovered."""
    sl_trades = [t for t in trades if t["reason"]=="sl"]
    win_trades = [t for t in trades if t["reason"] in ("tp","mh") and t["pnl"]>0]

    print(f"\n{'='*70}")
    print(f"  SL HİT SONRASI ANALİZ ({len(sl_trades)} SL, {len(win_trades)} kazanç)")
    print(f"{'='*70}")

    # For each SL hit, how far did price go and did it recover?
    recovered_5  = 0  # price returned to entry within 5 candles
    recovered_10 = 0
    recovered_20 = 0
    continued    = 0  # price went further by 1xSL_dist
    n=len(close)

    sl_continue_depths=[]  # how far (in ATR units) price went past SL after hitting it

    for t in sl_trades:
        ei=t["exit_i"]; d=t["dir"]; entry=t["entry"]; sl=t["sl"]
        sl_dist=abs(entry-sl)
        # look ahead
        look_end=min(ei+21,n)
        future_close=close[ei+1:look_end]
        future_low=low[ei+1:look_end]
        future_high=high[ei+1:look_end]
        if len(future_close)==0: continue

        if d==1:  # long trade
            # recovered: price got back above entry
            rec_5  = any(future_close[:5] >entry)  if len(future_close)>=5  else False
            rec_10 = any(future_close[:10]>entry)  if len(future_close)>=10 else False
            rec_20 = any(future_close[:20]>entry)  if len(future_close)>=20 else False
            # continued: price went 1xSL below our SL
            cont = any(future_low < sl - sl_dist)
            # max depth below SL
            depths=[sl-l for l in future_low if l<sl]
            max_depth=max(depths)/sl_dist if depths else 0
        else:  # short trade
            rec_5  = any(future_close[:5] <entry)  if len(future_close)>=5  else False
            rec_10 = any(future_close[:10]<entry)  if len(future_close)>=10 else False
            rec_20 = any(future_close[:20]<entry)  if len(future_close)>=20 else False
            cont = any(future_high > sl + sl_dist)
            depths=[h-sl for h in future_high if h>sl]
            max_depth=max(depths)/sl_dist if depths else 0

        if rec_5:  recovered_5+=1
        if rec_10: recovered_10+=1
        if rec_20: recovered_20+=1
        if cont:   continued+=1
        sl_continue_depths.append(max_depth)

    total=len(sl_trades)
    print(f"\n  SL sonrası {total} işlemde fiyat ne yaptı:")
    print(f"    5  mum içinde entry'ye döndü  : {recovered_5:>3d}/{total} = {recovered_5/total:.0%}  (SL haksız)")
    print(f"    10 mum içinde entry'ye döndü  : {recovered_10:>3d}/{total} = {recovered_10/total:.0%}")
    print(f"    20 mum içinde entry'ye döndü  : {recovered_20:>3d}/{total} = {recovered_20/total:.0%}")
    print(f"    SL sonrası 1xSL daha devam etti: {continued:>3d}/{total} = {continued/total:.0%}  (SL haklı)")
    print(f"    Ortalama SL sonrası derinlik   : {np.mean(sl_continue_depths):.2f}xSL")
    print(f"    Medyan  SL sonrası derinlik    : {np.median(sl_continue_depths):.2f}xSL")

    truly_bad = sum(1 for d in sl_continue_depths if d>1.0)
    print(f"\n  → {truly_bad}/{total} ({truly_bad/total:.0%}) SL 'trend devamı' — gerçekten kaçınılabilir")
    print(f"  → {total-truly_bad}/{total} ({(total-truly_bad)/total:.0%}) SL 'gürültü' — fiyat sonunda döndü")

def analyze_entry_features(trades):
    sl_t = [t for t in trades if t["reason"]=="sl"]
    win_t = [t for t in trades if t["reason"] in ("tp","mh") and t["pnl"]>0]

    print(f"\n{'='*70}")
    print(f"  GİRİŞ ÖNCESİ MOMENTUM ANALİZİ")
    print(f"{'='*70}")

    for label, grp in [("SL hits", sl_t), ("Wins", win_t)]:
        if not grp: continue
        consec = [t["consec"] for t in grp]
        vel5 = [t["vel5"]*100 for t in grp]
        atr_rank = [t["atr_rank"] for t in grp]
        print(f"\n  {label} ({len(grp)}t):")
        print(f"    Peş peşe yön mumları: mean={np.mean(consec):.2f} median={np.median(consec):.0f}")
        print(f"    5-mum hız (% yön-adjusted): mean={np.mean(vel5):.2f}% median={np.median(vel5):.2f}%")
        print(f"    ATR rank (1=normal): mean={np.mean(atr_rank):.2f}")

    # Distribution by consecutive candles
    print(f"\n  WR by peş peşe yön mumu sayısı:")
    for n_consec in range(0, 8):
        sl_n = sum(1 for t in sl_t if t["consec"]==n_consec)
        wn_n = sum(1 for t in win_t if t["consec"]==n_consec)
        tot  = sl_n+wn_n
        if tot>=3:
            wr=wn_n/tot
            bar="█"*int(wr*20)
            print(f"    {n_consec} mum: {tot:>3d}t  WR {wr:>4.0%}  {bar}")

def analyze_streaks(trades):
    """Streak analysis: after N consecutive SL hits, what's the next trade outcome?"""
    print(f"\n{'='*70}")
    print(f"  STREAK ANALİZİ — Peş peşe SL sonrası")
    print(f"{'='*70}")

    results=[1 if t["pnl"]>0 else 0 for t in trades]
    reasons=[t["reason"] for t in trades]

    # After 1, 2, 3 consecutive losses, what's win rate of next trade?
    for streak in [1,2,3]:
        next_wins=[]; next_losses=[]
        for i in range(streak, len(results)):
            if all(reasons[j]=="sl" for j in range(i-streak,i)):
                if i<len(results):
                    if results[i]==1: next_wins.append(i)
                    else: next_losses.append(i)
        tot=len(next_wins)+len(next_losses)
        if tot>0:
            wr=len(next_wins)/tot
            print(f"  {streak} peş peşe SL sonrası: {tot} durum → WR {wr:.0%} "
                  f"({len(next_wins)} kazanç, {len(next_losses)} kayıp)")

    print(f"\n  WR genel: {sum(results)/len(results):.0%}")

def test_cooldown(df_1h, trades_ref):
    """Test: after N consecutive SL hits on same side, skip next M candles."""
    print(f"\n{'='*70}")
    print(f"  COOLDOWN TESTİ — Peş peşe SL sonrası bekleme")
    print(f"{'='*70}")

    close=df_1h["close"].values; high=df_1h["high"].values; low=df_1h["low"].values
    vol=df_1h["volume"].values
    upper,middle,lower=bollinger_bands(df_1h["close"],20,2.0)
    atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
    vol_ma=df_1h["volume"].rolling(20).mean().values
    bb_pos=((df_1h["close"]-lower)/(upper-lower).replace(0,np.nan)).values
    split=pd.Timestamp("2026-01-01")

    def run_with_cooldown(sl_streak_limit, cooldown_candles):
        n=len(close); warmup=60
        balance=BAL; open_t=None; trades=[]
        consecutive_sl=0; cooldown_remaining=0

        for i in range(warmup,n):
            a=atr_s.iloc[i]
            if np.isnan(a) or a<=0: continue

            if cooldown_remaining>0:
                cooldown_remaining-=1

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
                    gross=d*(ep-entry)*qty; fees=(entry+ep)*qty*COST; net=gross-fees
                    balance+=net
                    trades.append({"ts":df_1h.index[i],"pnl":net,"reason":reason})
                    if reason=="sl":
                        consecutive_sl+=1
                        if consecutive_sl>=sl_streak_limit:
                            cooldown_remaining=cooldown_candles
                            consecutive_sl=0
                    else:
                        consecutive_sl=0
                    open_t=None
                continue

            if cooldown_remaining>0: continue

            bpos=bb_pos[i]
            if np.isnan(bpos): continue
            if not (bpos<0 or bpos>1): continue
            direction=1 if bpos<0 else -1
            if not np.isnan(vol_ma[i]) and vol[i]<vol_ma[i]: continue

            ep=close[i]; sl_d=SL_M*a; tp_d=TP_M*a
            slp=ep-direction*sl_d; tpp=ep+direction*tp_d
            qty=round((balance*RISK)/(ep*(sl_d/ep)),3)
            qty=min(qty,balance*0.5/ep)
            if qty<0.001: continue
            open_t={"i":i,"ts":df_1h.index[i],"dir":direction,
                    "entry":ep,"sl":slp,"tp":tpp,"qty":qty}

        return trades

    print(f"  {'Variant':<40s}  ALL  |  TRAIN  |  TEST  | maxDD")
    for streak_lim, cooldown in [(99,0),(2,6),(2,12),(2,24),(3,6),(3,12),(3,24)]:
        trades=run_with_cooldown(streak_lim, cooldown)
        tr=[t for t in trades if t["ts"]<split]
        te=[t for t in trades if t["ts"]>=split]
        def sc(tt):
            if not tt: return dict(n=0,wr=0,pnl=0,dd=0)
            p=np.array([x["pnl"] for x in tt])
            eq=BAL+np.cumsum(p); pk=np.maximum.accumulate(eq)
            return dict(n=len(p),wr=(p>0).mean(),pnl=p.sum(),dd=((pk-eq)/pk).max())
        tr_s=sc(tr); te_s=sc(te)
        tot=tr_s["pnl"]+te_s["pnl"]
        lbl=f"cooldown yok" if cooldown==0 else f"streak≥{streak_lim} → {cooldown}mum bekle"
        print(f"  {lbl:<40s}  {tr_s['n']+te_s['n']:>3d}t {tot/100:>+5.1f}%  |  "
              f"TRAIN WR{tr_s['wr']:>3.0%} ${tr_s['pnl']:>+7.0f}  |  "
              f"TEST WR{te_s['wr']:>3.0%} ${te_s['pnl']:>+7.0f}  |  "
              f"maxDD {max(tr_s['dd'],te_s['dd'])*100:.1f}%")

def analyze_hours(trades):
    """Hour-of-day win rate analysis (UTC)."""
    print(f"\n{'='*70}")
    print(f"  SAATLIK WR ANALİZİ (UTC)")
    print(f"{'='*70}")
    by_hour={}
    for t in trades:
        h=t["hour"]; by_hour.setdefault(h,{"sl":0,"win":0})
        if t["reason"]=="sl": by_hour[h]["sl"]+=1
        elif t["pnl"]>0: by_hour[h]["win"]+=1
    print(f"  {'Saat':>5s}  {'İşlem':>6s}  {'WR':>6s}  Bar")
    for h in sorted(by_hour):
        d=by_hour[h]; tot=d["sl"]+d["win"]
        if tot<3: continue
        wr=d["win"]/tot
        bar="█"*int(wr*20)
        print(f"  {h:>3d}:00   {tot:>4d}t    {wr:>4.0%}   {bar}")

def main():
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    trades,close,high,low,idx=run_full(df_1h)

    n_sl=sum(1 for t in trades if t["reason"]=="sl")
    n_tp=sum(1 for t in trades if t["reason"]=="tp")
    n_mh=sum(1 for t in trades if t["reason"]=="mh")
    print(f"Toplam: {len(trades)}t | SL={n_sl} | TP={n_tp} | maxHold={n_mh}")

    analyze_post_sl(trades, close, high, low, idx)
    analyze_entry_features(trades)
    analyze_streaks(trades)
    analyze_hours(trades)
    test_cooldown(df_1h, trades)

if __name__=="__main__":
    main()
