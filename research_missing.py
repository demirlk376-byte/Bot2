"""
research_missing.py

12 aylik arastirmanin sonunda ne eksik, ne yanlis, ne fazla:

YANLIS: Yalnizca GIRIS filtrelerini optimize ettik. Sistemimiz giris + sabit cikis.
        Her filtreleme denemesi trade sayisini azaltti, toplam PnL'i dusurdu.

EKSIK 1: KISMI CIKIS (buyuk fark)
  TP1 = 3xATR'de yari pozisyonu kapat, SL'yi entry'e cek.
  Simdi kaybeden bazi tradeler "break-even" olabilir.
  Simdi kazanan bazi tradeler TP1 + break-even yerine TP1 + TP2 olabilir.
  1M data ile tam izlenebilir.

EKSIK 2: SEANS FILTRESI (hic test edilmedi)
  BB sinyali Asya / Londra / NY seansinda mi atiyor? WR farkli mi?

EKSIK 3: ATR PERCENTILE (mutlak deger degil, goreli rank)
  ATR < 20. percentil = chop → atla
  ATR > 90. percentil = spike/haber → atla
  20-90: normal

EKSIK 4: ARDISIK KAYIP SONRASI BOYUT YARIM
  3 ardisik kayiptan sonra risk yariya in. (risk yonetimi, giris filtresi degil)

FAZLA: Gittikce daha az trade uretiyor binary filtreler.
  "Az trade = iyi" degil. Kaliteli filtreye ihtiyac var, miktar killesini degil.

Run: python research_missing.py
"""
from __future__ import annotations

import glob
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import bollinger_bands, atr

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.03
SL_M  = 3.0
TP_M  = 5.0
MH    = 48
SPLIT = pd.Timestamp("2026-01-01")


# ── Data ──────────────────────────────────────────────────────────────────────

def load_both():
    files_1m = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files_1m:
        df = pd.read_csv(f)
        df = df.rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    df_1m = (pd.concat(frames, ignore_index=True)
             .drop_duplicates(subset="ts").sort_values("ts"))
    df_1m.index = pd.to_datetime(df_1m["ts"], unit="ms")
    df_1m = df_1m.drop(columns=["ts"])

    df_1h = df_1m.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()

    return df_1m, df_1h


# ── BB sinyallerini bul (baseline mantigi) ────────────────────────────────────

def find_bb_signals(df_1h):
    """
    Baseline sinyalleri bul ve metadata'yi kaydet.
    Her sinyal: ts, direction, entry, sl, tp, atr_val, hour_utc
    """
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan))
    atr_ma = atr_s.rolling(200).mean()   # for percentile

    signals = []
    warmup = 60
    for i in range(warmup, len(df_1h)):
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
        sl_d = SL_M * a

        # ATR percentile: rank of current ATR vs last 200 bars
        atr_window = atr_s.iloc[max(0, i-200):i+1].dropna().values
        pct_rank = (atr_window < a).mean() if len(atr_window) > 0 else 0.5

        signals.append({
            "ts":        df_1h.index[i],
            "i":         i,
            "direction": direction,
            "entry":     ep,
            "sl":        ep - direction * sl_d,
            "tp":        ep + direction * TP_M * a,
            "tp1":       ep + direction * 3.0 * a,   # partial TP1 at 3xATR
            "atr":       a,
            "atr_pct":   pct_rank,
            "hour_utc":  df_1h.index[i].hour,
        })
    return signals


# ── EKSIK 1: Kismi Cikis (1M data ile izle) ──────────────────────────────────

