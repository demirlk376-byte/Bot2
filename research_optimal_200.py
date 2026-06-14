"""
research_optimal_200.py — Gerçek $200 hesap + aylık $100 ekleme simülasyonu

Önceki research_multi_capital.py $10K bakiyeyle çalışıp /50 ölçekledi. Ama
gerçek $200 hesapta şunlar devreye girer ve sonucu DEĞİŞTİRİR:
  • MIN_BTC_ORDER = 0.001 (MEXC minimum) — küçük pozisyonlar açılamaz
  • Margin kısıtı — 3 strateji aynı anda açıkken margin yetmeyebilir
  • Lot yuvarlama (3 ondalık)
  • Aylık $100 ekleme — bakiye büyür, sizing buna göre ölçeklenir

Bu script TEK paylaşılan bakiyeyle çalışır (gerçek hesap gibi), her stratejiye
ayrı pozisyon slotu verir (production main.py ile aynı), ve farklı sermaye
dağıtım modellerini karşılaştırır.

Amaç: en yüksek risk-getiri oranı (final bakiye vs maxDD) veren modeli bulmak.
"""
from __future__ import annotations

import glob
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST     = 0.0002      # tek yön fee (taker 0.01% + slippage payı)
LEVERAGE = 10
MIN_LOT  = 0.001
START    = 200.0
DEPOSIT  = 100.0       # her ay başı eklenecek
SPLIT    = pd.Timestamp("2026-01-01")

BB_SL = 3.0; BB_TP = 5.0; BB_MH = 48
ORB_RR = 2.0; ORB_MH = 6; ORB_HOUR = 14
ASIA_RR = 2.0; ASIA_SL_MULT = 1.0; ASIA_MH = 6


def load_all():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts","open","high","low","close","volume",
                      "ct","qv","count","tbv","tbqv","ign"]
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df, rule):
    return df.resample(rule).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def size_qty(mode, risk_pct, fixed_margin, balance, free_margin, ep, sl_dist):
    """Bir stratejinin pozisyon büyüklüğünü hesapla, margin kısıtına uy.
    mode='risk'  → bakiyenin %risk_pct'i kadar zarar riski
    mode='fixed' → sabit fixed_margin dolar margin (×leverage notional)
    Döner: (qty, margin_used) — margin yetmezse qty küçültülür, 0 olabilir.
    """
    if mode == "fixed":
        margin = min(fixed_margin, free_margin)
        if margin <= 0:
            return 0.0, 0.0
        qty = margin * LEVERAGE / ep
    else:  # risk
        risk_amt = balance * risk_pct
        qty = risk_amt / sl_dist if sl_dist > 0 else 0.0
        # margin gereği
        margin = qty * ep / LEVERAGE
        if margin > free_margin:
            qty = free_margin * LEVERAGE / ep
            margin = free_margin
    qty = round(qty, 3)
    if qty < MIN_LOT:
        return 0.0, 0.0
    margin = qty * ep / LEVERAGE
    if margin > free_margin + 1e-9:
        return 0.0, 0.0
    return qty, margin


