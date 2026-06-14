"""
research_combined4.py — Tüm 4 stratejiyi birlikte backtest eder.

Stratejiler (aynı anda 1 pozisyon, öncelik sırasıyla):
  1. BB Mean Reversion  — 1H, vol filter, SL=3×ATR TP=5×ATR, hold≤48h
  2. ORB (NY open)      — 14:00 UTC 1h range, SL=range, TP=2×range, hold≤6h, 1/gün
  3. Asia BO            — 00–07 UTC range, SL=1×ATR TP=2×ATR, hold≤6h, 1/gün
  4. S/R Breakout       — swing cluster kırılımı, vol+body filter, SL=3×ATR TP=4.5×ATR, hold≤48h

Hedef: Kasım 2025 gibi trend aylarında ORB/Asia BO/S/R BB açığını kapatıyor mu?
       Sonuç: tüm aylar pozitif mi?

Ölçek: $10,000 (oransal olarak $200 için /50 yap)
"""
from __future__ import annotations

import glob
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as adx_fn, find_sr_levels

# ─── Sabitler ────────────────────────────────────────────────────────────────
COST      = 0.0002     # %0.04 round-trip maker
BAL       = 10_000.0
SPLIT     = pd.Timestamp("2026-01-01")

# BB
BB_RISK   = 0.03; BB_SL = 3.0; BB_TP = 5.0; BB_MH = 48

# ORB
ORB_RISK  = 0.03; ORB_RR = 2.0; ORB_MH = 6; ORB_HOUR = 14

# Asia BO
ASIA_RISK = 0.03; ASIA_RR = 2.0; ASIA_SL_MULT = 1.0; ASIA_MH = 6

# S/R Breakout
SR_RISK   = 0.02; SR_SL = 3.0; SR_RR = 1.5; SR_MH = 48
SR_LB     = 50; SR_TOUCH = 2; SR_BREAK_PCT = 0.002

# Rejim filtresi
ADX_RANGING  = 20.0   # ADX < 20 → ranging → ORB/Asia/S/R baskılanır
ADX_TRENDING = 28.0   # ADX > 28 → trending


# ─── Veri yükleme ─────────────────────────────────────────────────────────────
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