def run_partial_exit(signals, df_1m, tp1_mult=3.0, tp2_mult=5.0, max_hold_h=48):
    """
    Kısmi çıkış: TP1'de %50 kapat + SL=entry, TP2'de kalan %50.

    ÖNEMLİ: Açık pozisyon varken yeni sinyal alınmaz (baseline ile aynı kural).
    TP1/TP2 1M bar granülaritesiyle izlenir.
    """
    trades = []
    balance = BAL
    open_until = pd.Timestamp("2000-01-01")   # son trade bitis zamani

    for sig in signals:
        ts_entry = sig["ts"]
        if ts_entry <= open_until:
            continue   # önceki trade hala acik

        direction  = sig["direction"]
        entry      = sig["entry"]
        a          = sig["atr"]
        sl1        = entry - direction * SL_M * a
        tp1_price  = entry + direction * tp1_mult * a
        tp2_price  = entry + direction * tp2_mult * a

        qty = min(
            round((balance * RISK) / (entry * SL_M * a / entry), 3),
            balance * 0.5 / entry
        )
        if qty < 0.001:
            continue

        # 1M barlar: entry kapanisindan sonraki max_hold_h saat
        ts_end = ts_entry + pd.Timedelta(hours=max_hold_h)
        future = df_1m.loc[ts_entry:ts_end]
        if len(future) < 2:
            continue
        future = future.iloc[1:]   # entry bari dahil etme

        half_qty    = qty / 2.0
        half_closed = False
        sl_curr     = sl1
        rem_qty     = qty
        accum_pnl   = 0.0
        ts_close    = ts_end

        for ts_bar, bar in future.iterrows():
            hi = bar["high"]; lo = bar["low"]; cl = bar["close"]

            if not half_closed:
                hit_sl  = (direction == 1 and lo <= sl_curr) or \
                           (direction == -1 and hi >= sl_curr)
                hit_tp1 = (direction == 1 and hi >= tp1_price) or \
                           (direction == -1 and lo <= tp1_price)
                if hit_sl and hit_tp1:
                    hit_sl = True; hit_tp1 = False   # konservatif: SL önce

                if hit_sl:
                    ep = sl_curr
                    accum_pnl += direction * (ep - entry) * rem_qty \
                                 - (entry + ep) * rem_qty * COST
                    ts_close = ts_bar; break

                if hit_tp1:
                    ep1 = tp1_price
                    accum_pnl += direction * (ep1 - entry) * half_qty \
                                 - (entry + ep1) * half_qty * COST
                    half_closed = True
                    sl_curr = entry          # break-even
                    rem_qty = half_qty
            else:
                hit_sl2 = (direction == 1 and lo <= sl_curr) or \
                           (direction == -1 and hi >= sl_curr)
                hit_tp2 = (direction == 1 and hi >= tp2_price) or \
                           (direction == -1 and lo <= tp2_price)
                if hit_sl2 and hit_tp2:
                    hit_tp2 = True; hit_sl2 = False  # BE'de TP önce

                if hit_tp2:
                    ep2 = tp2_price
                    accum_pnl += direction * (ep2 - entry) * rem_qty \
                                 - (entry + ep2) * rem_qty * COST
                    ts_close = ts_bar; break

                if hit_sl2:
                    ep2 = sl_curr
                    accum_pnl += direction * (ep2 - entry) * rem_qty \
                                 - (entry + ep2) * rem_qty * COST
                    ts_close = ts_bar; break
        else:
            # Max-hold: kalan pozisyonu kapat
            if len(future) > 0:
                ep = future.iloc[-1]["close"]
                accum_pnl += direction * (ep - entry) * rem_qty \
                             - (entry + ep) * rem_qty * COST

        balance += accum_pnl
        open_until = ts_close
        trades.append({
            "ts":       ts_entry,
            "ts_exit":  ts_close,
            "pnl":      accum_pnl,
            "half_win": half_closed and accum_pnl > 0 and not (
                        accum_pnl > direction * (tp2_price - entry) * half_qty * 0.9),
        })

    return trades


# ── EKSIK 2: Seans filtresi analizi ──────────────────────────────────────────

SESSION_MAP = {
    "Asia":   list(range(0, 8)),      # 00-08 UTC
    "London": list(range(8, 13)),     # 08-13 UTC
    "Overlap":list(range(13, 16)),    # 13-16 UTC (Lon+NY)
    "NY":     list(range(16, 21)),    # 16-21 UTC
    "Dead":   list(range(21, 24)),    # 21-24 UTC
}

