"""
research_multi_capital.py — Ayrı sermaye dilimleri + limit giriş

Önceki combined backtest 2 sorunla başarısız oldu:
  1) MAX_POSITIONS=1 → stratejiler birbirini bloke etti
  2) 1H barda close fiyatıyla giriş → ORB/Asia için çok kaymalı

Çözümler:
  1) Her stratejiye AYRI sermaye dilimi → aynı anda birden fazla pozisyon açık olabilir
  2) ORB/Asia için limit giriş simülasyonu → kırılım seviyesinde doldur (close değil)

Sermaye dağılımı ($10K backtest, gerçekte $200):
  BB    : RISK=0.030 (~%3 risk)  → serbest sinyaller, 48h
  ORB   : RISK=0.015 (~%1.5)     → 1/gün, limit giriş, 6h
  Asia  : RISK=0.010 (~%1.0)     → 1/gün, limit giriş, 6h

  Toplam risk açık pozisyon başına max: %5.5

Not: Pozisyonlar birbirinden bağımsız — BB açıkken ORB de açılabilir.
"""
from __future__ import annotations

import glob
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as adx_fn

COST      = 0.0002
BAL       = 10_000.0
SPLIT     = pd.Timestamp("2026-01-01")

# Her stratejinin risk parametresi
BB_RISK   = 0.030; BB_SL  = 3.0; BB_TP  = 5.0; BB_MH   = 48
ORB_RISK  = 0.015; ORB_RR = 2.0; ORB_MH = 6;  ORB_HOUR = 14
ASIA_RISK = 0.010; ASIA_RR = 2.0; ASIA_SL_MULT = 1.0; ASIA_MH = 6


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


