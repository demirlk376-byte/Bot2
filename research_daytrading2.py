"""
research_daytrading2.py — BB dışı day trading stratejileri

Test edilen 4 yaklaşım:
  A) VWAP Mean Reversion  — fiyat VWAP'tan sapınca fade et
  B) Opening Range Breakout (ORB) — NY açılışı (14:00-14:30 UTC) range'i kır
  C) Asia Range Breakout — Asya seansı range'ini London/NY'da kır
  D) 5m Momentum (EMA cross) — trend yönünde git, mean reversion'a karşı

Dürüst metodoloji: 2025-05→12 = TRAIN, 2026-01→ = TEST.
Her iki periyotta tutarlı PF>1.10 → gerçek edge.

Run: python research_daytrading2.py
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr, bollinger_bands

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.02
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")


# ── veri yükleme ──────────────────────────────────────────────────────────────

def load_1m() -> pd.DataFrame:
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m

def to_tf(df_1m, rule):
    return df_1m.resample(rule).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


# ── sonuç formatı ─────────────────────────────────────────────────────────────

def score(trades, label):
    if not trades:
        return f"{label:<52}  NO TRADES"
    p   = np.array([t["pnl"] for t in trades])
    tr  = [t for t in trades if t["ts"] < SPLIT]
    te  = [t for t in trades if t["ts"] >= SPLIT]
    def _s(lst):
        if not lst: return "—"
        pp = np.array([t["pnl"] for t in lst])
        return f"W{(pp>0).mean():.0%} ${pp.sum():>+6.0f}"
    gp = p[p>0].sum() if (p>0).any() else 0
    gl = abs(p[p<0].sum()) if (p<0).any() else 1
    pf = gp/gl
    bal = np.cumsum(p)
    dd  = abs(((bal-np.maximum.accumulate(bal))/(BAL+np.maximum.accumulate(bal))).min())*100
    days = max((trades[-1]["ts"]-trades[0]["ts"]).days,1)
    return (f"{label:<52} {len(p):>4}t WR{(p>0).mean():.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f}({p.sum()/100:>+5.1f}%) DD{dd:.1f}% tpd={len(p)/days:.1f} "
            f"| TR {_s(tr)} | TE {_s(te)}")


# ── A: VWAP Mean Reversion ────────────────────────────────────────────────────

def strat_vwap_mr(df_5m, thresh_pct, sl_mult, rr, max_hold):
    """Price deviates thresh_pct% from rolling VWAP → fade."""
    typical = (df_5m["high"]+df_5m["low"]+df_5m["close"])/3
    win = 24*12  # 24h rolling window on 5m bars
    vwap_s = (typical*df_5m["volume"]).rolling(win).sum() / df_5m["volume"].rolling(win).sum()
    atr_s  = atr(df_5m["high"], df_5m["low"], df_5m["close"], 14)

    c=df_5m["close"].values; h=df_5m["high"].values; lo=df_5m["low"].values
    vw=vwap_s.values; at=atr_s.values; n=len(c)
    balance=BAL; open_t=None; trades=[]
    for i in range(win+20, n):
        if np.isnan(vw[i]) or np.isnan(at[i]) or at[i]<=0: continue
        if open_t is not None:
            d=open_t["dir"]; ep=None; reason=None; held=i-open_t["i"]
            if d==1:
                if lo[i]<=open_t["sl"]: ep,reason=open_t["sl"],"sl"
                elif h[i]>=open_t["tp"]: ep,reason=open_t["tp"],"tp"
                elif h[i]>=vw[i] and held>2: ep,reason=c[i],"vwap_touch"
            else:
                if h[i]>=open_t["sl"]: ep,reason=open_t["sl"],"sl"
                elif lo[i]<=open_t["tp"]: ep,reason=open_t["tp"],"tp"
                elif lo[i]<=vw[i] and held>2: ep,reason=c[i],"vwap_touch"
            if ep is None and held>=max_hold: ep,reason=c[i],"mh"
            if ep is not None:
                pnl=open_t["dir"]*(ep-open_t["entry"])*open_t["qty"]-(open_t["entry"]+ep)*open_t["qty"]*COST
                balance+=pnl
                trades.append({"ts":df_5m.index[i],"pnl":pnl})
                open_t=None
            continue
        dev=(c[i]-vw[i])/vw[i]*100
        direction=0
        if dev<-thresh_pct: direction=1
        elif dev>thresh_pct: direction=-1
        if direction==0: continue
        entry=c[i]; sl_d=sl_mult*at[i]
        sl=entry-direction*sl_d; tp=entry+direction*rr*sl_d
        qty=min(round(balance*RISK/(entry*sl_d/entry),3), balance*0.5/entry)
        if qty<0.001: continue
        open_t={"i":i,"dir":direction,"entry":entry,"sl":sl,"tp":tp,"qty":qty}
    return trades


# ── B: Opening Range Breakout (ORB) ───────────────────────────────────────────

def strat_orb(df_1m, orb_minutes, sl_pct, rr, max_hold_min, session_start_utc=14):
    """NY open ORB: first N minutes defines range, ONE breakout trade per day."""
    trades=[]; balance=BAL
    grouped=df_1m.groupby(df_1m.index.date)
    for date, day_df in grouped:
        session=day_df[day_df.index.hour>=session_start_utc]
        if len(session)<orb_minutes+10: continue
        orb=session.iloc[:orb_minutes]
        orb_high=orb["high"].max(); orb_low=orb["low"].min()
        orb_range=orb_high-orb_low
        if orb_range<=0: continue
        sl_d=orb_range*sl_pct
        after=session.iloc[orb_minutes:]
        open_t=None; entry_done=False  # one entry per day
        for i,(ts,row) in enumerate(after.iterrows()):
            if open_t is not None:
                d=open_t["dir"]; ep=None; entry=open_t["entry"]
                if d==1:
                    if row["low"]<=open_t["sl"]: ep=open_t["sl"]
                    elif row["high"]>=open_t["tp"]: ep=open_t["tp"]
                else:
                    if row["high"]>=open_t["sl"]: ep=open_t["sl"]
                    elif row["low"]<=open_t["tp"]: ep=open_t["tp"]
                if ep is None and i>=max_hold_min: ep=row["close"]
                if ep is not None:
                    pnl=d*(ep-entry)*open_t["qty"]-(entry+ep)*open_t["qty"]*COST
                    balance+=pnl
                    trades.append({"ts":ts,"pnl":pnl})
                    open_t=None
                continue
            if entry_done: continue  # only one trade per day
            close=row["close"]
            if close>orb_high:
                entry=orb_high; sl=entry-sl_d; tp=entry+rr*sl_d
                qty=min(round(balance*RISK/(entry*(sl_d/entry)),3),balance*0.5/entry)
                if qty>=0.001: open_t={"dir":1,"entry":entry,"sl":sl,"tp":tp,"qty":qty}; entry_done=True
            elif close<orb_low:
                entry=orb_low; sl=entry+sl_d; tp=entry-rr*sl_d
                qty=min(round(balance*RISK/(entry*(sl_d/entry)),3),balance*0.5/entry)
                if qty>=0.001: open_t={"dir":-1,"entry":entry,"sl":sl,"tp":tp,"qty":qty}; entry_done=True
        if open_t is not None:
            ep=after.iloc[-1]["close"]; entry=open_t["entry"]
            pnl=open_t["dir"]*(ep-entry)*open_t["qty"]-(entry+ep)*open_t["qty"]*COST
            balance+=pnl; trades.append({"ts":after.index[-1],"pnl":pnl})
    return trades


# ── C: Asia Range Breakout ────────────────────────────────────────────────────

def strat_asia_breakout(df_1m, sl_mult_atr, rr, max_hold_min):
    """Asia session (00-08 UTC) range → London/NY breakout, ONE trade per day."""
    trades=[]; balance=BAL
    df_5m=to_tf(df_1m,"5min")
    atr_s=atr(df_5m["high"],df_5m["low"],df_5m["close"],14)
    grouped=df_5m.groupby(df_5m.index.date)
    for date, day_df in grouped:
        asia=day_df[day_df.index.hour<8]
        rest=day_df[day_df.index.hour>=8]
        if len(asia)<10 or len(rest)<5: continue
        a_high=asia["high"].max(); a_low=asia["low"].min()
        if a_high<=a_low: continue
        at_val=atr_s.reindex(day_df.index).dropna()
        if len(at_val)==0: continue
        sl_d=sl_mult_atr*at_val.mean()
        open_t=None; entry_done=False
        for i,(ts,row) in enumerate(rest.iterrows()):
            if open_t is not None:
                d=open_t["dir"]; ep=None; entry=open_t["entry"]
                if d==1:
                    if row["low"]<=open_t["sl"]: ep=open_t["sl"]
                    elif row["high"]>=open_t["tp"]: ep=open_t["tp"]
                else:
                    if row["high"]>=open_t["sl"]: ep=open_t["sl"]
                    elif row["low"]<=open_t["tp"]: ep=open_t["tp"]
                if ep is None and i>=max_hold_min//5: ep=row["close"]
                if ep is not None:
                    pnl=d*(ep-entry)*open_t["qty"]-(entry+ep)*open_t["qty"]*COST
                    balance+=pnl; trades.append({"ts":ts,"pnl":pnl}); open_t=None
                continue
            if entry_done: continue
            c=row["close"]
            if c>a_high:
                entry=a_high; sl=entry-sl_d; tp=entry+rr*sl_d
                qty=min(round(balance*RISK/(entry*(sl_d/entry)),3),balance*0.5/entry)
                if qty>=0.001: open_t={"dir":1,"entry":entry,"sl":sl,"tp":tp,"qty":qty}; entry_done=True
            elif c<a_low:
                entry=a_low; sl=entry+sl_d; tp=entry-rr*sl_d
                qty=min(round(balance*RISK/(entry*(sl_d/entry)),3),balance*0.5/entry)
                if qty>=0.001: open_t={"dir":-1,"entry":entry,"sl":sl,"tp":tp,"qty":qty}; entry_done=True
        if open_t is not None:
            ep=rest.iloc[-1]["close"]; entry=open_t["entry"]
            pnl=open_t["dir"]*(ep-entry)*open_t["qty"]-(entry+ep)*open_t["qty"]*COST
            balance+=pnl; trades.append({"ts":rest.index[-1],"pnl":pnl})
    return trades


# ── D: 5m Momentum (EMA cross + trend) ───────────────────────────────────────

def strat_momentum(df_5m, fast, slow, sl_mult, rr, max_hold):
    """EMA fast/slow cross momentum — trend yönünde long/short."""
    ema_f=df_5m["close"].ewm(span=fast,adjust=False).mean()
    ema_s=df_5m["close"].ewm(span=slow,adjust=False).mean()
    atr_s=atr(df_5m["high"],df_5m["low"],df_5m["close"],14)
    c=df_5m["close"].values; h=df_5m["high"].values; lo=df_5m["low"].values
    ef=ema_f.values; es=ema_s.values; at=atr_s.values; n=len(c)
    balance=BAL; open_t=None; trades=[]; last_dir=0
    for i in range(slow+14+1, n):
        if np.isnan(at[i]) or at[i]<=0: continue
        if open_t is not None:
            d=open_t["dir"]; ep=None
            if d==1:
                if lo[i]<=open_t["sl"]: ep=open_t["sl"]
                elif h[i]>=open_t["tp"]: ep=open_t["tp"]
                elif ef[i]<es[i]: ep=c[i]  # exit on cross flip
            else:
                if h[i]>=open_t["sl"]: ep=open_t["sl"]
                elif lo[i]<=open_t["tp"]: ep=open_t["tp"]
                elif ef[i]>es[i]: ep=c[i]
            if ep is None and (i-open_t["i"])>=max_hold: ep=c[i]
            if ep is not None:
                pnl=d*(ep-open_t["entry"])*open_t["qty"]-(open_t["entry"]+ep)*open_t["qty"]*COST
                balance+=pnl; trades.append({"ts":df_5m.index[i],"pnl":pnl}); open_t=None
            continue
        # cross signal
        cross_up   = ef[i]>es[i] and ef[i-1]<=es[i-1]
        cross_down = ef[i]<es[i] and ef[i-1]>=es[i-1]
        if not (cross_up or cross_down): continue
        direction=1 if cross_up else -1
        if direction==last_dir: continue  # no double-entry
        entry=c[i]; sl_d=sl_mult*at[i]
        sl=entry-direction*sl_d; tp=entry+direction*rr*sl_d
        qty=min(round(balance*RISK/(entry*sl_d/entry),3),balance*0.5/entry)
        if qty<0.001: continue
        open_t={"i":i,"dir":direction,"entry":entry,"sl":sl,"tp":tp,"qty":qty}
        last_dir=direction
    return trades


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Veri yükleniyor…")
    m   = load_1m()
    df5 = to_tf(m, "5min")
    df15= to_tf(m, "15min")
    print(f"1m={len(m)} 5m={len(df5)} 15m={len(df15)}\n")

    print("="*120)
    print("REFERANS: 1h BB (doğrulanmış edge)")
    df1h=to_tf(m,"1h")
    from research_daytrading import backtest as bt1h
    ref=bt1h(df1h,20,2.0,3.0,5.0/3.0,48)
    print(score(ref,"1H BB(20,2) SL3ATR TP1.67 mh48"))

    # ── A: VWAP Mean Reversion ───────────────────────────────────────────────
    print("\n" + "="*120)
    print("A) VWAP MEAN REVERSION (5m)")
    print("-"*120)
    for thresh in [0.5, 1.0, 1.5, 2.0]:
        for sl in [1.5, 2.0, 3.0]:
            for rr in [1.5, 2.0, 3.0]:
                t=strat_vwap_mr(df5, thresh, sl, rr, max_hold=48)
                lbl=f"VWAP5m dev>{thresh:.1f}% SL{sl:.1f}ATR RR{rr:.1f}"
                print(score(t, lbl))

    # ── B: ORB ───────────────────────────────────────────────────────────────
    print("\n" + "="*120)
    print("B) OPENING RANGE BREAKOUT — NY açılışı 14:00 UTC")
    print("-"*120)
    for orb_min in [15, 30, 60]:
        for sl_pct in [0.5, 1.0, 1.5]:
            for rr in [1.5, 2.0, 3.0]:
                t=strat_orb(m, orb_min, sl_pct, rr, max_hold_min=240)
                lbl=f"ORB range={orb_min}min SL{sl_pct:.1f}×range RR{rr:.1f}"
                print(score(t, lbl))

    # ── C: Asia Range Breakout ────────────────────────────────────────────────
    print("\n" + "="*120)
    print("C) ASIA RANGE BREAKOUT (London/NY kırılımı)")
    print("-"*120)
    for sl in [1.0, 1.5, 2.0]:
        for rr in [1.5, 2.0, 3.0]:
            t=strat_asia_breakout(m, sl, rr, max_hold_min=240)
            lbl=f"Asia BO SL{sl:.1f}ATR RR{rr:.1f}"
            print(score(t, lbl))

    # ── D: Momentum ──────────────────────────────────────────────────────────
    print("\n" + "="*120)
    print("D) EMA MOMENTUM (5m cross)")
    print("-"*120)
    for fast,slow in [(9,21),(5,20),(3,10),(8,21),(10,50)]:
        for sl in [2.0, 3.0]:
            for rr in [1.5, 2.0, 3.0]:
                t=strat_momentum(df5, fast, slow, sl, rr, max_hold=72)
                lbl=f"EMA{fast}/{slow} SL{sl:.1f}ATR RR{rr:.1f}"
                print(score(t, lbl))

    print("\n" + "="*120)
    print("YORUM: PF>1.10 ve TR+TE ikisinde de pozitif → gerçek edge.")
    print("       1H referansı (PF 1.24, +%28) geçemeyen config → boş yere ekleme.")


if __name__ == "__main__":
    main()