def session_of(hour):
    for name, hours in SESSION_MAP.items():
        if hour in hours:
            return name
    return "Unknown"


def analyze_sessions(signals):
    by_session = defaultdict(list)
    for s in signals:
        sess = session_of(s["hour_utc"])
        by_session[sess].append(s)
    return by_session


# ── EKSIK 3: ATR percentile filtresi ─────────────────────────────────────────

def run_atr_pct_filter(signals, df_1h, low_pct=20, high_pct=90):
    """
    ATR percentile disminda olan sinyalleri atla.
    low_pct altindaki sinyaller: chop (zayif volatilite)
    high_pct ustundeki sinyaller: spike / haber
    """
    filtered = [s for s in signals
                if low_pct / 100 <= s["atr_pct"] <= high_pct / 100]
    return filtered


# ── EKSIK 4: Ardisik kayip sonrasi risk yariya ────────────────────────────────

def run_consec_loss_halving(signals, df_1h):
    """
    3 ardisik kayiptan sonra risk 0.015'e iner (3%'dan yariya).
    Kazanc gelince normal'e doner.
    """
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan))

    c  = df_1h["close"].values; h = df_1h["high"].values; lo = df_1h["low"].values
    vol = df_1h["volume"].values

    warmup = 60; balance = BAL; open_t = None; trades = []
    consec_losses = 0; risk_now = RISK

    for i in range(warmup, len(df_1h)):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]
            qty = open_t["qty"]; held = i - open_t["i"]
            ep = None; reason = None
            if d == 1:
                if lo[i] <= sl: ep, reason = sl, "sl"
                elif h[i] >= tp: ep, reason = tp, "tp"
            else:
                if h[i] >= sl: ep, reason = sl, "sl"
                elif lo[i] <= tp: ep, reason = tp, "tp"
            if ep is None and held >= MH: ep, reason = c[i], "mh"
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                if pnl < 0:
                    consec_losses += 1
                    if consec_losses >= 3:
                        risk_now = RISK * 0.5  # yariya in
                else:
                    consec_losses = 0
                    risk_now = RISK            # normale don
                trades.append({"ts": df_1h.index[i], "pnl": pnl, "reason": reason,
                                "risk_used": open_t["risk_used"]})
                open_t = None
            continue

        bpos = bb_pos.iloc[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        if np.isnan(vol_ma.iloc[i]) or vol[i] < vol_ma.iloc[i]:
            continue

        direction = 1 if bpos < 0 else -1
        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = round((balance * risk_now) / (ep * (sl_d / ep)), 3)
        qty = min(qty, balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty,
                  "risk_used": risk_now}
    return trades


# ── Baseline referans ─────────────────────────────────────────────────────────

def run_baseline(df_1h):
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan))
    c = df_1h["close"].values; h = df_1h["high"].values; lo = df_1h["low"].values
    vol = df_1h["volume"].values
    warmup = 60; balance = BAL; open_t = None; trades = []
    for i in range(warmup, len(df_1h)):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]
            qty = open_t["qty"]; held = i - open_t["i"]
            ep = None; reason = None
            if d == 1:
                if lo[i] <= sl: ep, reason = sl, "sl"
                elif h[i] >= tp: ep, reason = tp, "tp"
            else:
                if h[i] >= sl: ep, reason = sl, "sl"
                elif lo[i] <= tp: ep, reason = tp, "tp"
            if ep is None and held >= MH: ep, reason = c[i], "mh"
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                trades.append({"ts": open_t["ts"], "pnl": pnl, "reason": reason,
                               "hour_utc": open_t["ts"].hour})
                open_t = None
            continue
        bpos = bb_pos.iloc[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        if np.isnan(vol_ma.iloc[i]) or vol[i] < vol_ma.iloc[i]:
            continue
        direction = 1 if bpos < 0 else -1
        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = round((balance * RISK) / (ep * (sl_d / ep)), 3)
        qty = min(qty, balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}
    return trades


# ── Stats ─────────────────────────────────────────────────────────────────────

def stat(tt, label, width=60):
    if not tt:
        return f"{label:<{width}} 0t"
    p  = np.array([t["pnl"] for t in tt])
    wr = (p > 0).mean()
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf  = pos / neg if neg > 0 else float("inf")
    eq  = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd  = ((pk - eq) / pk).max()
    tr  = [t for t in tt if t["ts"] < SPLIT]
    te  = [t for t in tt if t["ts"] >= SPLIT]
    tp_ = np.array([t["pnl"] for t in tr]) if tr else np.array([0.0])
    te_ = np.array([t["pnl"] for t in te]) if te else np.array([0.0])
    return (f"{label:<{width}} {len(p):>3}t WR{wr:.0%} PF{pf:.2f} "
            f"${p.sum():>+8.0f}({p.sum()/100:>+.1f}%) DD{dd*100:.1f}% "
            f"| TR WR{(tp_>0).mean():.0%} ${tp_.sum():>+6.0f}"
            f"| TE WR{(te_>0).mean():.0%} ${te_.sum():>+6.0f}")


def main():
    print("Veri yukleniyor (1M + 1H)…")
    df_1m, df_1h = load_both()
    print(f"1H: {len(df_1h)} bar | 1M: {len(df_1m)} bar")
    print("=" * 130)

    # Baseline
    baseline = run_baseline(df_1h)
    print(stat(baseline, "BASELINE (1H BB + vol + 3% risk)"))
    print()

    # Sinyalleri bul
    signals = find_bb_signals(df_1h)
    print(f"Toplam BB sinyali: {len(signals)}")
    print()

    # ── EKSIK 1: Kismi Cikis ─────────────────────────────────────────────────
    print("═══ EKSIK 1: Kismi Cikis — TP1@3xATR→%50 kapat, SL=entry; TP2@5xATR ══════════════")
    pe_trades = run_partial_exit(signals, df_1m, tp1_mult=3.0, tp2_mult=5.0)
    print(stat(pe_trades, "  Kismi cikis (TP1=3xATR, TP2=5xATR)"))

    # Kac trade half-win oldu?
    hw = sum(1 for t in pe_trades if t.get("half_win"))
    full_win = sum(1 for t in pe_trades if t["pnl"] > 0 and not t.get("half_win"))
    full_loss = sum(1 for t in pe_trades if t["pnl"] < 0)
    print(f"  Dagilim: {full_loss} tam kayip | {hw} yari kazanc | {full_win} tam kazanc")

    # Farkli TP1 noktalari
    for tp1_m in [2.0, 2.5, 3.0, 4.0]:
        t = run_partial_exit(signals, df_1m, tp1_mult=tp1_m, tp2_mult=5.0)
        print(stat(t, f"  Kismi cikis TP1={tp1_m}xATR TP2=5xATR"))
    print()

    # ── EKSIK 2: Seans Filtresi ───────────────────────────────────────────────
    print("═══ EKSIK 2: Seans Filtresi Analizi (hangi saatte BB signal daha guclü?) ════════")
    # baseline trades artık entry timestamp (ts) ve hour_utc içeriyor
    by_sess = defaultdict(list)
    for t in baseline:
        sess = session_of(t["hour_utc"])
        by_sess[sess].append(t)

    for sess_name, sess_trades in sorted(by_sess.items(), key=lambda x: len(x[1]), reverse=True):
        if not sess_trades:
            continue
        pnl = np.array([t["pnl"] for t in sess_trades])
        hours = sorted(set(t["hour_utc"] for t in sess_trades))
        print(f"  {sess_name:<10} {len(sess_trades):>3} trade "
              f"WR{(pnl>0).mean():.0%} ${pnl.sum():>+7.0f} "
              f"| saatler: {hours[0]:02d}-{hours[-1]+1:02d} UTC")

    # Seans bazli filtre: dead zone ve abnormal saatleri atla
    dead_hours = set(range(21, 24)) | {0}  # 21-01 UTC
    asia_only = set(range(1, 7))

    for label, hours_ok in [("dead zone atla (21-01 UTC)", set(range(1, 21))),
                             ("sadece London+NY (08-21 UTC)", set(range(8, 21))),
                             ("sadece Overlap (13-16 UTC)", set(range(13, 16))),
                             ("London+Overlap (08-16 UTC)", set(range(8, 16)))]:
        filtered_trades = [t for t in baseline if t["hour_utc"] in hours_ok]
        print(stat(filtered_trades, f"  {label}", width=50))
    print()

    # ── EKSIK 3: ATR Percentile Filtresi ─────────────────────────────────────
    print("═══ EKSIK 3: ATR Percentile Filtresi (chop ve spike'i atla) ════════════════════")
    # ATR percentile baseline trades üzerinde uygula
    # Sinyal timestamp → ATR percentile lookup
    sig_atr_pct = {s["ts"]: s["atr_pct"] for s in signals}
    for lo_p, hi_p in [(0, 100), (20, 80), (20, 90), (30, 85), (10, 95)]:
        filtered_trades = [t for t in baseline
                           if lo_p/100 <= sig_atr_pct.get(t["ts"], 0.5) <= hi_p/100]
        label = f"  ATR percentile {lo_p}-{hi_p}%"
        print(stat(filtered_trades, label))
    print()

    # ── EKSIK 4: Ardisik Kayip Sonrasi Risk Yariya ───────────────────────────
    print("═══ EKSIK 4: Ardisik Kayip Sonrasi Risk Yariya (risk yonetimi) ════════════════")
    cl_trades = run_consec_loss_halving(signals, df_1h)
    print(stat(cl_trades, "  Ardisik kayip 3+ → risk yariya", width=50))
    print()

    # ── Seans + ATR percentile birlikte ──────────────────────────────────────
    print("═══ Kombine: Seans + ATR percentile (en umut verici ikili) ═════════════════════")
    for sess_hours, lo_p, hi_p, lbl in [
        (range(8, 21), 20, 90, "London+NY AND ATR pct 20-90%"),
        (range(8, 21), 10, 95, "London+NY AND ATR pct 10-95%"),
        (range(13, 16), 20, 90, "Overlap AND ATR pct 20-90%"),
        (range(8, 16),  20, 90, "London+Overlap AND ATR pct 20-90%"),
    ]:
        filtered_trades = [t for t in baseline
                           if t["hour_utc"] in sess_hours
                           and lo_p/100 <= sig_atr_pct.get(t["ts"], 0.5) <= hi_p/100]
        print(stat(filtered_trades, f"  {lbl}"))
    print()

    # ── Kismi Cikis (duzeltilmis) ────────────────────────────────────────────
    print("═══ Duzeltilmis Kismi Cikis (tek pozisyon kurali) ══════════════════════════════")
    for tp1_m in [2.5, 3.0, 3.5, 4.0]:
        pe = run_partial_exit(signals, df_1m, tp1_mult=tp1_m, tp2_mult=5.0)
        hw = sum(1 for t in pe if t.get("half_win"))
        print(stat(pe, f"  TP1={tp1_m}xATR TP2=5xATR") + f"  ({hw} yari kazanc)")
    print()

    # ── Ozet ─────────────────────────────────────────────────────────────────
    print("═══ Ozet ═══════════════════════════════════════════════════════════════════════")
    print(stat(baseline, "  BASELINE"))
    print()
    print("  Neyi yanlis yapiyoruz:")
    print("  1. Entry filtrelerine odaklanip cikis yonetimini hic test etmedik.")
    print("  2. Binary 'al/atla' → graduel risk boyutlandirmasi daha dogru.")
    print("  3. Seans farkindaliği eksikti (hangi saatte edge var?).")
    print()
    print("  En umit verici yonler (OHLCV'den elde edilebilir):")
    print("  a) Kismi cikis (TP1@3xATR) — tam kayiplerin bir kismi yari kazanca donebilir")
    print("  b) Seans filtresi — dead zone sinyallerinde edge zayif olabilir")
    print("  c) ATR percentile — chop ve spike donemlerinde skip")
    print()
    print("  OHLCV tavanini gecmek icin hala gereken: live funding/OI, order book depth.")


if __name__ == "__main__":
    main()