def run(df_1h, separate_capital=True, limit_entry_orb=True, limit_entry_asia=True):
    """
    separate_capital  : True → her strateji kendi "hesabından" trade eder
                        False → tek pozisyon (eski davranış)
    limit_entry_orb   : True → ORB girişi close değil, orb_high/low'da (limit)
    limit_entry_asia  : True → Asia girişi close değil, asia_high/low'da (limit)
    """
    close  = df_1h["close"].values
    high   = df_1h["high"].values
    low_v  = df_1h["low"].values
    vol    = df_1h["volume"].values
    idx    = df_1h.index

    upper_s, _, lower_s = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s   = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma  = df_1h["volume"].rolling(20).mean()
    bb_pos  = ((df_1h["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan))

    atr_arr   = atr_s.values
    volma_arr = vol_ma.values
    bb_arr    = bb_pos.values

    n = len(close); warmup = 60

    # Precompute dates/hours to avoid repeated computation inside loop
    dates_arr = np.array([ts.date() for ts in idx])
    hours_arr = np.array([ts.hour for ts in idx])

    # Precompute ORB range per date (14:00 UTC candle)
    orb_by_date: dict[date, dict] = {}
    asia_by_date: dict[date, dict] = {}
    for j in range(n):
        d = dates_arr[j]
        h = hours_arr[j]
        if h == ORB_HOUR:
            orb_by_date[d] = {"high": high[j], "low": low_v[j]}
        if h < 8:
            if d not in asia_by_date:
                asia_by_date[d] = {"high": high[j], "low": low_v[j], "count": 1}
            else:
                asia_by_date[d]["high"] = max(asia_by_date[d]["high"], high[j])
                asia_by_date[d]["low"]  = min(asia_by_date[d]["low"],  low_v[j])
                asia_by_date[d]["count"] += 1

    # Ayrı pozisyon takibi
    bb_open    = None   # BB pozisyonu
    orb_open   = None   # ORB pozisyonu
    asia_open  = None   # Asia BO pozisyonu

    # Bakiye takibi (separate_capital=False ise hepsi aynı)
    bal_bb   = BAL
    bal_orb  = BAL
    bal_asia = BAL

    trades = []

    orb_traded:  set[date] = set()
    asia_traded: set[date] = set()

    for i in range(warmup, n):
        a = atr_arr[i]
        if np.isnan(a) or a <= 0:
            continue

        cur_date = idx[i].date()
        cur_hour = idx[i].hour

        # Aynı barda kapanıp yeniden açılmayı önle
        bb_closed   = False
        orb_closed  = False
        asia_closed = False

        # ─── BB pozisyonu yönet ──────────────────────────────────────────────
        if bb_open is not None:
            d=bb_open["dir"]; entry=bb_open["entry"]
            sl=bb_open["sl"]; tp=bb_open["tp"]
            qty=bb_open["qty"]; held=i-bb_open["i"]
            ep=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep,reason=sl,"sl"
                elif high[i]>=tp: ep,reason=tp,"tp"
            else:
                if high[i]>=sl: ep,reason=sl,"sl"
                elif low_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=BB_MH: ep,reason=close[i],"mh"
            if ep is not None:
                pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST
                bal_bb+=pnl
                trades.append({"ts":idx[i],"pnl":pnl,"reason":reason,"strat":"bb","dir":d})
                bb_open=None; bb_closed=True

        # ─── ORB pozisyonu yönet ─────────────────────────────────────────────
        if orb_open is not None:
            d=orb_open["dir"]; entry=orb_open["entry"]
            sl=orb_open["sl"]; tp=orb_open["tp"]
            qty=orb_open["qty"]; held=i-orb_open["i"]
            ep=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep,reason=sl,"sl"
                elif high[i]>=tp: ep,reason=tp,"tp"
            else:
                if high[i]>=sl: ep,reason=sl,"sl"
                elif low_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=ORB_MH: ep,reason=close[i],"mh"
            if ep is not None:
                pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST
                bal_orb+=pnl
                trades.append({"ts":idx[i],"pnl":pnl,"reason":reason,"strat":"orb","dir":d})
                orb_open=None; orb_closed=True

        # ─── Asia pozisyonu yönet ────────────────────────────────────────────
        if asia_open is not None:
            d=asia_open["dir"]; entry=asia_open["entry"]
            sl=asia_open["sl"]; tp=asia_open["tp"]
            qty=asia_open["qty"]; held=i-asia_open["i"]
            ep=None; reason=None
            if d==1:
                if low_v[i]<=sl: ep,reason=sl,"sl"
                elif high[i]>=tp: ep,reason=tp,"tp"
            else:
                if high[i]>=sl: ep,reason=sl,"sl"
                elif low_v[i]<=tp: ep,reason=tp,"tp"
            if ep is None and held>=ASIA_MH: ep,reason=close[i],"mh"
            if ep is not None:
                pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST
                bal_asia+=pnl
                trades.append({"ts":idx[i],"pnl":pnl,"reason":reason,"strat":"asia_bo","dir":d})
                asia_open=None; asia_closed=True

        # ─── 1. BB sinyali ───────────────────────────────────────────────────
        if bb_open is None and not bb_closed:
            bpos=bb_arr[i]
            if not np.isnan(bpos) and (bpos<0.0 or bpos>1.0):
                direction=1 if bpos<0.0 else -1
                vm=volma_arr[i]
                if np.isnan(vm) or vol[i]>=vm:
                    ep=close[i]; sl_d=BB_SL*a
                    slp=ep-direction*sl_d; tpp=ep+direction*BB_TP*a
                    qty=round((bal_bb*BB_RISK)/(ep*sl_d/ep),3)
                    qty=min(qty, bal_bb*0.5/ep)
                    if qty>=0.001:
                        bb_open={"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}

        # ─── 2. ORB sinyali (limit giriş) ────────────────────────────────────
        if orb_open is None and not orb_closed and cur_date not in orb_traded and cur_hour > ORB_HOUR:
            orb = orb_by_date.get(cur_date)
            if orb is not None:
                orb_high = orb["high"]; orb_low = orb["low"]
                orb_range = orb_high - orb_low
                if orb_range > 0:
                    cp = close[i]; direction = 0
                    if cp > orb_high:  direction = 1
                    elif cp < orb_low: direction = -1
                    if direction != 0:
                        ep = (orb_high if direction==1 else orb_low) if limit_entry_orb else cp
                        sl_d = orb_range
                        slp = ep - direction * sl_d
                        tpp = ep + direction * ORB_RR * sl_d
                        qty = round((bal_orb * ORB_RISK) / (ep * sl_d / ep), 3)
                        qty = min(qty, bal_orb * 0.5 / ep)
                        if qty >= 0.001:
                            orb_traded.add(cur_date)
                            orb_open = {"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}

        # ─── 3. Asia BO sinyali (limit giriş) ────────────────────────────────
        if asia_open is None and not asia_closed and cur_date not in asia_traded and cur_hour >= 8:
            asia = asia_by_date.get(cur_date)
            if asia is not None and asia["count"] >= 4:
                asia_high = asia["high"]; asia_low = asia["low"]
                cp = close[i]; direction = 0
                if cp > asia_high:  direction = 1
                elif cp < asia_low: direction = -1
                if direction != 0:
                    sl_d = ASIA_SL_MULT * a
                    ep = (asia_high if direction==1 else asia_low) if limit_entry_asia else cp
                    slp = ep - direction * sl_d
                    tpp = ep + direction * ASIA_RR * sl_d
                    qty = round((bal_asia * ASIA_RISK) / (ep * sl_d / ep), 3)
                    qty = min(qty, bal_asia * 0.5 / ep)
                    if qty >= 0.001:
                        asia_traded.add(cur_date)
                        asia_open = {"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}

    return trades


def score(trades, split=SPLIT):
    tr=[t for t in trades if t["ts"]<split]
    te=[t for t in trades if t["ts"]>=split]
    def _s(tt):
        if not tt: return dict(n=0,wr=0,pnl=0,pf=0,dd=0)
        p=np.array([t["pnl"] for t in tt])
        pos=p[p>0].sum(); neg=-p[p<0].sum()
        pf=pos/neg if neg>0 else float("inf")
        eq=BAL+np.cumsum(p); pk=np.maximum.accumulate(eq)
        return dict(n=len(p),wr=(p>0).mean(),pnl=p.sum(),pf=pf,dd=((pk-eq)/pk).max())
    return _s(tr),_s(te)


def pr(label, tr, te):
    tot=tr["pnl"]+te["pnl"]
    print(f"{label:<50s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  "
          f"TEST {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")


def monthly_table(trades_dict):
    all_months = sorted(set(
        t["ts"].strftime("%Y-%m")
        for trades in trades_dict.values()
        for t in trades
    ))
    labels = list(trades_dict.keys())
    col = 10

    # Header
    header = f"{'Ay':<10s}"
    for lbl in labels:
        header += f"  {lbl[:col]:>{col}s}"
    print(header)

    neg_counts = {lbl: 0 for lbl in labels}
    for mo in all_months:
        row = f"  {mo:<8s}"
        for lbl in labels:
            trades = trades_dict[lbl]
            month_t = [t for t in trades if t["ts"].strftime("%Y-%m")==mo]
            p = sum(t["pnl"] for t in month_t)
            row += f"  {p:>+8.0f}({len(month_t):>2d}t)"
            if p < 0:
                neg_counts[lbl] += 1
        print(row)
    print()
    neg_row = f"{'Neg. ay':>10s}"
    for lbl in labels:
        neg_row += f"  {neg_counts[lbl]:>4d}/{len(all_months):>2d}     "
    print(neg_row)


def main():
    print("Veri yükleniyor…")
    df_1m=load_all(); df_1h=resample(df_1m,"1h")
    print(f"Range: {df_1h.index[0].date()} → {df_1h.index[-1].date()}\n")

    print("="*115)
    print("ÇOKLU SERMAYE DİLİMİ + LİMİT GİRİŞ TESTİ")
    print("BB %3 risk | ORB %1.5 risk | Asia BO %1.0 risk — AYRI HESAPLAR")
    print("Train: May–Dec 2025 | Test: Jan–Apr 2026")
    print("="*115)

    configs = [
        ("BB ONLY (referans)",                     False, False, True,  True),
        ("ESKI: tek pos, close giriş",             True,  False, False, False),
        ("YENİ: ayrı sermaye, close giriş",        True,  True,  False, False),
        ("YENİ: ayrı sermaye, limit giriş",        True,  True,  True,  True),
    ]

    results = {}
    for label, with_all, sep_cap, lim_orb, lim_asia in configs:
        if not with_all:
            # BB only
            t=run(df_1h, separate_capital=False, limit_entry_orb=False, limit_entry_asia=False)
            t=[x for x in t if x["strat"]=="bb"]
        else:
            t=run(df_1h, separate_capital=sep_cap, limit_entry_orb=lim_orb, limit_entry_asia=lim_asia)
        tr,te=score(t); pr(label,tr,te); results[label]=t

    # Strateji detayı (en iyi config için)
    best = results["YENİ: ayrı sermaye, limit giriş"]
    print()
    print("─── Strateji bazlı katkı (YENİ: ayrı sermaye + limit giriş) ───")
    for strat in ["bb","orb","asia_bo"]:
        tt=[t for t in best if t["strat"]==strat]
        if tt:
            tr,te=score(tt)
            pr(f"  {strat}",tr,te)

    # Aylık dağılım
    print()
    print("─── Aylık dağılım ──────────────────────────────────────────────")
    monthly_table({
        "BB-only": results["BB ONLY (referans)"],
        "Ayrı+Limit": results["YENİ: ayrı sermaye, limit giriş"],
    })

    # Özet
    print()
    print("─── $200 gerçek hesap tahmini (/50 ölçek) ─────────────────────")
    for label in ["BB ONLY (referans)", "YENİ: ayrı sermaye, limit giriş"]:
        t=results[label]
        total=sum(x["pnl"] for x in t)
        n=len(t)
        p=np.array([x["pnl"] for x in t])
        wr=(p>0).mean() if len(p)>0 else 0
        eq=BAL+np.cumsum(p); pk=np.maximum.accumulate(eq)
        dd=((pk-eq)/pk).max() if len(p)>0 else 0
        print(f"  {label:<50s}: ${total/50:>+.0f}/yıl  WR{wr:.0%}  maxDD {dd*100:.1f}%  ({n}t)")


if __name__=="__main__":
    main()
