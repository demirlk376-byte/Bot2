"""
research_bb_filters.py — BB mean-reversion filtre optimizasyonu

Sadece BB sleeve'ini izole edip farklı filtre kombinasyonlarını
2023 / 2024 / 2025-26 üç dönemde test eder. Amaç: BB'yi PF>1.0'a çıkarmak.

Test edilen filtreler:
  - sniper grade ≥ N  (ATR%≥50, overshoot<0.5, VWAP yönlü mesafe≥%0.5)
  - TP varyantları: 5×ATR (mevcut) / 3×ATR / 2×ATR / orta band (mean)
  - ADX trending eşiği: 28 (mevcut) / 22

Diğer her şey research_2year.py ile birebir aynı (margin, lot, fee, cooldown).
"""
from __future__ import annotations
import glob, sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr, adx as _adx_ind, vwap, atr_percentile

COST_MAKER = 0.0
COST_TAKER = 0.0001
LEVERAGE   = 10
MIN_LOT    = 0.001
START      = 200.0

BB_RISK = 0.08
BB_SL   = 3.0
BB_MH   = 48
DAILY_MAX_LOSS = 0.35
CONSEC_LIMIT   = 2
COOLDOWN_HOURS = 4


def load_period(year_months):
    frames = []
    for ym in year_months:
        for f in sorted(glob.glob(f"/home/user/Bot2/BTCUSDT-1m-{ym}.csv")):
            df = pd.read_csv(f)
            df.columns = ["ts","open","high","low","close","volume",
                          "ct","qv","count","tbv","tbqv","ign"]
            frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    if not frames:
        return pd.DataFrame()
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms", utc=True)
    return full.drop(columns=["ts"])


def resample_1h(df):
    return df.resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def size_qty(risk_pct, balance, free_margin, ep, sl_dist):
    if sl_dist <= 0 or free_margin <= 0:
        return 0.0, 0.0
    qty = (balance * risk_pct) / sl_dist
    qty = min(qty, free_margin * LEVERAGE / ep)
    qty = round(qty, 3)
    if qty < MIN_LOT:
        return 0.0, 0.0
    margin = qty * ep / LEVERAGE
    if margin > free_margin + 1e-9:
        return 0.0, 0.0
    return qty, margin


