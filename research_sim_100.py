"""
research_sim_100.py — $100 SABİT sermaye ile gerçekçi çok-aylık simülasyon.

research_portfolio_sim.py motorunun birebir aynısı, FARKLAR:
  - START=100, aylık ekleme YOK (MONTHLY=0) → saf "ayda kaç $ kâr" ölçümü
  - RISK_SCALE=1.25 tüm sleeve risk %'lerine uygulandı (canlı config ile aynı)
  - Aylık $ kâr dökümü + ortalama/medyan aylık kâr raporu
  - Tüm mevcut BTC verisi (2023→2026), tek coin (yerelde sadece BTC var)

GERÇEKÇİLİK:
  - Bakiye = total equity (açık pozisyon teminatları dahil)
  - Pozisyon boyutu serbest equity ve 10x kaldıraçla sınırlı ($100'de margin kısıtı baskın)
  - Min lot 0.001 BTC; taker fee %0.01 her bacak; pesimist SL/TP dolumu
  - MAX_POSITIONS=4 yerine 5 slot (bb/orb/asia/fvg/squeeze) ama margin doğal sınır

Run: python research_sim_100.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr as atr_fn, ema as ema_fn, adx as adx_fn

# ── Sabitler ──────────────────────────────────────────────────────────────
COST       = 0.0001
LEVERAGE   = 10
MIN_LOT    = 0.001
START      = 100.0
MONTHLY    = 150.0         # her ay $150 ekleme + compounding
MAX_SIZING = 10_000.0
SCALE      = 1.25          # RISK_SCALE (canlı config)

BB_RISK    = 0.08 * SCALE; BB_SL = 3.0;  BB_TP = 5.0;  BB_MH = 48
ORB_RISK   = 0.05 * SCALE; ORB_RR = 2.0; ORB_MH = 6
ASIA_RISK  = 0.03 * SCALE; ASIA_SL = 1.0; ASIA_RR = 2.0; ASIA_MH = 6
FVG_RISK   = 0.02 * SCALE; FVG_RR = 2.5;  FVG_SL_BUF = 0.3; FVG_GAP = 0.5; FVG_MH = 24
SQ_RISK    = 0.02 * SCALE; SQ_SL = 2.0;   SQ_RR = 2.5;  SQ_MH = 20
SQ_KC      = 1.5;  SQ_MINB = 5

ADX_TREND  = 28.0
BB_PERIOD  = 20; KC_PERIOD = 20; EMA200 = 200; ATR14 = 14


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


def kc_series(close, high, low, period=20, mult=1.5):
    mid = ema_fn(close, period)
    at  = atr_fn(high, low, close, period)
    return mid, mid + mult * at, mid - mult * at


def bb_arrays(close, period=20, std=2.0):
    mid = close.rolling(period).mean()
    sd  = close.rolling(period).std()
    return (mid + std * sd).values, (mid - std * sd).values


def run(start_after=None, label=""):
    print("Veri yükleniyor (tüm mevcut BTC ayları)...")
    m1 = load_months(["/home/user/Bot2/BTCUSDT-1m-*.csv"])
    if start_after is not None:
        m1 = m1[m1.index >= start_after]
    df = to_1h(m1)
    if label:
        print(f"\n########## {label} ##########")
    print(f"1h bar: {len(df)}  ({df.index[0].date()} → {df.index[-1].date()})")

    close = df["close"]; high = df["high"]; low = df["low"]; vol = df["volume"]
    at14    = atr_fn(high, low, close, ATR14).values
    adxv    = adx_fn(high, low, close, 14).values
    bb_u, bb_l = bb_arrays(close)
    vol_ma  = vol.rolling(BB_PERIOD).mean().values
    e200    = ema_fn(close, EMA200).values
    kc_m, kc_up, kc_lo = kc_series(close, high, low, KC_PERIOD, SQ_KC)
    bb_up2, bb_lo2 = bb_arrays(close)
    in_sq   = pd.Series((bb_up2 < kc_up.values) & (bb_lo2 > kc_lo.values), index=df.index)
    sq_cnt  = in_sq.groupby((~in_sq).cumsum()).cumcount().values

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

    equity = START
    slots = {"bb": None, "orb": None, "asia": None, "fvg": None, "squeeze": None}
    orb_day  = {}
    asia_day = {}
    fvg_zones = []
    trades = []

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
        sizing_eq = min(equity, MAX_SIZING)   # compounding (MAX_SIZING'e kadar)
        risk_usdt = sizing_eq * risk_pct
        qty = round(risk_usdt / sl_dist, 3)
        if qty < MIN_LOT:
            return False
        margin = qty * entry / LEVERAGE
        if margin > free_equity() - 1:
            return False
        slots[slot] = {"dir": direction, "entry": entry, "sl": sl, "tp": tp,
                       "qty": qty, "margin": margin, "bar": bar_i}
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
        trades.append({"ts": idx[bar_i], "slot": slot, "pnl": net,
                       "reason": reason, "month": str(idx[bar_i].to_period("M"))})
        slots[slot] = None

    WARMUP = EMA200 + 10
    MAX_HOLDS = {"bb": BB_MH, "orb": ORB_MH, "asia": ASIA_MH,
                 "fvg": FVG_MH, "squeeze": SQ_MH}

    # Per-month bookkeeping for honest % return: equity at month start (AFTER the
    # deposit) and the deposit amount, so monthly profit excludes deposits.
    month_start_eq = {}   # month → equity right after that month's deposit
    month_deposit  = {}   # month → $ deposited that month
    deposits_total = 0.0
    prev_mth = None
    first_mth = True

    for i in range(WARMUP, len(df)):
        ts   = idx[i]; atr_v = at14[i]
        if np.isnan(atr_v) or atr_v <= 0:
            continue
        date = ts.date(); hour = ts.hour; wday = ts.weekday()
        mth_str = str(ts.to_period("M"))
        if mth_str != prev_mth:
            # Add the monthly deposit at the start of every month except the first
            # (the first month starts from START only).
            dep = 0.0 if first_mth else MONTHLY
            equity += dep
            deposits_total += dep
            month_deposit[mth_str] = dep
            month_start_eq[mth_str] = equity
            prev_mth = mth_str
            first_mth = False

        # SL/TP/MaxHold
        for slot, s in list(slots.items()):
            if s is None:
                continue
            d = s["dir"]
            hit_sl = lo[i] <= s["sl"] if d == 1 else hi[i] >= s["sl"]
            hit_tp = hi[i] >= s["tp"] if d == 1 else lo[i] <= s["tp"]
            expired = (i - s["bar"]) >= MAX_HOLDS[slot]
            if hit_sl:
                do_close(slot, s["sl"], "sl", i)
            elif hit_tp:
                do_close(slot, s["tp"], "tp", i)
            elif expired:
                do_close(slot, cl[i], "maxhold", i)

        fvg_zones = [z for z in fvg_zones if z["age"] < FVG_MH and z["born"] < i]
        for z in fvg_zones:
            z["age"] += 1

        # BB (weekend + ADX<28 + volume)
        if slots["bb"] is None and wday >= 5:
            adx_ok = np.isnan(adx[i]) or adx[i] < ADX_TREND
            vol_ok = not np.isnan(vm[i]) and cl[i] > 0 and vol.iloc[i] > vm[i]
            if adx_ok and vol_ok and not np.isnan(bb_l[i]):
                if cl[i] < bb_l[i]:
                    try_open("bb", 1, cl[i], cl[i]-BB_SL*atr_v, cl[i]+BB_TP*atr_v, BB_RISK, i)
                elif cl[i] > bb_u[i]:
                    try_open("bb", -1, cl[i], cl[i]+BB_SL*atr_v, cl[i]-BB_TP*atr_v, BB_RISK, i)

        # ORB
        if hour == 14:
            orb_day[date] = {"h": hi[i], "l": lo[i], "done": False}
        elif hour > 14 and date in orb_day and not orb_day[date]["done"]:
            o = orb_day[date]; rng = o["h"] - o["l"]
            if rng > 0 and slots["orb"] is None:
                if cl[i] > o["h"]:
                    if try_open("orb", 1, o["h"], o["l"], o["h"]+ORB_RR*rng, ORB_RISK, i):
                        orb_day[date]["done"] = True
                elif cl[i] < o["l"]:
                    if try_open("orb", -1, o["l"], o["h"], o["l"]-ORB_RR*rng, ORB_RISK, i):
                        orb_day[date]["done"] = True

        # Asia BO
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
                    if try_open("asia", 1, a["h"], a["h"]-ASIA_SL*atr_v, a["h"]+ASIA_RR*atr_v, ASIA_RISK, i):
                        asia_day[date]["done"] = True
                elif cl[i] < a["l"]:
                    if try_open("asia", -1, a["l"], a["l"]+ASIA_SL*atr_v, a["l"]-ASIA_RR*atr_v, ASIA_RISK, i):
                        asia_day[date]["done"] = True

        # FVG
        if i >= 2:
            gap_bull = lo[i] - hi[i-2]
            gap_bear = lo[i-2] - hi[i]
            if gap_bull >= FVG_GAP * atr_v:
                fvg_zones.append({"dir": 1, "top": float(lo[i]), "bot": float(hi[i-2]), "age": 0, "born": i})
            if gap_bear >= FVG_GAP * atr_v:
                fvg_zones.append({"dir": -1, "top": float(lo[i-2]), "bot": float(hi[i]), "age": 0, "born": i})
        if slots["fvg"] is None and not np.isnan(e200[i]):
            for z in list(fvg_zones):
                if z["born"] >= i:
                    continue
                sl_dist = (z["top"] - z["bot"]) + FVG_SL_BUF * atr_v
                if sl_dist <= 0:
                    continue
                if z["dir"] == 1 and lo[i] <= z["top"] and cl[i] > z["bot"] and cl[i] > e200[i]:
                    ep = z["top"]
                    if try_open("fvg", 1, ep, ep-sl_dist, ep+FVG_RR*sl_dist, FVG_RISK, i):
                        fvg_zones.remove(z); break
                elif z["dir"] == -1 and hi[i] >= z["bot"] and cl[i] < z["top"] and cl[i] < e200[i]:
                    ep = z["bot"]
                    if try_open("fvg", -1, ep, ep+sl_dist, ep-FVG_RR*sl_dist, FVG_RISK, i):
                        fvg_zones.remove(z); break

        # Squeeze
        if slots["squeeze"] is None and i >= 1:
            was_sq = bool(insq[i-1]); is_sq = bool(insq[i]); cnt = int(sqcnt[i-1])
            if was_sq and not is_sq and cnt >= SQ_MINB:
                d1h = 1 if cl[i] > kcm[i] else -1
                d4h = int(dir4v[i])
                if d4h == 0 or d4h == d1h:
                    try_open("squeeze", d1h, cl[i], cl[i]-d1h*SQ_SL*atr_v,
                             cl[i]+d1h*SQ_RR*SQ_SL*atr_v, SQ_RISK, i)

    for slot in list(slots.keys()):
        if slots[slot] is not None:
            do_close(slot, cl[-1], "end", len(df)-1)

    # ── Rapor ────────────────────────────────────────────────────────────
    t = pd.DataFrame(trades) if trades else pd.DataFrame()
    print(f"\n{'='*72}")
    print(f"  $100 BAŞLANGIÇ + $150/AY + COMPOUNDING — RISK_SCALE=1.25 — BTC")
    print(f"{'='*72}")
    if len(t) == 0:
        print("Trade yok!"); return
    invested = START + deposits_total
    print(f"  Dönem:            {idx[0].date()} → {idx[-1].date()}")
    print(f"  Yatırılan toplam: ${invested:,.2f}  ($100 + {int(deposits_total/MONTHLY) if MONTHLY else 0}×$150)")
    print(f"  Final equity:     ${equity:,.2f}")
    print(f"  Net kâr:          ${equity-invested:+,.2f}")
    print(f"  Trade sayısı:     {len(t)}   WR: {(t['pnl']>0).mean()*100:.1f}%")

    # Aylık döküm: kâr $ + AYLIK % GETİRİ (deposit hariç, ay-başı equity üzerinden)
    mpnl = t.groupby("month")["pnl"].sum()
    print(f"\n  {'Ay':<9}{'Trd':>5}{'Ay başı $':>12}{'+Ekleme':>9}{'Kâr $':>11}{'Aylık %':>9}")
    print(f"  {'-'*56}")
    monthly_pct = []
    monthly_pnl = []
    for mth in sorted(month_start_eq.keys()):
        start_eq = month_start_eq[mth]
        dep = month_deposit.get(mth, 0.0)
        p = mpnl.get(mth, 0.0)
        n = int((t["month"] == mth).sum()) if len(t) else 0
        # % return on the capital available that month (start equity incl. deposit)
        pct = (p / start_eq * 100) if start_eq > 0 else 0.0
        monthly_pct.append(pct)
        monthly_pnl.append(p)
        print(f"  {mth:<9}{n:>5}{start_eq:>12,.0f}{dep:>+9.0f}{p:>+11.2f}{pct:>+8.1f}%")

    pct_arr = np.array(monthly_pct)
    pos_mths = (pct_arr > 0).sum()
    print(f"\n  {'-'*56}")
    print(f"  Toplam ay:               {len(pct_arr)}")
    print(f"  Kârlı ay:                {pos_mths}/{len(pct_arr)}  ({pos_mths/len(pct_arr)*100:.0f}%)")
    print(f"  ORTALAMA aylık getiri:   {pct_arr.mean():+.1f}%")
    print(f"  MEDYAN aylık getiri:     {np.median(pct_arr):+.1f}%")
    print(f"  En iyi / en kötü ay:     {pct_arr.max():+.1f}% / {pct_arr.min():+.1f}%")

    eq_curve = t["pnl"].cumsum() + START
    pk = eq_curve.cummax(); mdd = abs(((eq_curve - pk) / pk).min()) * 100
    print(f"  Max drawdown:            {mdd:.1f}%")

    # In-sample (2023-24, stratejilerin ayarlandığı veri) vs out-of-sample (2025+)
    is_mask  = pct_arr[[m < '2025' for m in sorted(month_start_eq.keys())]]
    oos_mask = pct_arr[[m >= '2025' for m in sorted(month_start_eq.keys())]]
    print(f"\n  AYLIK GETİRİ — dönem ayrımı (overfit kontrolü):")
    if len(is_mask):
        print(f"    2023-2024 (in-sample, İYİMSER):  ort {is_mask.mean():+.1f}%/ay")
    if len(oos_mask):
        print(f"    2025-2026 (out-of-sample, DÜRÜST): ort {oos_mask.mean():+.1f}%/ay")


if __name__ == "__main__":
    # 1) Tüm dönem (2023→2026) — in-sample dahil, iyimser üst sınır
    run(label="TÜM DÖNEM 2023-2026 (in-sample dahil — İYİMSER)")
    # 2) Sadece out-of-sample (2025-05→2026-04), SIFIRDAN $100 — küçük hesap + görülmemiş veri
    run(start_after="2025-01-01", label="SADECE OOS 2025-2026, SIFIRDAN $100 (EN DÜRÜST)")
