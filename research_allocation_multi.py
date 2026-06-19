"""
research_allocation_multi.py — ÇOKLU-COIN sermaye dağıtım testi (BTC + ETH).

research_allocation.py tek coin (BTC) idi. Bu versiyon BTC ve ETH'yi TEK
sermaye havuzunu paylaştırarak çalıştırır — gerçek bot gibi, margin hem
stratejilere hem coinlere bölünür. Böylece "eşit-risk daha iyi" bulgusu
sermaye coinlere de bölününce hâlâ geçerli mi görülür.

Veri kısıtı: yalnız BTC (tam) + ETH (2025-09→12) lokalde mevcut. Bu yüzden
test 4  aylık çakışan pencere (2025 Eyl-Ara). Tek rejim — yön gösterici,
kesin değil.

Slot'lar coin başına: btc_bb, eth_orb, ... Aynı anda en fazla MAX_POS pozisyon.

Run: python research_allocation_multi.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from research_allocation import (
    load_months, to_1h, prep, COST, LEVERAGE, MIN_LOT, START, MONTHLY,
    MAX_SIZING, BASE_RISK, MAX_HOLDS, SLOTS as SLEEVES,
    BB_SL, BB_TP, ORB_RR, ASIA_SL, ASIA_RR, FVG_RR, FVG_SL_BUF, FVG_GAP,
    SQ_SL, SQ_RR, SQ_KC, SQ_MINB, ADX_TREND, EMA200,
)

MAX_POS = 4   # gerçek bottaki MAX_POSITIONS


def gen_keys(coins):
    return [f"{c}_{s}" for c in coins for s in SLEEVES]


def run_multi(coin_data, policy, risk_scale=1.0, flat_risk=None):
    """coin_data: {coin: prepped-dict D}. Tek havuz, coin başına slot."""
    coins = list(coin_data.keys())
    # Ortak saatlik index (kesişim)
    common = None
    for c in coins:
        ix = pd.DatetimeIndex(coin_data[c]["idx"])
        common = ix if common is None else common.intersection(ix)
    common = common.sort_values()

    # Her coin için index→pozisyon haritası
    pos_map = {c: {ts: k for k, ts in enumerate(coin_data[c]["idx"])} for c in coins}

    risk = {}
    for s in SLEEVES:
        risk[s] = flat_risk if policy == "flat" else BASE_RISK[s] * risk_scale

    slots = {k: None for k in gen_keys(coins)}
    equity = START
    deposits = 0
    orb_day = {c: {} for c in coins}
    asia_day = {c: {} for c in coins}
    fvg_zones = {c: [] for c in coins}
    trades = []
    eq_series = []

    def locked():
        return sum(s["margin"] for s in slots.values() if s is not None)

    def free_eq():
        return equity - locked()

    def n_open():
        return sum(1 for s in slots.values() if s is not None)

    def try_open(key, direction, entry, sl, tp, sleeve, ts):
        nonlocal equity
        if slots[key] is not None:
            return False
        if n_open() >= MAX_POS:
            return False
        sl_dist = abs(entry - sl)
        if sl_dist <= 0 or entry <= 0:
            return False
        base = min(free_eq() if policy == "shared_free" else equity, MAX_SIZING)
        qty = round(base * risk[sleeve] / sl_dist, 3)
        if qty < MIN_LOT:
            return False
        margin = qty * entry / LEVERAGE
        if margin > free_eq() - 1:
            return False
        slots[key] = {"dir": direction, "entry": entry, "sl": sl, "tp": tp,
                      "qty": qty, "margin": margin, "ts": ts, "sleeve": sleeve}
        return True

    def do_close(key, exit_px, reason, ts):
        nonlocal equity
        s = slots[key]
        if s is None:
            return
        pnl = (exit_px - s["entry"]) * s["dir"] * s["qty"]
        fee = (s["entry"] + exit_px) * s["qty"] * COST
        net = pnl - fee
        equity += net
        trades.append({"key": key, "sleeve": s["sleeve"], "pnl": net,
                       "month": str(pd.Timestamp(ts).to_period("M"))})
        slots[key] = None

    prev_mth = str(common[0].to_period("M"))

    for ts in common:
        mth = str(ts.to_period("M"))
        if mth != prev_mth:
            equity += MONTHLY
            deposits += 1
            prev_mth = mth

        hour = ts.hour; wday = ts.weekday()

        for c in coins:
            D = coin_data[c]
            i = pos_map[c].get(ts)
            if i is None or i < EMA200 + 10:
                continue
            cl = D["cl"]; hi = D["hi"]; lo = D["lo"]
            atr_v = D["at14"][i]
            if np.isnan(atr_v) or atr_v <= 0:
                continue
            adx = D["adx"]; vm = D["vm"]; vol = D["vol"]
            bb_u = D["bb_u"]; bb_l = D["bb_l"]; e200 = D["e200"]; kcm = D["kcm"]
            insq = D["insq"]; sqcnt = D["sqcnt"]; dir4v = D["dir4v"]
            date = ts.date()

            # ── Exit kontrolleri (bu coin'in slotları) ──
            for s in SLEEVES:
                key = f"{c}_{s}"
                pos = slots[key]
                if pos is None:
                    continue
                d = pos["dir"]
                hit_sl = lo[i] <= pos["sl"] if d == 1 else hi[i] >= pos["sl"]
                hit_tp = hi[i] >= pos["tp"] if d == 1 else lo[i] <= pos["tp"]
                bar_age = i - pos_map[c].get(pd.Timestamp(pos["ts"]), i)
                expired = bar_age >= MAX_HOLDS[s]
                if hit_sl:
                    do_close(key, pos["sl"], "sl", ts)
                elif hit_tp:
                    do_close(key, pos["tp"], "tp", ts)
                elif expired:
                    do_close(key, cl[i], "maxhold", ts)

            # FVG zone aging
            fvg_zones[c] = [z for z in fvg_zones[c] if z["age"] < MAX_HOLDS["fvg"] and z["born"] < i]
            for z in fvg_zones[c]:
                z["age"] += 1

            # ── BB ──
            if slots[f"{c}_bb"] is None and wday >= 5:
                adx_ok = np.isnan(adx[i]) or adx[i] < ADX_TREND
                vol_ok = not np.isnan(vm[i]) and cl[i] > 0 and vol.iloc[i] > vm[i]
                if adx_ok and vol_ok and not np.isnan(bb_l[i]):
                    if cl[i] < bb_l[i]:
                        try_open(f"{c}_bb", 1, cl[i], cl[i]-BB_SL*atr_v, cl[i]+BB_TP*atr_v, "bb", ts)
                    elif cl[i] > bb_u[i]:
                        try_open(f"{c}_bb", -1, cl[i], cl[i]+BB_SL*atr_v, cl[i]-BB_TP*atr_v, "bb", ts)

            # ── ORB ──
            if hour == 14:
                orb_day[c][date] = {"h": hi[i], "l": lo[i], "done": False}
            elif hour > 14 and date in orb_day[c] and not orb_day[c][date]["done"]:
                o = orb_day[c][date]; rng = o["h"] - o["l"]
                if rng > 0 and slots[f"{c}_orb"] is None:
                    if cl[i] > o["h"]:
                        if try_open(f"{c}_orb", 1, o["h"], o["l"], o["h"]+ORB_RR*rng, "orb", ts):
                            orb_day[c][date]["done"] = True
                    elif cl[i] < o["l"]:
                        if try_open(f"{c}_orb", -1, o["l"], o["h"], o["l"]-ORB_RR*rng, "orb", ts):
                            orb_day[c][date]["done"] = True

            # ── Asia ──
            if 0 <= hour < 8:
                if date not in asia_day[c]:
                    asia_day[c][date] = {"h": hi[i], "l": lo[i], "done": False}
                else:
                    asia_day[c][date]["h"] = max(asia_day[c][date]["h"], hi[i])
                    asia_day[c][date]["l"] = min(asia_day[c][date]["l"], lo[i])
            elif hour >= 8 and date in asia_day[c] and not asia_day[c][date]["done"]:
                a = asia_day[c][date]
                if slots[f"{c}_asia"] is None:
                    if cl[i] > a["h"]:
                        if try_open(f"{c}_asia", 1, a["h"], a["h"]-ASIA_SL*atr_v, a["h"]+ASIA_RR*atr_v, "asia", ts):
                            asia_day[c][date]["done"] = True
                    elif cl[i] < a["l"]:
                        if try_open(f"{c}_asia", -1, a["l"], a["l"]+ASIA_SL*atr_v, a["l"]-ASIA_RR*atr_v, "asia", ts):
                            asia_day[c][date]["done"] = True

            # ── FVG ──
            if i >= 2:
                gap_bull = lo[i] - hi[i-2]
                gap_bear = lo[i-2] - hi[i]
                if gap_bull >= FVG_GAP * atr_v:
                    fvg_zones[c].append({"dir": 1, "top": float(lo[i]), "bot": float(hi[i-2]), "age": 0, "born": i})
                if gap_bear >= FVG_GAP * atr_v:
                    fvg_zones[c].append({"dir": -1, "top": float(lo[i-2]), "bot": float(hi[i]), "age": 0, "born": i})
            if slots[f"{c}_fvg"] is None and not np.isnan(e200[i]):
                for z in list(fvg_zones[c]):
                    if z["born"] >= i:
                        continue
                    sl_dist = (z["top"] - z["bot"]) + FVG_SL_BUF * atr_v
                    if sl_dist <= 0:
                        continue
                    if z["dir"] == 1 and lo[i] <= z["top"] and cl[i] > z["bot"] and cl[i] > e200[i]:
                        ep = z["top"]
                        if try_open(f"{c}_fvg", 1, ep, ep-sl_dist, ep+FVG_RR*sl_dist, "fvg", ts):
                            fvg_zones[c].remove(z); break
                    elif z["dir"] == -1 and hi[i] >= z["bot"] and cl[i] < z["top"] and cl[i] < e200[i]:
                        ep = z["bot"]
                        if try_open(f"{c}_fvg", -1, ep, ep+sl_dist, ep-FVG_RR*sl_dist, "fvg", ts):
                            fvg_zones[c].remove(z); break

            # ── Squeeze ──
            if slots[f"{c}_squeeze"] is None and i >= 1:
                if bool(insq[i-1]) and not bool(insq[i]) and int(sqcnt[i-1]) >= SQ_MINB:
                    d1h = 1 if cl[i] > kcm[i] else -1
                    d4h = int(dir4v[i])
                    if d4h == 0 or d4h == d1h:
                        try_open(f"{c}_squeeze", d1h, cl[i], cl[i]-d1h*SQ_SL*atr_v,
                                 cl[i]+d1h*SQ_RR*SQ_SL*atr_v, "squeeze", ts)

        eq_series.append(equity)

    # close leftovers at last close
    for c in coins:
        last_i = len(coin_data[c]["cl"]) - 1
        for s in SLEEVES:
            key = f"{c}_{s}"
            if slots[key] is not None:
                do_close(key, coin_data[c]["cl"][last_i], "end", common[-1])

    t = pd.DataFrame(trades) if trades else pd.DataFrame()
    total_dep = START + deposits * MONTHLY
    net = equity - total_dep
    roi = (equity / total_dep - 1) * 100 if total_dep > 0 else 0
    eq = pd.Series(eq_series); pk = eq.cummax()
    mdd = abs(((eq - pk) / pk).min()) * 100 if len(eq) else 0.0
    if len(t):
        w = t[t["pnl"] > 0]["pnl"].sum(); l = abs(t[t["pnl"] < 0]["pnl"].sum())
        pf = round(w/l, 2) if l > 0 else 9.99
        wr = (t["pnl"] > 0).mean()*100
        n_mth = t["month"].nunique()
        avg_mth = net / n_mth if n_mth else 0.0
    else:
        pf, wr, avg_mth = float("nan"), 0.0, 0.0
    calmar = roi/mdd if mdd > 0 else float("nan")
    return {"equity": equity, "net": net, "roi": roi, "mdd": mdd, "pf": pf,
            "wr": wr, "n": len(t), "calmar": calmar, "avg_mth": avg_mth,
            "dep": total_dep, "trades": t}


def main():
    print("Veri yükleniyor (BTC + ETH, çakışan dönem)...")
    btc1 = load_months(["/home/user/Bot2/BTCUSDT-1m-2025-09.csv",
                        "/home/user/Bot2/BTCUSDT-1m-2025-1*.csv"])
    eth1 = load_months(["/home/user/Bot2/eth_data/ETHUSDT-1m-2025-09.csv",
                        "/home/user/Bot2/eth_data/ETHUSDT-1m-2025-1*.csv"])
    btc_h = to_1h(btc1); eth_h = to_1h(eth1)
    # kesişen aylar
    lo_ts = max(btc_h.index[0], eth_h.index[0])
    hi_ts = min(btc_h.index[-1], eth_h.index[-1])
    btc_h = btc_h.loc[lo_ts:hi_ts]; eth_h = eth_h.loc[lo_ts:hi_ts]
    print(f"Dönem: {btc_h.index[0].date()} → {btc_h.index[-1].date()}  "
          f"BTC {len(btc_h)} / ETH {len(eth_h)} bar")

    D = {"btc": prep(btc_h, btc1), "eth": prep(eth_h, eth1)}

    configs = [
        ("MEVCUT (kademeli)",   dict(policy="shared_equity")),
        ("Serbest-equity",      dict(policy="shared_free")),
        ("Düz eşit %3",         dict(policy="flat", flat_risk=0.03)),
        ("Düz eşit %4",         dict(policy="flat", flat_risk=0.04)),
        ("Yarı risk ×0.5",      dict(policy="scaled", risk_scale=0.5)),
        ("Ölçek ×1.25",         dict(policy="scaled", risk_scale=1.25)),
    ]

    print(f"\n{'='*90}")
    print(f"  ÇOKLU-COIN (BTC+ETH) DAĞITIM TESTİ  (${START:.0f}+${MONTHLY:.0f}/ay, "
          f"10x, max {MAX_POS} poz)")
    print(f"{'='*90}")
    print(f"  {'Politika':<20} {'Final $':>9} {'Net $':>8} {'ROI':>7} "
          f"{'Ay.Ort$':>9} {'MaxDD':>7} {'PF':>5} {'Trade':>6} {'Calmar':>7}")
    print(f"  {'-'*86}")
    rows = []
    for name, kw in configs:
        r = run_multi(D, **kw); r["name"] = name; rows.append(r)
        print(f"  {name:<20} ${r['equity']:>7,.0f} ${r['net']:>+7,.0f} "
              f"{r['roi']:>+6.0f}% ${r['avg_mth']:>+7,.0f} {r['mdd']:>6.1f}% "
              f"{r['pf']:>5.2f} {r['n']:>6} {r['calmar']:>7.2f}")

    best_mth = max(rows, key=lambda x: x["avg_mth"])
    best_cal = max(rows, key=lambda x: (x["calmar"] if not np.isnan(x["calmar"]) else -1))
    print(f"\n  >> En yüksek AYLIK ORT. kâr: {best_mth['name']}  "
          f"(${best_mth['avg_mth']:+,.0f}/ay, DD {best_mth['mdd']:.1f}%)")
    print(f"  >> En iyi risk-ayarlı:       {best_cal['name']}  "
          f"(Calmar {best_cal['calmar']:.2f})")
    print(f"\n  NOT: 4 aylık tek rejim (2025 boğa kuyruğu). Yön gösterici, kesin değil.")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