def run_bb(df_1m, cfg):
    """BB-only sim. cfg: dict(sniper, tp_mode, tp_mult, adx_thr, day_mode)."""
    df = resample_1h(df_1m)
    if len(df) < 100:
        return []

    close  = df["close"].values
    high_v = df["high"].values
    low_v  = df["low"].values
    vol    = df["volume"].values
    idx    = df.index

    upper_s, mid_s, lower_s = bollinger_bands(df["close"], 20, 2.0)
    atr_s  = atr(df["high"], df["low"], df["close"], 14)
    adx_s  = _adx_ind(df["high"], df["low"], df["close"], 14)
    vol_ma = df["volume"].rolling(20).mean()
    bb_pos_s = ((df["close"] - lower_s) / (upper_s - lower_s).replace(0, np.nan))
    atrpct_s = atr_percentile(df["high"], df["low"], df["close"], 14, 50)
    vwap_s   = vwap(df["high"], df["low"], df["close"], df["volume"], 24)

    atr_a   = atr_s.values
    adx_a   = adx_s.values
    volma_a = vol_ma.values
    bb_a    = bb_pos_s.values
    mid_a   = mid_s.values
    atrp_a  = atrpct_s.values
    vwap_a  = vwap_s.values

    n = len(close); warmup = 65
    dates_a = np.array([ts.date() for ts in idx])
    wday_a  = np.array([ts.weekday() for ts in idx])  # 5,6 = hafta sonu

    balance = START; used_margin = 0.0
    daily_start = START; daily_date = None
    bb_o = None
    consec = 0; cooldown = None
    trades = []

    sniper_min = cfg["sniper"]
    tp_mode    = cfg["tp_mode"]
    tp_mult    = cfg["tp_mult"]
    adx_thr    = cfg["adx_thr"]
    day_mode   = cfg.get("day_mode", "all")  # all / weekend / weekday

    def free(): return balance - used_margin

    for i in range(warmup, n):
        a_val = atr_a[i]
        if np.isnan(a_val) or a_val <= 0:
            continue
        cd = dates_a[i]; now_ts = idx[i]

        if cd != daily_date:
            daily_date = cd
            daily_start = balance + used_margin

        # kapanış
        if bb_o is not None:
            d = bb_o["dir"]; entry = bb_o["entry"]
            sl = bb_o["sl"]; tp = bb_o["tp"]; qty = bb_o["qty"]
            held = i - bb_o["i"]
            ep_exit = None; reason = None
            if d == 1:
                if low_v[i] <= sl:   ep_exit, reason = sl, "sl"
                elif high_v[i] >= tp: ep_exit, reason = tp, "tp"
            else:
                if high_v[i] >= sl:  ep_exit, reason = sl, "sl"
                elif low_v[i] <= tp:  ep_exit, reason = tp, "tp"
            if ep_exit is None and held >= BB_MH:
                ep_exit, reason = close[i], "mh"
            if ep_exit is not None:
                raw = d * (ep_exit - entry) * qty
                fee = entry * qty * COST_MAKER + ep_exit * qty * COST_TAKER
                pnl = raw - fee
                balance += pnl; used_margin -= bb_o["margin"]
                trades.append({"pnl": pnl, "reason": reason})
                if pnl < 0:
                    consec += 1
                    if consec >= CONSEC_LIMIT:
                        cooldown = now_ts + pd.Timedelta(hours=COOLDOWN_HOURS)
                else:
                    consec = 0
                bb_o = None

        equity = balance + used_margin
        if daily_start > 0 and (daily_start - equity) / daily_start >= DAILY_MAX_LOSS:
            continue

        adx_val = adx_a[i]
        trending = not np.isnan(adx_val) and adx_val >= adx_thr

        is_weekend = wday_a[i] >= 5
        day_ok = (day_mode == "all" or
                  (day_mode == "weekend" and is_weekend) or
                  (day_mode == "weekday" and not is_weekend))

        if bb_o is None and not trending and day_ok:
            if cooldown is None or now_ts >= cooldown:
                if cooldown is not None and now_ts >= cooldown:
                    cooldown = None
                bpos = bb_a[i]; vm = volma_a[i]
                if not np.isnan(bpos) and (bpos < 0.0 or bpos > 1.0):
                    if np.isnan(vm) or vol[i] >= vm:
                        direction = 1 if bpos < 0.0 else -1

                        # sniper grade
                        if sniper_min > 0:
                            score = 0
                            ap = atrp_a[i]
                            if not np.isnan(ap) and ap >= 50:
                                score += 1
                            overshoot = abs(bpos) if direction == 1 else abs(bpos - 1.0)
                            if overshoot < 0.5:
                                score += 1
                            vw = vwap_a[i]
                            if not np.isnan(vw) and vw > 0:
                                dev = (close[i] - vw) / vw
                                edge = (-dev if direction == 1 else dev) * 100
                                if edge >= 0.5:
                                    score += 1
                            if score < sniper_min:
                                continue

                        ep = close[i]
                        sl_dist = BB_SL * a_val
                        qty, mg = size_qty(BB_RISK, balance, free(), ep, sl_dist)
                        if qty > 0:
                            used_margin += mg
                            # TP modu
                            if tp_mode == "atr":
                                tp = ep + direction * tp_mult * a_val
                            else:  # "mid" → orta banda dönüş
                                tp = mid_a[i]
                                # geçersizse ATR fallback
                                if np.isnan(tp) or (direction == 1 and tp <= ep) or \
                                   (direction == -1 and tp >= ep):
                                    tp = ep + direction * 2.0 * a_val
                            bb_o = {
                                "i": i, "dir": direction, "entry": ep,
                                "sl": ep - direction * sl_dist,
                                "tp": tp, "qty": qty, "margin": mg,
                            }
    return trades


