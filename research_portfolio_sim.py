"""
research_portfolio_sim.py — Tüm 5 sleeve birlikte: $100 başlangıç + $100/ay, 12 ay

BB + ORB + Asia BO + FVG + Squeeze aynı anda, aynı bütçeyi paylaşarak çalışır.

Gerçekçilik kısıtları:
  - MAX_SIZING_BALANCE = $10,000 (pozisyon büyüklüğü bu limit üzerinde donduruluyor)
    Neden? $10K üzerinde market depth kısıtı + aşırı compound sınırlaması
  - Bakiye = total equity (açık pozisyon teminatları dahil)
  - Min lot 0.001 BTC → küçük bakiyede bazı sinyaller geçer, bazıları minimum lot'u sağlayamaz

Kapsam: May 2025 → Apr 2026 (tam 12 ay, VALIDATION periodu)
Başlangıç: $100  |  Aylık ekleme: $100  |  Kaldıraç: 10x

Run: python research_portfolio_sim.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr as atr_fn, ema as ema_fn, bollinger_bands, adx as adx_fn

# ── Sabitler ──────────────────────────────────────────────────────────────
COST       = 0.0001   # taker fee per side
LEVERAGE   = 10
MIN_LOT    = 0.001    # BTC minimum lot
START      = 100.0
MONTHLY    = 100.0
MAX_SIZING = 10_000.0  # pozisyon boyutlandırması bu bakiyeyi geçemez

BB_RISK    = 0.08; BB_SL = 3.0;  BB_TP = 5.0;  BB_MH = 48
ORB_RISK   = 0.05; ORB_RR = 2.0; ORB_MH = 6
ASIA_RISK  = 0.03; ASIA_SL = 1.0; ASIA_RR = 2.0; ASIA_MH = 6
FVG_RISK   = 0.02; FVG_RR = 2.5;  FVG_SL_BUF = 0.3; FVG_GAP = 0.5; FVG_MH = 24
SQ_RISK    = 0.02; SQ_SL = 2.0;   SQ_RR = 2.5;  SQ_MH = 20
SQ_KC      = 1.5;  SQ_MINB = 5

ADX_TREND  = 28.0
BB_PERIOD  = 20; KC_PERIOD = 20; EMA200 = 200; ATR14 = 14


# ── Data ──────────────────────────────────────────────────────────────────

def load_months(patterns):
    frames = []
    for pat in patterns:
        for f in sorted(glob.glob(pat)):
            df = pd.read_csv(f)
            df.columns = ["ts","open","high","low","close","volume",
                          "ct","qv","count","tbv","tbqv","ign"]
            frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    m = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m.drop(columns=["ts"])


def to_1h(df_1m):
    return df_1m.resample("1h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


# ── Indicators ────────────────────────────────────────────────────────────

def kc_series(close, high, low, period=20, mult=1.5):
    mid = ema_fn(close, period)
    at  = atr_fn(high, low, close, period)
    return mid, mid + mult * at, mid - mult * at


def bb_arrays(close, period=20, std=2.0):
    mid = close.rolling(period).mean()
    sd  = close.rolling(period).std()
    return (mid + std * sd).values, (mid - std * sd).values


# ── Main simulation ───────────────────────────────────────────────────────

def run():
    print("Veri yükleniyor...")
    m1 = load_months([
        "/home/user/Bot2/BTCUSDT-1m-2025-*.csv",
        "/home/user/Bot2/BTCUSDT-1m-2026-*.csv",
    ])
    df = to_1h(m1)
    print(f"1h bar: {len(df)}  ({df.index[0].date()} → {df.index[-1].date()})")

    # Indicators — compute once
    close = df["close"]; high = df["high"]; low = df["low"]; vol = df["volume"]
    at14    = atr_fn(high, low, close, ATR14).values
    adxv    = adx_fn(high, low, close, 14).values
    bb_u, bb_l = bb_arrays(close)
    vol_ma  = vol.rolling(BB_PERIOD).mean().values
    e200    = ema_fn(close, EMA200).values
    kc_m, kc_up, kc_lo = kc_series(close, high, low, KC_PERIOD, SQ_KC)
    bb_up2, bb_lo2 = bb_arrays(close)  # for squeeze detection (same BB)
    in_sq   = pd.Series((bb_up2 < kc_up.values) & (bb_lo2 > kc_lo.values), index=df.index)
    sq_cnt  = in_sq.groupby((~in_sq).cumsum()).cumcount().values

    # 4h MTF direction
    df4 = m1.resample("4h").agg({"open":"first","high":"max","low":"min",
                                  "close":"last","volume":"sum"}).dropna()
    kc_m4, _, _ = kc_series(df4["close"], df4["high"], df4["low"], KC_PERIOD, SQ_KC)
    dir4_s = (df4["close"] > kc_m4).astype(int).replace(0, -1)
    dir4_s.index = dir4_s.index + pd.Timedelta("4h")
    dir4v = dir4_s.reindex(df.index, method="ffill").fillna(0).values

    cl  = close.values; hi = high.values; lo = low.values
    vm  = vol_ma; adx = adxv; kcm = kc_m.values
    insq = in_sq.values; sqcnt = sq_cnt
    idx = df.index

    # ── Bakiye (total equity) ─────────────────────────────────────────────
    equity = START          # gerçek toplam değer (açık pos teminatı dahil)
    deposits = 0            # kaç ekleme yapıldı

    # slots: None veya {dir,entry,sl,tp,qty,margin,bar}
    slots = {"bb": None, "orb": None, "asia": None, "fvg": None, "squeeze": None}

    # ORB / Asia per-day state
    orb_day  = {}
    asia_day = {}

    # FVG zones
    fvg_zones = []

    # Kayıtlar
    trades = []
    monthly_equity = {}   # month_str → equity at start of month (after deposit)
    current_mth = str(idx[0].to_period("M"))
    monthly_equity[current_mth] = equity

    def locked_margin():
        return sum(s["margin"] for s in slots.values() if s is not None)

    def free_equity():
        return equity - locked_margin()

    def try_open(slot, direction, entry, sl, tp, risk_pct, bar_i):
        nonlocal equity
        if slots[slot] is not None:
            return False
        sl_dist = abs(entry - sl)
        if sl_dist <= 0 or entry <= 0:
            return False
        # Pozisyon boyutu: MAX_SIZING ile sınırlı, gerçek equity'den de geçemez
        sizing_eq = min(equity, MAX_SIZING)
        risk_usdt = sizing_eq * risk_pct
        qty = round(risk_usdt / sl_dist, 3)
        if qty < MIN_LOT:
            return False
        margin = qty * entry / LEVERAGE
        if margin > free_equity() - 1:   # 1$ buffer
            return False
        slots[slot] = {
            "dir": direction, "entry": entry, "sl": sl, "tp": tp,
            "qty": qty, "margin": margin, "bar": bar_i,
        }
        return True

    def do_close(slot, exit_px, reason, bar_i):
        nonlocal equity
        s = slots[slot]
        if s is None:
            return
        pnl = (exit_px - s["entry"]) * s["dir"] * s["qty"]
        fee = (s["entry"] + exit_px) * s["qty"] * COST
        net = pnl - fee
        equity += net
        trades.append({
            "ts": idx[bar_i], "slot": slot, "dir": s["dir"],
            "entry": s["entry"], "exit": exit_px, "pnl": net,
            "reason": reason, "year": idx[bar_i].year,
            "month": str(idx[bar_i].to_period("M")),
        })
        slots[slot] = None

    # ── Bar loop ───────────────────────────────────────────────────────────
    WARMUP = EMA200 + 10
    prev_mth = current_mth

    for i in range(WARMUP, len(df)):
        ts   = idx[i]; atr_v = at14[i]
        if np.isnan(atr_v) or atr_v <= 0:
            continue

        date = ts.date(); hour = ts.hour; wday = ts.weekday()
        mth_str = str(ts.to_period("M"))

        # ── Aylık ekleme ────────────────────────────────────────────────
        if mth_str != prev_mth:
            equity += MONTHLY
            deposits += 1
            monthly_equity[mth_str] = equity
            prev_mth = mth_str

        # ── SL / TP / MaxHold kontrolleri ──────────────────────────────
        MAX_HOLDS = {"bb": BB_MH, "orb": ORB_MH, "asia": ASIA_MH,
                     "fvg": FVG_MH, "squeeze": SQ_MH}
        for slot, s in list(slots.items()):
            if s is None:
                continue
            d = s["dir"]
            hit_sl = lo[i] <= s["sl"] if d == 1 else hi[i] >= s["sl"]
            hit_tp = hi[i] >= s["tp"] if d == 1 else lo[i] <= s["tp"]
            expired = (i - s["bar"]) >= MAX_HOLDS[slot]
            if hit_sl and hit_tp:
                do_close(slot, s["sl"], "sl", i)
            elif hit_sl:
                do_close(slot, s["sl"], "sl", i)
            elif hit_tp:
                do_close(slot, s["tp"], "tp", i)
            elif expired:
                do_close(slot, cl[i], "maxhold", i)

        # ── FVG zone expiry ──────────────────────────────────────────────
        fvg_zones = [z for z in fvg_zones if z["age"] < FVG_MH and z["born"] < i]
        for z in fvg_zones:
            z["age"] += 1

        # ── BB (hafta sonu + ADX<28 + hacim) ────────────────────────────
        if slots["bb"] is None and wday >= 5:
            adx_ok = np.isnan(adx[i]) or adx[i] < ADX_TREND
            vol_ok = not np.isnan(vm[i]) and cl[i] > 0 and vol.iloc[i] > vm[i]
            if adx_ok and vol_ok and not np.isnan(bb_l[i]):
                if cl[i] < bb_l[i]:
                    try_open("bb", 1, cl[i], cl[i]-BB_SL*atr_v,
                             cl[i]+BB_TP*atr_v, BB_RISK, i)
                elif cl[i] > bb_u[i]:
                    try_open("bb", -1, cl[i], cl[i]+BB_SL*atr_v,
                             cl[i]-BB_TP*atr_v, BB_RISK, i)

        # ── ORB ──────────────────────────────────────────────────────────
        if hour == 14:
            orb_day[date] = {"h": hi[i], "l": lo[i], "done": False}
        elif hour > 14 and date in orb_day and not orb_day[date]["done"]:
            o = orb_day[date]; rng = o["h"] - o["l"]
            if rng > 0 and slots["orb"] is None:
                if cl[i] > o["h"]:
                    if try_open("orb", 1, o["h"], o["l"],
                                o["h"]+ORB_RR*rng, ORB_RISK, i):
                        orb_day[date]["done"] = True
                elif cl[i] < o["l"]:
                    if try_open("orb", -1, o["l"], o["h"],
                                o["l"]-ORB_RR*rng, ORB_RISK, i):
                        orb_day[date]["done"] = True

        # ── Asia BO ──────────────────────────────────────────────────────
        if 0 <= hour < 8:
            if date not in asia_day:
                asia_day[date] = {"h": hi[i], "l": lo[i], "done": False}
            else:
                asia_day[date]["h"] = max(asia_day[date]["h"], hi[i])
                asia_day[date]["l"] = min(asia_day[date]["l"], lo[i])
        elif hour >= 8 and date in asia_day and not asia_day[date]["done"]:
            a = asia_day[date]
            if slots["asia"] is None:
                if cl[i] > a["h"]:
                    if try_open("asia", 1, a["h"], a["h"]-ASIA_SL*atr_v,
                                a["h"]+ASIA_RR*atr_v, ASIA_RISK, i):
                        asia_day[date]["done"] = True
                elif cl[i] < a["l"]:
                    if try_open("asia", -1, a["l"], a["l"]+ASIA_SL*atr_v,
                                a["l"]-ASIA_RR*atr_v, ASIA_RISK, i):
                        asia_day[date]["done"] = True

        # ── FVG ──────────────────────────────────────────────────────────
        if i >= 2:
            gap_bull = lo[i] - hi[i-2]
            gap_bear = lo[i-2] - hi[i]
            if gap_bull >= FVG_GAP * atr_v:
                fvg_zones.append({"dir": 1, "top": float(lo[i]),
                                   "bot": float(hi[i-2]), "age": 0, "born": i})
            if gap_bear >= FVG_GAP * atr_v:
                fvg_zones.append({"dir": -1, "top": float(lo[i-2]),
                                   "bot": float(hi[i]), "age": 0, "born": i})

        if slots["fvg"] is None and not np.isnan(e200[i]):
            for z in list(fvg_zones):
                if z["born"] >= i:
                    continue
                sl_dist = (z["top"] - z["bot"]) + FVG_SL_BUF * atr_v
                if sl_dist <= 0:
                    continue
                if z["dir"] == 1 and lo[i] <= z["top"] and cl[i] > z["bot"]:
                    if cl[i] > e200[i]:
                        ep = z["top"]
                        if try_open("fvg", 1, ep, ep-sl_dist,
                                    ep+FVG_RR*sl_dist, FVG_RISK, i):
                            fvg_zones.remove(z); break
                elif z["dir"] == -1 and hi[i] >= z["bot"] and cl[i] < z["top"]:
                    if cl[i] < e200[i]:
                        ep = z["bot"]
                        if try_open("fvg", -1, ep, ep+sl_dist,
                                    ep-FVG_RR*sl_dist, FVG_RISK, i):
                            fvg_zones.remove(z); break

        # ── Squeeze ──────────────────────────────────────────────────────
        if slots["squeeze"] is None and i >= 1:
            was_sq = bool(insq[i-1])
            is_sq  = bool(insq[i])
            cnt    = int(sqcnt[i-1])
            if was_sq and not is_sq and cnt >= SQ_MINB:
                d1h = 1 if cl[i] > kcm[i] else -1
                d4h = int(dir4v[i])
                if d4h == 0 or d4h == d1h:
                    try_open("squeeze", d1h, cl[i],
                             cl[i]-d1h*SQ_SL*atr_v,
                             cl[i]+d1h*SQ_RR*SQ_SL*atr_v,
                             SQ_RISK, i)

    # Son açık pozisyonları kapat
    for slot in list(slots.keys()):
        if slots[slot] is not None:
            do_close(slot, cl[-1], "end", len(df)-1)

    # ── Rapor ──────────────────────────────────────────────────────────────
    t = pd.DataFrame(trades) if trades else pd.DataFrame()
    total_deposited = START + deposits * MONTHLY

    def pf(s):
        if len(s) == 0: return float("nan")
        w = s[s["pnl"] > 0]["pnl"].sum()
        l = abs(s[s["pnl"] < 0]["pnl"].sum())
        return round(w / l, 2) if l > 0 else 9.99

    net_gain = equity - total_deposited
    roi = (equity / total_deposited - 1) * 100 if total_deposited > 0 else 0

    print(f"\n{'='*60}")
    print(f"  PORTFÖY SİMÜLASYON: May 2025 → Apr 2026")
    print(f"{'='*60}")
    print(f"  Başlangıç: ${START:.0f}  |  Aylık ekleme: ${MONTHLY:.0f}")
    print(f"  Toplam yatırılan:  ${total_deposited:>8,.0f}")
    print(f"  Final equity:      ${equity:>8,.2f}")
    print(f"  Net kâr:           ${net_gain:>+8,.2f}  ({roi:+.1f}%)")

    if len(t) == 0:
        print("Trade yok!"); return

    eq_curve = t["pnl"].cumsum() + START
    pk = eq_curve.cummax(); mdd = abs(((eq_curve - pk) / pk).min()) * 100

    print(f"  Toplam trade:      {len(t)}")
    print(f"  Genel PF:          {pf(t):.2f}  WR: {(t['pnl']>0).mean()*100:.1f}%")
    print(f"  Max Drawdown:      {mdd:.1f}%")

    print(f"\n  {'Sleeve':<10} {'n':>4}  {'PF':>5}  {'WR':>5}  {'Net $':>8}")
    print(f"  {'-'*42}")
    for slot in ["bb","orb","asia","fvg","squeeze"]:
        sub = t[t["slot"]==slot]
        if len(sub) == 0:
            print(f"  {slot:<10}    0    —      —       —")
            continue
        print(f"  {slot:<10} {len(sub):>4}  {pf(sub):>5.2f}  "
              f"{(sub['pnl']>0).mean()*100:>4.0f}%  ${sub['pnl'].sum():>7.2f}")

    print(f"\n  {'Ay':<8} {'Başlangıç':>11} {'Net PnL':>9} {'Bitiş':>11} trades")
    print(f"  {'-'*52}")
    months = sorted(monthly_equity.keys())
    for k, mth in enumerate(months):
        m_trades = t[t["month"] == mth]
        m_pnl = m_trades["pnl"].sum() if len(m_trades) > 0 else 0.0
        m_start = monthly_equity[mth]
        m_end = m_start + m_pnl
        sign = "+" if m_pnl >= 0 else ""
        print(f"  {mth}  ${m_start:>10,.2f}  {sign}${m_pnl:>7,.2f}  "
              f"${m_end:>10,.2f}  {len(m_trades)}")

    print(f"\n{'='*60}")
    print(f"  $100 yatırıp aylık $100 ekleyerek = ${equity:,.2f}")
    print(f"  Toplam yatırılan $1,200 → net kâr: ${net_gain:+,.2f}")
    print(f"  ROI: {roi:+.1f}%  (yatırılan sermayeye göre)")
    print(f"{'='*60}")


if __name__ == "__main__":
    run()