# ─── Kombine backtest ─────────────────────────────────────────────────────────
def run_combined(df_1h, regime_filter=True):
    """
    Tek pozisyon, 4 strateji öncelik kaskadı: BB → ORB → Asia BO → S/R.
    regime_filter=True: ADX<20'de ORB/Asia/S/R baskılanır.
    """
    close  = df_1h["close"].values
    high   = df_1h["high"].values
    low_v  = df_1h["low"].values
    vol    = df_1h["volume"].values
    open_v = df_1h["open"].values
    idx    = df_1h.index

    # Precompute indicators
    upper_s, _, lower_s = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s   = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    adx_s   = adx_fn(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma  = df_1h["volume"].rolling(20).mean()
    bb_pos  = ((df_1h["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan))

    upper_arr = upper_s.values
    lower_arr = lower_s.values
    bb_arr    = bb_pos.values
    atr_arr   = atr_s.values
    adx_arr   = adx_s.values
    volma_arr = vol_ma.values

    n = len(close); warmup = 60

    balance  = BAL
    open_t   = None   # current open trade
    trades   = []

    # ORB / Asia BO: 1 trade per day state
    orb_traded:  set[date] = set()
    asia_traded: set[date] = set()

    for i in range(warmup, n):
        a = atr_arr[i]
        if np.isnan(a) or a <= 0:
            continue

        # ─── Manage open position ────────────────────────────────────────────
        if open_t is not None:
            d     = open_t["dir"]
            entry = open_t["entry"]
            sl    = open_t["sl"]
            tp    = open_t["tp"]
            qty   = open_t["qty"]
            mh    = open_t["max_hold"]
            held  = i - open_t["i"]

            ep = None; reason = None
            if d == 1:
                if low_v[i] <= sl:  ep, reason = sl,  "sl"
                elif high[i] >= tp: ep, reason = tp,  "tp"
            else:
                if high[i] >= sl:   ep, reason = sl,  "sl"
                elif low_v[i] <= tp:ep, reason = tp,  "tp"
            if ep is None and held >= mh:
                ep, reason = close[i], "mh"

            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                trades.append({
                    "ts":     idx[i],
                    "pnl":    pnl,
                    "reason": reason,
                    "strat":  open_t["strat"],
                    "dir":    d,
                    "entry":  entry,
                    "held":   held,
                })
                open_t = None
            continue

        # ─── Regime ──────────────────────────────────────────────────────────
        adx_v = adx_arr[i] if not np.isnan(adx_arr[i]) else 25.0
        if regime_filter:
            regime = "ranging" if adx_v < ADX_RANGING else (
                     "trending" if adx_v > ADX_TRENDING else "neutral")
            bo_allowed = (regime != "ranging")
        else:
            bo_allowed = True

        cur_date = idx[i].date()

        # ─── 1. BB Mean Reversion ────────────────────────────────────────────
        bpos = bb_arr[i]
        if not np.isnan(bpos) and (bpos < 0.0 or bpos > 1.0):
            direction = 1 if bpos < 0.0 else -1
            vm = volma_arr[i]
            if np.isnan(vm) or vol[i] >= vm:
                ep  = close[i]
                sl_d = BB_SL * a
                slp  = ep - direction * sl_d
                tpp  = ep + direction * BB_TP * a
                qty  = round((balance * BB_RISK) / (ep * sl_d / ep), 3)
                qty  = min(qty, balance * 0.5 / ep)
                if qty >= 0.001:
                    open_t = {"i": i, "dir": direction, "entry": ep,
                              "sl": slp, "tp": tpp, "qty": qty,
                              "max_hold": BB_MH, "strat": "bb"}
                    continue

        if not bo_allowed:
            continue   # skip ORB / Asia / S/R in ranging regime

        # ─── 2. ORB (NY 14:00 UTC) ───────────────────────────────────────────
        cur_hour = idx[i].hour
        if cur_date not in orb_traded and cur_hour > ORB_HOUR:
            # Find 14:00 candle for today
            mask_orb = (pd.to_datetime(idx).date == cur_date) & (idx.hour == ORB_HOUR)
            orb_rows = df_1h[mask_orb]
            if not orb_rows.empty:
                orb_high = float(orb_rows["high"].max())
                orb_low  = float(orb_rows["low"].min())
                orb_range = orb_high - orb_low
                if orb_range > 0:
                    cp = close[i]
                    direction = 0
                    if cp > orb_high:   direction = 1
                    elif cp < orb_low:  direction = -1
                    if direction != 0:
                        ep   = cp
                        slp  = orb_high - orb_range if direction == 1 else orb_low + orb_range
                        tpp  = ep + direction * ORB_RR * orb_range
                        sl_d = abs(ep - slp)
                        if sl_d > 0:
                            qty = round((balance * ORB_RISK) / (ep * sl_d / ep), 3)
                            qty = min(qty, balance * 0.5 / ep)
                            if qty >= 0.001:
                                orb_traded.add(cur_date)
                                open_t = {"i": i, "dir": direction, "entry": ep,
                                          "sl": slp, "tp": tpp, "qty": qty,
                                          "max_hold": ORB_MH, "strat": "orb"}
                                continue

        # ─── 3. Asia BO (London 08:00 UTC) ───────────────────────────────────
        if cur_date not in asia_traded and cur_hour >= 8:
            mask_asia = (pd.to_datetime(idx).date == cur_date) & (idx.hour < 8)
            asia_rows = df_1h[mask_asia]
            if len(asia_rows) >= 4:
                asia_high = float(asia_rows["high"].max())
                asia_low  = float(asia_rows["low"].min())
                cp = close[i]
                direction = 0
                if cp > asia_high:  direction = 1
                elif cp < asia_low: direction = -1
                if direction != 0:
                    sl_d = ASIA_SL_MULT * a
                    ep   = cp
                    slp  = ep - direction * sl_d
                    tpp  = ep + direction * ASIA_RR * sl_d
                    qty  = round((balance * ASIA_RISK) / (ep * sl_d / ep), 3)
                    qty  = min(qty, balance * 0.5 / ep)
                    if qty >= 0.001:
                        asia_traded.add(cur_date)
                        open_t = {"i": i, "dir": direction, "entry": ep,
                                  "sl": slp, "tp": tpp, "qty": qty,
                                  "max_hold": ASIA_MH, "strat": "asia_bo"}
                        continue

        # ─── 4. S/R Breakout ─────────────────────────────────────────────────
        if i >= SR_LB + 10:
            window = df_1h.iloc[i - SR_LB: i + 1]
            levels = find_sr_levels(window, lookback=SR_LB, min_touches=SR_TOUCH)
            if levels:
                cp   = close[i]
                prev = close[i - 1]
                vm   = volma_arr[i]
                # Volume spike check
                vol_ok = not np.isnan(vm) and vol[i] > 1.5 * vm
                # Body ratio check
                crange = high[i] - low_v[i]
                body   = abs(close[i] - open_v[i])
                body_ok = (crange > 0) and (body / crange > 0.6)
                if vol_ok and body_ok:
                    direction = 0
                    min_break = cp * SR_BREAK_PCT
                    for lvl in levels:
                        lp = lvl.price
                        if lvl.level_type == "resistance" and cp > lp + min_break and prev <= lp:
                            direction = 1; break
                        if lvl.level_type == "support" and cp < lp - min_break and prev >= lp:
                            direction = -1; break
                    if direction != 0:
                        ep   = cp
                        sl_d = SR_SL * a
                        slp  = ep - direction * sl_d
                        tpp  = ep + direction * SR_RR * sl_d
                        qty  = round((balance * SR_RISK) / (ep * sl_d / ep), 3)
                        qty  = min(qty, balance * 0.5 / ep)
                        if qty >= 0.001:
                            open_t = {"i": i, "dir": direction, "entry": ep,
                                      "sl": slp, "tp": tpp, "qty": qty,
                                      "max_hold": SR_MH, "strat": "sr"}
                            continue

    return trades


# ─── İstatistikler ───────────────────────────────────────────────────────────
def score(trades, split=SPLIT):
    tr = [t for t in trades if t["ts"] < split]
    te = [t for t in trades if t["ts"] >= split]

    def _s(tt):
        if not tt:
            return dict(n=0, wr=0, pnl=0, pf=0, dd=0)
        p = np.array([t["pnl"] for t in tt])
        pos = p[p > 0].sum(); neg = -p[p < 0].sum()
        pf  = pos / neg if neg > 0 else float("inf")
        eq  = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
        return dict(n=len(p), wr=(p>0).mean(), pnl=p.sum(), pf=pf,
                    dd=((pk-eq)/pk).max())
    return _s(tr), _s(te)


def monthly(trades):
    m = {}
    for t in trades:
        m.setdefault(t["ts"].strftime("%Y-%m"), []).append(t)
    return m


def pr(label, tr, te):
    tot = tr["pnl"] + te["pnl"]
    print(f"{label:<40s}  {tr['n']+te['n']:>3d}t {tot/100:>+6.1f}%  "
          f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  "
          f"TEST {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  "
          f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")


def main():
    print("Veri yükleniyor…")
    df_1m = load_all()
    df_1h = resample(df_1m, "1h")
    print(f"Veri aralığı: {df_1h.index[0].date()} → {df_1h.index[-1].date()}")
    print(f"1h mum sayısı: {len(df_1h)}\n")

    print("=" * 105)
    print("4 STRATEJİ KOMBİNASYON BACKTEST")
    print("Train: May–Dec 2025 | Test: Jan–Apr 2026")
    print("Öncelik: BB → ORB → Asia BO → S/R Breakout | MAX_POS=1")
    print("=" * 105)

    # BB only (referans)
    def run_bb_only(df_1h):
        from indicators import bollinger_bands, atr
        close=df_1h["close"].values; high=df_1h["high"].values
        low_v=df_1h["low"].values; vol=df_1h["volume"].values; idx=df_1h.index
        upper_s,_,lower_s=bollinger_bands(df_1h["close"],20,2.0)
        atr_s=atr(df_1h["high"],df_1h["low"],df_1h["close"],14)
        vol_ma=df_1h["volume"].rolling(20).mean().values
        bb_pos=((df_1h["close"]-lower_s)/(upper_s-lower_s).replace(0,np.nan)).values
        n=len(close); balance=BAL; open_t=None; trades=[]
        for i in range(60,n):
            a=atr_s.iloc[i]
            if np.isnan(a) or a<=0: continue
            if open_t is not None:
                d=open_t["dir"]; entry=open_t["entry"]; sl=open_t["sl"]; tp=open_t["tp"]
                qty=open_t["qty"]; held=i-open_t["i"]; ep=None; reason=None
                if d==1:
                    if low_v[i]<=sl: ep,reason=sl,"sl"
                    elif high[i]>=tp: ep,reason=tp,"tp"
                else:
                    if high[i]>=sl: ep,reason=sl,"sl"
                    elif low_v[i]<=tp: ep,reason=tp,"tp"
                if ep is None and held>=48: ep,reason=close[i],"mh"
                if ep is not None:
                    pnl=d*(ep-entry)*qty-(entry+ep)*qty*COST
                    balance+=pnl
                    trades.append({"ts":idx[i],"pnl":pnl,"reason":reason,"strat":"bb","dir":d})
                    open_t=None
                continue
            bpos=bb_pos[i]
            if np.isnan(bpos) or not (bpos<0 or bpos>1): continue
            direction=1 if bpos<0 else -1
            vm=vol_ma[i]
            if np.isnan(vm) or vol[i]<vm: continue
            ep=close[i]; sl_d=3.0*a; slp=ep-direction*sl_d; tpp=ep+direction*5.0*a
            qty=round((balance*BB_RISK)/(ep*sl_d/ep),3); qty=min(qty,balance*0.5/ep)
            if qty<0.001: continue
            open_t={"i":i,"dir":direction,"entry":ep,"sl":slp,"tp":tpp,"qty":qty}
        return trades

    bb_trades = run_bb_only(df_1h)
    tr_bb, te_bb = score(bb_trades)
    pr("BB ONLY (referans)", tr_bb, te_bb)

    # 4-strateji kombinasyon
    print()
    combo = run_combined(df_1h, regime_filter=True)
    tr_c, te_c = score(combo)
    pr("4 Strateji + rejim filtresi", tr_c, te_c)

    combo_no_regime = run_combined(df_1h, regime_filter=False)
    tr_cn, te_cn = score(combo_no_regime)
    pr("4 Strateji, rejim filtresi YOK", tr_cn, te_cn)

    # Strateji bazlı dağılım
    print()
    print("─── Strateji başına katkı (4-strateji + rejim filtresi) ───")
    for strat in ["bb", "orb", "asia_bo", "sr"]:
        tt = [t for t in combo if t["strat"] == strat]
        if tt:
            tr_s, te_s = score(tt)
            pr(f"  {strat:<10s}", tr_s, te_s)
        else:
            print(f"  {strat:<10s}: 0 trade")

    # Aylık dağılım
    print()
    print("─── Aylık dağılım ─────────────────────────────────────────")
    mb = monthly(bb_trades)
    mc = monthly(combo)
    all_months = sorted(set(list(mb) + list(mc)))
    print(f"{'Ay':<10s}  {'BB n':>5s} {'BB$':>8s}  {'Kombo n':>7s} {'Kombo$':>8s}  "
          f"{'Delta':>8s}  {'Stratejiler'}")

    for mo in all_months:
        bt = mb.get(mo, [])
        ct = mc.get(mo, [])
        bp = sum(t["pnl"] for t in bt)
        cp = sum(t["pnl"] for t in ct)
        strats = {}
        for t in ct:
            strats[t["strat"]] = strats.get(t["strat"], 0) + 1
        strat_str = " ".join(f"{k}×{v}" for k, v in sorted(strats.items()))
        print(f"  {mo}   {len(bt):>4d}t {bp:>+8.0f}    {len(ct):>5d}t {cp:>+8.0f}   "
              f"{cp-bp:>+8.0f}  [{strat_str}]")

    # Net özet
    bb_total  = sum(t["pnl"] for t in bb_trades)
    com_total = sum(t["pnl"] for t in combo)
    print()
    print("─── Özet ───────────────────────────────────────────────────")
    print(f"  BB ONLY toplam:         ${bb_total:>+8.0f} (+{bb_total/100:.1f}% on $10K) "
          f"→ $200'de ≈ ${bb_total/50:>+.0f}/yıl")
    print(f"  4-STRATEJİ toplam:      ${com_total:>+8.0f} (+{com_total/100:.1f}% on $10K) "
          f"→ $200'de ≈ ${com_total/50:>+.0f}/yıl")
    print(f"  İyileşme:               ${com_total-bb_total:>+8.0f} "
          f"({(com_total-bb_total)/bb_total*100:>+.1f}%)")
    print()
    # Negatif ay sayısı
    def neg_months(m):
        return sum(1 for mo, tt in m.items() if sum(t["pnl"] for t in tt) < 0)
    print(f"  BB negatif ay sayısı:   {neg_months(mb)} / {len(mb)}")
    print(f"  Kombo negatif ay sayısı:{neg_months(mc)} / {len(mc)}")


if __name__ == "__main__":
    main()