def run(df_1h, sizing, deposits=True, compound=True):
    """
    sizing: dict — her strateji için ('mode', risk_pct, fixed_margin)
      örn {'bb':('risk',0.03,0), 'orb':('risk',0.015,0), 'asia':('risk',0.01,0)}
    Tek paylaşılan bakiye + margin kısıtı + aylık deposit.
    compound=False → pozisyon boyutu hep START ($200) bazlı (bileşik yok); böylece
      saf aylık edge ölçülür, bileşik patlaması rakamı bozmaz.
    Döner: trades listesi + equity zaman serisi + deposit toplamı.
    """
    close = df_1h["close"].values
    high  = df_1h["high"].values
    low_v = df_1h["low"].values
    vol   = df_1h["volume"].values
    idx   = df_1h.index

    upper_s, _, lower_s = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    bb_pos = ((df_1h["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan))

    atr_arr=atr_s.values; volma_arr=vol_ma.values; bb_arr=bb_pos.values
    n=len(close); warmup=60

    dates_arr=np.array([ts.date() for ts in idx])
    hours_arr=np.array([ts.hour for ts in idx])
    month_arr=np.array([ts.strftime("%Y-%m") for ts in idx])

    orb_by_date={}; asia_by_date={}
    for j in range(n):
        d=dates_arr[j]; h=hours_arr[j]
        if h==ORB_HOUR:
            orb_by_date[d]={"high":high[j],"low":low_v[j]}
        if h<8:
            if d not in asia_by_date:
                asia_by_date[d]={"high":high[j],"low":low_v[j],"count":1}
            else:
                asia_by_date[d]["high"]=max(asia_by_date[d]["high"],high[j])
                asia_by_date[d]["low"] =min(asia_by_date[d]["low"], low_v[j])
                asia_by_date[d]["count"]+=1

    balance=START
    used_margin=0.0
    total_deposited=START
    bb_open=orb_open=asia_open=None
    trades=[]; equity=[]
    orb_traded=set(); asia_traded=set()
    cur_month=None

    def free():
        return balance - used_margin

    for i in range(warmup,n):
        a=atr_arr[i]
        if np.isnan(a) or a<=0:
            equity.append((idx[i],balance)); continue

        # Aylık deposit (ay değişince)
        if deposits and month_arr[i]!=cur_month:
            if cur_month is not None:   # ilk ay START zaten yatırıldı
                balance+=DEPOSIT; total_deposited+=DEPOSIT
            cur_month=month_arr[i]

        cur_date=dates_arr[i]; cur_hour=hours_arr[i]
        size_bal = balance if compound else START  # non-compound → hep $200 bazlı
        bb_closed=orb_closed=asia_closed=False

        # ── pozisyon yönetimi (kapanışlar) ──
        for slot,pos in (("bb",bb_open),("orb",orb_open),("asia",asia_open)):
            if pos is None: continue
            d=pos["dir"]; entry=pos["entry"]; sl=pos["sl"]; tp=pos["tp"]
            qty=pos["qty"]; mh=pos["mh"]; held=i-pos["i"]
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
                balance+=pnl; used_margin-=pos["margin"]
                trades.append({"ts":idx[i],"pnl":pnl,"reason":reason,"strat":slot,"dir":d})
                if slot=="bb": bb_open=None; bb_closed=True
                elif slot=="orb": orb_open=None; orb_closed=True
                else: asia_open=None; asia_closed=True

        # ── BB sinyali ──
        if bb_open is None and not bb_closed:
            bpos=bb_arr[i]
            if not np.isnan(bpos) and (bpos<0.0 or bpos>1.0):
                direction=1 if bpos<0.0 else -1
                vm=volma_arr[i]
                if np.isnan(vm) or vol[i]>=vm:
                    ep=close[i]; sl_d=BB_SL*a
                    mode,rp,fm=sizing["bb"]
                    qty,margin=size_qty(mode,rp,fm,size_bal,free(),ep,sl_d)
                    if qty>0:
                        slp=ep-direction*sl_d; tpp=ep+direction*BB_TP*a
                        used_margin+=margin
                        bb_open={"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,
                                 "qty":qty,"margin":margin,"mh":BB_MH}

        # ── ORB sinyali (limit giriş) ──
        if orb_open is None and not orb_closed and cur_date not in orb_traded and cur_hour>ORB_HOUR:
            orb=orb_by_date.get(cur_date)
            if orb is not None:
                oh=orb["high"]; ol=orb["low"]; rng=oh-ol
                if rng>0:
                    cp=close[i]; direction=0
                    if cp>oh: direction=1
                    elif cp<ol: direction=-1
                    if direction!=0:
                        ep=oh if direction==1 else ol   # limit giriş
                        sl_d=rng
                        mode,rp,fm=sizing["orb"]
                        qty,margin=size_qty(mode,rp,fm,size_bal,free(),ep,sl_d)
                        if qty>0:
                            slp=ep-direction*sl_d; tpp=ep+direction*ORB_RR*sl_d
                            used_margin+=margin; orb_traded.add(cur_date)
                            orb_open={"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,
                                      "qty":qty,"margin":margin,"mh":ORB_MH}

        # ── Asia BO sinyali (limit giriş) ──
        if asia_open is None and not asia_closed and cur_date not in asia_traded and cur_hour>=8:
            asia=asia_by_date.get(cur_date)
            if asia is not None and asia["count"]>=4:
                ah=asia["high"]; al=asia["low"]
                cp=close[i]; direction=0
                if cp>ah: direction=1
                elif cp<al: direction=-1
                if direction!=0:
                    sl_d=ASIA_SL_MULT*a
                    ep=ah if direction==1 else al   # limit giriş
                    mode,rp,fm=sizing["asia"]
                    qty,margin=size_qty(mode,rp,fm,size_bal,free(),ep,sl_d)
                    if qty>0:
                        slp=ep-direction*sl_d; tpp=ep+direction*ASIA_RR*sl_d
                        used_margin+=margin; asia_traded.add(cur_date)
                        asia_open={"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,
                                   "qty":qty,"margin":margin,"mh":ASIA_MH}

        equity.append((idx[i],balance))

    return trades, equity, total_deposited


def stats(trades, equity, deposited):
    if not trades:
        return dict(n=0,wr=0,final=START,dd=0,pf=0,dep=deposited)
    p=np.array([t["pnl"] for t in trades])
    eq=np.array([e[1] for e in equity])
    pk=np.maximum.accumulate(eq)
    dd=((pk-eq)/pk).max()
    pos=p[p>0].sum(); neg=-p[p<0].sum()
    pf=pos/neg if neg>0 else float("inf")
    return dict(n=len(p),wr=(p>0).mean(),final=eq[-1],dd=dd,pf=pf,dep=deposited)


def main():
    print("Veri yükleniyor…")
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    print(f"Range: {df_1h.index[0].date()} → {df_1h.index[-1].date()} "
          f"({len(df_1h)} saat ≈ {len(df_1h)/24/30:.1f} ay)\n")

    # Test edilecek sermaye modelleri
    models = {
        "BB-only sabit margin $200 (mevcut)":
            {"bb":("fixed",0,200), "orb":("fixed",0,0), "asia":("fixed",0,0)},
        "BB-only %3 risk":
            {"bb":("risk",0.03,0), "orb":("fixed",0,0), "asia":("fixed",0,0)},
        "Araştırma oranı (BB3% ORB1.5% Asia1%)":
            {"bb":("risk",0.03,0), "orb":("risk",0.015,0), "asia":("risk",0.01,0)},
        "Orta agresif (BB5% ORB3% Asia2%)":
            {"bb":("risk",0.05,0), "orb":("risk",0.03,0), "asia":("risk",0.02,0)},
        "Agresif (BB8% ORB5% Asia3%)":
            {"bb":("risk",0.08,0), "orb":("risk",0.05,0), "asia":("risk",0.03,0)},
        "Çok agresif (BB12% ORB8% Asia5%)":
            {"bb":("risk",0.12,0), "orb":("risk",0.08,0), "asia":("risk",0.05,0)},
        "Sabit margin böl (BB$100 ORB$60 Asia$40)":
            {"bb":("fixed",0,100), "orb":("fixed",0,60), "asia":("fixed",0,40)},
    }

    for with_dep in (False, True):
        tag = "AYLIK +$100 EKLEME İLE" if with_dep else "EKLEME YOK (saf strateji getirisi)"
        print("="*100)
        print(f"  {tag}  —  başlangıç $200")
        print("="*100)
        print(f"{'Model':<42s} {'Trade':>6s} {'WR':>5s} {'PF':>5s} "
              f"{'maxDD':>7s} {'SonBakiye':>11s} {'Yatırılan':>10s} {'Net Kâr':>10s}")
        print("-"*100)
        for name,sizing in models.items():
            tr,eq,dep=run(df_1h, sizing, deposits=with_dep)
            s=stats(tr,eq,dep)
            net=s["final"]-s["dep"]
            print(f"{name:<42s} {s['n']:>6d} {s['wr']:>4.0%} {s['pf']:>5.2f} "
                  f"{s['dd']*100:>6.1f}% {s['final']:>10,.0f}$ {s['dep']:>9,.0f}$ "
                  f"{net:>+9,.0f}$")
        print()

    # En iyi modelin strateji bazlı + aylık dökümü (ekleme yok, saf getiri)
    print("="*100)
    best_sizing={"bb":("risk",0.05,0), "orb":("risk",0.03,0), "asia":("risk",0.02,0)}
    tr,eq,dep=run(df_1h, best_sizing, deposits=False)
    print("DETAY: Orta agresif (BB5% ORB3% Asia2%) — ekleme yok")
    print("-"*100)
    for strat in ["bb","orb","asia"]:
        tt=[t for t in tr if t["strat"]==strat]
        if tt:
            p=np.array([t["pnl"] for t in tt])
            pos=p[p>0].sum(); neg=-p[p<0].sum()
            pf=pos/neg if neg>0 else 999
            print(f"  {strat:<8s} {len(tt):>4d}t  WR{(p>0).mean():>3.0%}  "
                  f"PF{pf:.2f}  net ${p.sum():>+8.0f}")
    # aylık
    print("\n  Aylık (Orta agresif, ekleme yok):")
    months=sorted(set(t["ts"].strftime("%Y-%m") for t in tr))
    for mo in months:
        mt=[t for t in tr if t["ts"].strftime("%Y-%m")==mo]
        pnl=sum(t["pnl"] for t in mt)
        mark="🔴" if pnl<0 else "🟢"
        print(f"    {mo}: {pnl:>+8.0f}$  ({len(mt):>2d}t) {mark}")


if __name__=="__main__":
    main()
