"""
research_allocation.py — Sermaye/margin dağıtım yöntemlerini karşılaştır.

Aynı trade motoru (BB + ORB + Asia + FVG + Squeeze, research_portfolio_sim.py
ile birebir aynı sinyaller), SADECE sermaye dağıtım politikası değişir.

Test edilen politikalar:
  1. shared_equity   — MEVCUT: risk = toplam equity × risk_pct, ortak havuz
  2. shared_free     — risk = serbest (kilitlenmemiş) equity × risk_pct
  3. buckets         — her sleeve kendi alt-hesabı (equity × ağırlık)
  4. flat_risk       — tüm sleeve'ler eşit risk %
  5. half_risk       — mevcut riskler × 0.5
  6. scaled_0.75/1.25 — mevcut riskler × global çarpan

Her politika için: final equity, ROI, Max Drawdown, PF, trade sayısı ve
Calmar (ROI/MDD — risk-ayarlı getiri). EN İYİ = en yüksek Calmar, sadece
en yüksek getiri değil (getiri tek başına aşırı drawdown'u gizler).

Run: python research_allocation.py
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
MONTHLY    = 100.0
MAX_SIZING = 10_000.0

BB_RISK    = 0.08; BB_SL = 3.0;  BB_TP = 5.0;  BB_MH = 48
ORB_RISK   = 0.05; ORB_RR = 2.0; ORB_MH = 6
ASIA_RISK  = 0.03; ASIA_SL = 1.0; ASIA_RR = 2.0; ASIA_MH = 6
FVG_RISK   = 0.02; FVG_RR = 2.5;  FVG_SL_BUF = 0.3; FVG_GAP = 0.5; FVG_MH = 24
SQ_RISK    = 0.02; SQ_SL = 2.0;   SQ_RR = 2.5;  SQ_MH = 20
SQ_KC      = 1.5;  SQ_MINB = 5

ADX_TREND  = 28.0
BB_PERIOD  = 20; KC_PERIOD = 20; EMA200 = 200; ATR14 = 14

SLOTS = ["bb", "orb", "asia", "fvg", "squeeze"]
BASE_RISK = {"bb": BB_RISK, "orb": ORB_RISK, "asia": ASIA_RISK,
             "fvg": FVG_RISK, "squeeze": SQ_RISK}
MAX_HOLDS = {"bb": BB_MH, "orb": ORB_MH, "asia": ASIA_MH,
             "fvg": FVG_MH, "squeeze": SQ_MH}


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


def kc_series(close, high, low, period=20, mult=1.5):
    mid = ema_fn(close, period)
    at  = atr_fn(high, low, close, period)
    return mid, mid + mult * at, mid - mult * at


def bb_arrays(close, period=20, std=2.0):
    mid = close.rolling(period).mean()
    sd  = close.rolling(period).std()
    return (mid + std * sd).values, (mid - std * sd).values


# ── Precompute indicators once (shared across all policies) ─────────────────

def prep(df, m1):
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

    return {
        "cl": close.values, "hi": high.values, "lo": low.values,
        "vol": vol, "vm": vol_ma, "adx": adxv, "at14": at14,
        "bb_u": bb_u, "bb_l": bb_l, "e200": e200, "kcm": kc_m.values,
        "insq": in_sq.values, "sqcnt": sq_cnt, "dir4v": dir4v, "idx": df.index,
    }


# ── Simulation parametrized by allocation policy ────────────────────────────

def run_sim(P, D, policy, risk_scale=1.0, flat_risk=None, weights=None):
    """policy ∈ {shared_equity, shared_free, buckets, flat, scaled}
    risk_scale: global çarpan (scaled / half)
    flat_risk: 'flat' politikası için tek risk %
    weights: 'buckets' için sleeve ağırlıkları (toplam ≤ 1)
    """
    cl, hi, lo = D["cl"], D["hi"], D["lo"]
    vol, vm, adx, at14 = D["vol"], D["vm"], D["adx"], D["at14"]
    bb_u, bb_l, e200, kcm = D["bb_u"], D["bb_l"], D["e200"], D["kcm"]
    insq, sqcnt, dir4v, idx = D["insq"], D["sqcnt"], D["dir4v"], D["idx"]

    # Effective per-sleeve risk %
    risk = {}
    for s in SLOTS:
        if policy == "flat":
            risk[s] = flat_risk
        else:
            risk[s] = BASE_RISK[s] * risk_scale

    if weights is None:
        # default bucket weights ∝ base risk (more aggressive sleeve = bigger bucket)
        tot = sum(BASE_RISK.values())
        weights = {s: BASE_RISK[s] / tot for s in SLOTS}

    slots = {s: None for s in SLOTS}

    # Bucket sub-accounts (only used by 'buckets')
    bucket_eq = {s: START * weights[s] for s in SLOTS}

    equity = START
    deposits = 0
    orb_day, asia_day, fvg_zones, trades = {}, {}, [], []
    eq_series = []  # equity after every bar (for drawdown)

    def locked_margin():
        return sum(s["margin"] for s in slots.values() if s is not None)

    def free_equity():
        return equity - locked_margin()

    def bucket_locked(slot):
        s = slots[slot]
        return s["margin"] if s is not None else 0.0

    def try_open(slot, direction, entry, sl, tp, bar_i):
        nonlocal equity
        if slots[slot] is not None:
            return False
        sl_dist = abs(entry - sl)
        if sl_dist <= 0 or entry <= 0:
            return False

        rp = risk[slot]
        if policy == "buckets":
            base = min(bucket_eq[slot], MAX_SIZING)
        elif policy == "shared_free":
            base = min(free_equity(), MAX_SIZING)
        else:  # shared_equity, flat, scaled
            base = min(equity, MAX_SIZING)

        risk_usdt = base * rp
        qty = round(risk_usdt / sl_dist, 3)
        if qty < MIN_LOT:
            return False
        margin = qty * entry / LEVERAGE

        if policy == "buckets":
            if margin > bucket_eq[slot] - bucket_locked(slot) - 0.5:
                return False
        else:
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
        if policy == "buckets":
            bucket_eq[slot] += net
        trades.append({"slot": slot, "pnl": net,
                       "month": str(idx[bar_i].to_period("M"))})
        slots[slot] = None

    WARMUP = EMA200 + 10
    prev_mth = str(idx[WARMUP].to_period("M"))

    for i in range(WARMUP, len(idx)):
        ts = idx[i]; atr_v = at14[i]
        if np.isnan(atr_v) or atr_v <= 0:
            eq_series.append(equity); continue
        date = ts.date(); hour = ts.hour; wday = ts.weekday()
        mth_str = str(ts.to_period("M"))

        if mth_str != prev_mth:
            equity += MONTHLY
            deposits += 1
            if policy == "buckets":
                for s in SLOTS:
                    bucket_eq[s] += MONTHLY * weights[s]
            prev_mth = mth_str

        # SL/TP/maxhold
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

        fvg_zones[:] = [z for z in fvg_zones if z["age"] < FVG_MH and z["born"] < i]
        for z in fvg_zones:
            z["age"] += 1

        # BB
        if slots["bb"] is None and wday >= 5:
            adx_ok = np.isnan(adx[i]) or adx[i] < ADX_TREND
            vol_ok = not np.isnan(vm[i]) and cl[i] > 0 and vol.iloc[i] > vm[i]
            if adx_ok and vol_ok and not np.isnan(bb_l[i]):
                if cl[i] < bb_l[i]:
                    try_open("bb", 1, cl[i], cl[i]-BB_SL*atr_v, cl[i]+BB_TP*atr_v, i)
                elif cl[i] > bb_u[i]:
                    try_open("bb", -1, cl[i], cl[i]+BB_SL*atr_v, cl[i]-BB_TP*atr_v, i)

        # ORB
        if hour == 14:
            orb_day[date] = {"h": hi[i], "l": lo[i], "done": False}
        elif hour > 14 and date in orb_day and not orb_day[date]["done"]:
            o = orb_day[date]; rng = o["h"] - o["l"]
            if rng > 0 and slots["orb"] is None:
                if cl[i] > o["h"]:
                    if try_open("orb", 1, o["h"], o["l"], o["h"]+ORB_RR*rng, i):
                        orb_day[date]["done"] = True
                elif cl[i] < o["l"]:
                    if try_open("orb", -1, o["l"], o["h"], o["l"]-ORB_RR*rng, i):
                        orb_day[date]["done"] = True

        # Asia
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
                    if try_open("asia", 1, a["h"], a["h"]-ASIA_SL*atr_v, a["h"]+ASIA_RR*atr_v, i):
                        asia_day[date]["done"] = True
                elif cl[i] < a["l"]:
                    if try_open("asia", -1, a["l"], a["l"]+ASIA_SL*atr_v, a["l"]-ASIA_RR*atr_v, i):
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
                    if try_open("fvg", 1, ep, ep-sl_dist, ep+FVG_RR*sl_dist, i):
                        fvg_zones.remove(z); break
                elif z["dir"] == -1 and hi[i] >= z["bot"] and cl[i] < z["top"] and cl[i] < e200[i]:
                    ep = z["bot"]
                    if try_open("fvg", -1, ep, ep+sl_dist, ep-FVG_RR*sl_dist, i):
                        fvg_zones.remove(z); break

        # Squeeze
        if slots["squeeze"] is None and i >= 1:
            was_sq = bool(insq[i-1]); is_sq = bool(insq[i]); cnt = int(sqcnt[i-1])
            if was_sq and not is_sq and cnt >= SQ_MINB:
                d1h = 1 if cl[i] > kcm[i] else -1
                d4h = int(dir4v[i])
                if d4h == 0 or d4h == d1h:
                    try_open("squeeze", d1h, cl[i], cl[i]-d1h*SQ_SL*atr_v,
                             cl[i]+d1h*SQ_RR*SQ_SL*atr_v, i)

        eq_series.append(equity)

    for slot in SLOTS:
        if slots[slot] is not None:
            do_close(slot, cl[-1], "end", len(idx)-1)

    t = pd.DataFrame(trades) if trades else pd.DataFrame()
    total_dep = START + deposits * MONTHLY
    net = equity - total_dep
    roi = (equity / total_dep - 1) * 100 if total_dep > 0 else 0

    eq = pd.Series(eq_series)
    pk = eq.cummax()
    mdd = abs(((eq - pk) / pk).min()) * 100 if len(eq) else 0.0

    if len(t):
        w = t[t["pnl"] > 0]["pnl"].sum()
        l = abs(t[t["pnl"] < 0]["pnl"].sum())
        pf = round(w / l, 2) if l > 0 else 9.99
        wr = (t["pnl"] > 0).mean() * 100
    else:
        pf, wr = float("nan"), 0.0

    calmar = roi / mdd if mdd > 0 else float("nan")

    return {"equity": equity, "net": net, "roi": roi, "mdd": mdd,
            "pf": pf, "wr": wr, "n": len(t), "calmar": calmar,
            "dep": total_dep}


CONFIGS = [
    ("MEVCUT (shared_equity)", dict(policy="shared_equity")),
    ("Serbest-equity",          dict(policy="shared_free")),
    ("Sabit kova (risk∝)",      dict(policy="buckets")),
    ("Düz risk %3 (eşit)",      dict(policy="flat", flat_risk=0.03)),
    ("Düz risk %4 (eşit)",      dict(policy="flat", flat_risk=0.04)),
    ("Yarı risk (×0.5)",        dict(policy="scaled", risk_scale=0.5)),
    ("Ölçek ×0.75",             dict(policy="scaled", risk_scale=0.75)),
    ("Ölçek ×1.25",             dict(policy="scaled", risk_scale=1.25)),
]


def run_window(df, m1, label):
    """Run all policies on one date window. Returns {name: metrics}."""
    D = prep(df, m1)
    out = {}
    print(f"\n{'='*88}")
    print(f"  DÖNEM: {label}  ({df.index[0].date()} → {df.index[-1].date()}, "
          f"{len(df)} bar)")
    print(f"{'='*88}")
    print(f"  {'Politika':<24} {'Final $':>10} {'ROI':>8} "
          f"{'MaxDD':>7} {'PF':>5} {'WR':>5} {'Trade':>6} {'Calmar':>7}")
    print(f"  {'-'*84}")
    for name, kw in CONFIGS:
        r = run_sim(None, D, **kw)
        out[name] = r
        print(f"  {name:<24} ${r['equity']:>8,.0f} {r['roi']:>+7.0f}% "
              f"{r['mdd']:>6.1f}% {r['pf']:>5.2f} {r['wr']:>4.0f}% "
              f"{r['n']:>6} {r['calmar']:>7.2f}")
    return out


def main():
    print("Veri yükleniyor (2023-2026)...")
    m1 = load_months(["/home/user/Bot2/BTCUSDT-1m-20*.csv"])
    df = to_1h(m1)
    print(f"Toplam 1h bar: {len(df)}  ({df.index[0].date()} → {df.index[-1].date()})")

    # Rejim bazlı pencereler — her dağıtımın FARKLI koşullarda davranışı
    windows = [
        ("2023 (chop/recovery)", df.loc["2023-01-01":"2023-12-31"]),
        ("2024 (boğa)",          df.loc["2024-01-01":"2024-12-31"]),
        ("2025-26 (validation)", df.loc["2025-05-01":"2026-04-30"]),
        ("3 yıl (2023→2026)",    df),
    ]

    all_results = {}
    for label, sub in windows:
        if len(sub) < 500:
            continue
        all_results[label] = run_window(sub, m1, label)

    # ── Özet: ortalama Calmar sıralaması (rejimler arası sağlamlık) ──────────
    print(f"\n{'='*88}")
    print(f"  ÖZET — Rejimler arası ortalama (sağlamlık göstergesi)")
    print(f"{'='*88}")
    print(f"  {'Politika':<24} {'Ort.Calmar':>11} {'Ort.MaxDD':>10} "
          f"{'En kötü DD':>11} {'Ort.PF':>7}")
    print(f"  {'-'*72}")
    summary = []
    for name, _ in CONFIGS:
        cals = [all_results[w][name]["calmar"] for w in all_results
                if not np.isnan(all_results[w][name]["calmar"])]
        dds  = [all_results[w][name]["mdd"] for w in all_results]
        pfs  = [all_results[w][name]["pf"] for w in all_results
                if not np.isnan(all_results[w][name]["pf"])]
        avg_cal = np.mean(cals) if cals else float("nan")
        avg_dd  = np.mean(dds) if dds else float("nan")
        worst_dd = max(dds) if dds else float("nan")
        avg_pf  = np.mean(pfs) if pfs else float("nan")
        summary.append((name, avg_cal, avg_dd, worst_dd, avg_pf))
        print(f"  {name:<24} {avg_cal:>11.2f} {avg_dd:>9.1f}% "
              f"{worst_dd:>10.1f}% {avg_pf:>7.2f}")

    best = max(summary, key=lambda x: (x[1] if not np.isnan(x[1]) else -1))
    safest = min(summary, key=lambda x: (x[3] if not np.isnan(x[3]) else 1e9))
    print(f"\n  >> En iyi risk-ayarlı (ort. Calmar): {best[0]}")
    print(f"  >> En düşük en-kötü drawdown:        {safest[0]} ({safest[3]:.1f}%)")
    print(f"{'='*88}")


if __name__ == "__main__":
    main()
