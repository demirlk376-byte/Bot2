"""
research_mgmt.py

POZISYON YONETIMI — SL'ye giden tradeleri kurtarma denemeleri.

Soru: SL hit oranimiz %47. Bu tradelerin bir kismi once lehte hareket edip
sonra geri donuyor olabilir. Eger:
  - lehte X×ATR gidince SL'yi break-even'e cekersek → kayip yerine sifir
  - veya trailing stop kullanirsak → kazananin bir kismini kilitleriz
  - veya erken ters giden tradeleri kesersek → buyuk kayiptan kacariz
toplam sonuc duzelir mi?

ONEMLI: Her sey 1M bar ile gercek intra-trade path uzerinden izlenir.
Tek pozisyon kurali (acikken yeni sinyal yok), train/test split korunur.

Baseline: SL=3×ATR TP=5×ATR → 238t WR47% +28.2%

Run: python research_mgmt.py
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.03
SL_M  = 3.0
TP_M  = 5.0
MH    = 48            # max hold saat
SPLIT = pd.Timestamp("2026-01-01")


# ── Data ──────────────────────────────────────────────────────────────────────

def load_both():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df = df.rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    df_1m = (pd.concat(frames, ignore_index=True)
             .drop_duplicates(subset="ts").sort_values("ts"))
    df_1m.index = pd.to_datetime(df_1m["ts"], unit="ms")
    df_1m = df_1m.drop(columns=["ts"])
    df_1h = df_1m.resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()
    return df_1m, df_1h


def find_bb_signals(df_1h):
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan))
    signals = []
    for i in range(60, len(df_1h)):
        bpos = bb_pos.iloc[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        vol = df_1h["volume"].iloc[i]; vma = vol_ma.iloc[i]
        if np.isnan(vma) or vol < vma:
            continue
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        direction = 1 if bpos < 0 else -1
        ep = df_1h["close"].iloc[i]
        signals.append({
            "ts": df_1h.index[i], "direction": direction,
            "entry": ep, "atr": a,
        })
    return signals


# ── Genel simulator: per-trade 1M path, esnek yonetim kurali ───────────────────

def simulate(signals, df_1m, manage, max_hold_h=MH):
    """
    manage(state, bar) -> her 1M barda cagrilir, opsiyonel cikis dondurur.
    Burada bunun yerine yonetim parametrelerini dogrudan ele aliyoruz; manage
    bir dict olarak gelir ve hangi tekniklerin aktif oldugunu belirler.
    """
    trades = []
    balance = BAL
    open_until = pd.Timestamp("2000-01-01")

    be_trigger   = manage.get("be_trigger")    # X×ATR lehte gidince SL→entry
    be_lock      = manage.get("be_lock", 0.0)  # SL→entry + lock×ATR
    trail_act    = manage.get("trail_act")     # trailing aktivasyon X×ATR
    trail_dist   = manage.get("trail_dist")    # trailing mesafe X×ATR
    cut_adverse  = manage.get("cut_adverse")   # ilk N barda Y×ATR ters→kes
    cut_bars     = manage.get("cut_bars", 0)
    cut_need_fav = manage.get("cut_need_fav", 0.0)  # bu kadar lehte gitmediyse

    for sig in signals:
        ts_entry  = sig["ts"]
        if ts_entry <= open_until:
            continue
        direction = sig["direction"]
        entry     = sig["entry"]
        a         = sig["atr"]
        sl0       = entry - direction * SL_M * a
        tp        = entry + direction * TP_M * a

        qty = min(
            round((balance * RISK) / (entry * SL_M * a / entry), 3),
            balance * 0.5 / entry
        )
        if qty < 0.001:
            continue

        ts_end = ts_entry + pd.Timedelta(hours=max_hold_h)
        future = df_1m.loc[ts_entry:ts_end]
        if len(future) < 2:
            continue
        future = future.iloc[1:]

        sl_curr   = sl0
        peak_fav  = 0.0          # max lehte hareket (×ATR cinsinden degil, fiyat)
        ep = None; reason = None
        bar_idx = 0

        for ts_bar, bar in future.iterrows():
            hi = bar["high"]; lo = bar["low"]; cl = bar["close"]
            bar_idx += 1

            # lehte hareket (favorable excursion) — bu barin uc noktasi
            fav_price = hi if direction == 1 else lo
            fav = direction * (fav_price - entry)        # >0 lehte
            if fav > peak_fav:
                peak_fav = fav

            # --- erken kesme: ilk cut_bars barda yeterince lehte gitmeyip
            #     cut_adverse×ATR ters gittiyse, market'ten cik ---
            if cut_adverse is not None and bar_idx <= cut_bars:
                adv_price = lo if direction == 1 else hi
                adv = direction * (entry - adv_price)    # >0 ters
                if adv >= cut_adverse * a and peak_fav < cut_need_fav * a:
                    ep, reason = cl, "cut"
                    break

            # --- break-even: lehte be_trigger×ATR gidince SL'yi cek ---
            if be_trigger is not None and peak_fav >= be_trigger * a:
                new_sl = entry + direction * be_lock * a
                if direction == 1:
                    sl_curr = max(sl_curr, new_sl)
                else:
                    sl_curr = min(sl_curr, new_sl)

            # --- trailing stop: trail_act×ATR sonrasi peak'ten trail_dist×ATR ---
            if trail_act is not None and peak_fav >= trail_act * a:
                trail_sl = entry + direction * (peak_fav - trail_dist * a)
                if direction == 1:
                    sl_curr = max(sl_curr, trail_sl)
                else:
                    sl_curr = min(sl_curr, trail_sl)

            # --- exit kontrolu (SL once, konservatif) ---
            hit_sl = (direction == 1 and lo <= sl_curr) or \
                     (direction == -1 and hi >= sl_curr)
            hit_tp = (direction == 1 and hi >= tp) or \
                     (direction == -1 and lo <= tp)
            if hit_sl:
                ep, reason = sl_curr, ("be" if abs(sl_curr-entry) < 1e-6 or
                                       (direction*(sl_curr-entry) >= 0) else "sl")
                break
            if hit_tp:
                ep, reason = tp, "tp"
                break

        if ep is None:
            ep, reason = future.iloc[-1]["close"], "mh"

        pnl = direction * (ep - entry) * qty - (entry + ep) * qty * COST
        balance += pnl
        # kapanis zamani
        if reason in ("sl","be","tp","cut"):
            ts_close = ts_bar
        else:
            ts_close = future.index[-1]
        open_until = ts_close
        trades.append({"ts": ts_close, "ts_entry": ts_entry,
                       "pnl": pnl, "reason": reason})
    return trades


def stat(tt, label):
    if not tt:
        return f"{label:<42} 0 trades"
    p  = np.array([t["pnl"] for t in tt])
    wr = (p > 0).mean()
    from collections import Counter
    rc = Counter(t["reason"] for t in tt)
    pos = p[p>0].sum(); neg = -p[p<0].sum()
    pf = pos/neg if neg>0 else float("inf")
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd = ((pk-eq)/pk).max()
    tr = [t for t in tt if t["ts_entry"] < SPLIT]
    te = [t for t in tt if t["ts_entry"] >= SPLIT]
    tp_ = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    te_ = np.array([t["pnl"] for t in te]) if te else np.array([])
    s_tr = f"WR{(tp_>0).mean():.0%} ${tp_.sum():>+6.0f}" if len(tp_) else "—"
    s_te = f"WR{(te_>0).mean():.0%} ${te_.sum():>+6.0f}" if len(te_) else "—"
    rc_s = " ".join(f"{k}:{v}" for k,v in sorted(rc.items()))
    return (f"{label:<42} {len(p):>3}t WR{wr:.0%} PF{pf:.2f} "
            f"${p.sum():>+7.0f} ({p.sum()/100:>+5.1f}%) DD{dd*100:.0f}% "
            f"[{rc_s}] | TR {s_tr} | TE {s_te}")


def main():
    df_1m, df_1h = load_both()
    sigs = find_bb_signals(df_1h)
    print(f"BTC 1h: {len(df_1h)} bar, {len(sigs)} ham BB sinyali  "
          f"({df_1h.index[0]:%Y-%m-%d} → {df_1h.index[-1]:%Y-%m-%d})")
    print("=" * 140)

    # 0) Baseline (yonetim yok) — 1M path ile, dogrulama icin
    print("\n[BASELINE — statik SL=3 TP=5, 1M path]\n")
    print(stat(simulate(sigs, df_1m, {}), "baseline (no mgmt)"))

    # 1) Break-even cekme — farkli tetikleyiciler
    print("\n[BREAK-EVEN — lehte X×ATR gidince SL→entry]\n")
    for trig in [1.0, 1.5, 2.0, 2.5, 3.0]:
        t = simulate(sigs, df_1m, {"be_trigger": trig, "be_lock": 0.0})
        print(stat(t, f"BE @ {trig:.1f}×ATR lehte → SL=entry"))

    # 2) Break-even + kar kilitle (SL entry'nin biraz ustune)
    print("\n[BREAK-EVEN + LOCK — SL→entry + lock×ATR]\n")
    for trig, lock in [(2.0,0.5),(2.0,1.0),(2.5,1.0),(3.0,1.0),(3.0,1.5)]:
        t = simulate(sigs, df_1m, {"be_trigger": trig, "be_lock": lock})
        print(stat(t, f"BE @ {trig:.1f} → SL=entry+{lock:.1f}×ATR"))

    # 3) Trailing stop
    print("\n[TRAILING STOP — act×ATR sonrasi peak−dist×ATR]\n")
    for act, dist in [(2.0,2.0),(2.5,2.0),(3.0,2.0),(3.0,2.5),(3.0,3.0),(4.0,2.0)]:
        t = simulate(sigs, df_1m, {"trail_act": act, "trail_dist": dist})
        print(stat(t, f"trail act={act:.1f} dist={dist:.1f}×ATR"))

    # 4) Erken kesme — ilk N barda lehte gitmeden Y×ATR ters → kes
    print("\n[ERKEN KESME — ilk N barda Y×ATR ters + lehte<F → cut]\n")
    for cb, ca, cf in [(60,1.5,0.5),(120,1.5,0.5),(120,2.0,0.5),
                       (180,2.0,0.5),(240,2.0,1.0)]:
        t = simulate(sigs, df_1m,
                     {"cut_adverse": ca, "cut_bars": cb, "cut_need_fav": cf})
        print(stat(t, f"cut: {cb}m icinde {ca:.1f}×ters & fav<{cf:.1f}"))

    # 5) Kombinasyon: BE + trailing
    print("\n[KOMBINASYON — BE @2 sonra trailing]\n")
    for trig, act, dist in [(2.0,3.0,2.0),(1.5,3.0,2.5),(2.0,4.0,2.0)]:
        t = simulate(sigs, df_1m,
                     {"be_trigger": trig, "trail_act": act, "trail_dist": dist})
        print(stat(t, f"BE@{trig:.1f} + trail act={act:.1f} d={dist:.1f}"))

    print("\nbaseline referans: 238t WR47% +28.2% DD~10%")


if __name__ == "__main__":
    main()