def stats(trades):
    if not trades:
        return {"n":0,"wr":0,"pf":0,"net":0}
    p = [t["pnl"] for t in trades]
    pos = sum(x for x in p if x > 0)
    neg = sum(-x for x in p if x < 0)
    return {"n":len(p), "wr":sum(1 for x in p if x>0)/len(p),
            "pf":pos/neg if neg>0 else 999, "net":sum(p)}


def main():
    print("Veri yükleniyor…", flush=True)
    df23 = load_period([f"2023-{m:02d}" for m in range(1,13)])
    df24 = load_period([f"2024-{m:02d}" for m in range(1,13)])
    df25 = load_period([f"2025-{m:02d}" for m in range(5,13)] +
                       [f"2026-{m:02d}" for m in range(1,5)])
    print(f"  2023:{len(df23):,}  2024:{len(df24):,}  2025-26:{len(df25):,}\n")

    configs = [
        ("MEVCUT (sniper0, TP5atr, ADX28)",  dict(sniper=0, tp_mode="atr", tp_mult=5.0, adx_thr=28)),
        ("sniper≥2, TP5atr, ADX28",          dict(sniper=2, tp_mode="atr", tp_mult=5.0, adx_thr=28)),
        ("sniper0, TP3atr, ADX28",           dict(sniper=0, tp_mode="atr", tp_mult=3.0, adx_thr=28)),
        ("sniper0, TP2atr, ADX28",           dict(sniper=0, tp_mode="atr", tp_mult=2.0, adx_thr=28)),
        ("sniper0, TP=ortaband, ADX28",      dict(sniper=0, tp_mode="mid", tp_mult=0,   adx_thr=28)),
        ("sniper0, TP5atr, ADX22",           dict(sniper=0, tp_mode="atr", tp_mult=5.0, adx_thr=22)),
        ("sniper≥2, TP3atr, ADX22",          dict(sniper=2, tp_mode="atr", tp_mult=3.0, adx_thr=22)),
        ("sniper≥2, TP=ortaband, ADX22",     dict(sniper=2, tp_mode="mid", tp_mult=0,   adx_thr=22)),
        ("sniper≥3, TP3atr, ADX28",          dict(sniper=3, tp_mode="atr", tp_mult=3.0, adx_thr=28)),
        ("HAFTA İÇİ (sadece Pzt-Cum)",       dict(sniper=0, tp_mode="atr", tp_mult=5.0, adx_thr=28, day_mode="weekday")),
        ("HAFTA SONU (sadece Cmt-Paz)",      dict(sniper=0, tp_mode="atr", tp_mult=5.0, adx_thr=28, day_mode="weekend")),
        ("HAFTA SONU + sniper≥2",            dict(sniper=2, tp_mode="atr", tp_mult=5.0, adx_thr=28, day_mode="weekend")),
    ]

    periods = [("2023", df23), ("2024", df24), ("2025-26", df25)]

    print("="*92)
    print("  BB FİLTRE TARAMASI — Profit Factor / Trade sayısı / Net $ (her dönem ayrı)")
    print("="*92)
    hdr = f"  {'Konfig':<34s}"
    for pn,_ in periods:
        hdr += f"  {pn+' PF':>9s} {'n':>4s}"
    hdr += f"  {'ORT PF':>7s}"
    print(hdr)
    print("  " + "-"*90)

    for label, cfg in configs:
        row = f"  {label:<34s}"
        pfs = []
        for pn, dfp in periods:
            t = run_bb(dfp, cfg)
            s = stats(t)
            pfs.append(s["pf"] if s["n"] > 0 else 0)
            flag = "✓" if s["pf"] >= 1.0 else " "
            row += f"  {s['pf']:>7.2f}{flag} {s['n']:>4d}"
        avg_pf = sum(pfs)/len(pfs)
        row += f"  {avg_pf:>7.2f}"
        print(row, flush=True)

    print("\n  ✓ = o dönemde PF≥1.0 (kârlı). Hedef: 3 dönemde de ✓ olan konfig.")
    print("  Not: ORB/Asia BO değişmiyor — bunlar sadece BB sleeve içindir.")


if __name__ == "__main__":
    main()
