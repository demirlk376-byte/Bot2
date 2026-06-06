"""
research_btcd_clean.py

BTC Dominance rejimi BB-fade edge'ini etkiliyor mu? — DÜRÜST metodoloji.

Önceki research_btcd.py'deki iki kusuru düzeltir:
  KUSUR 1: Yön filtrelerinde ham yüzde (s["dom"]=%36-57) "dom > 0" ile
           karşılaştırılıyordu → her zaman True → filtre aslında çalışmıyordu.
  KUSUR 2: Her filtre ayrı run() çağrısıyla test ediliyordu; pozisyon-boyutu
           compounding + no-overlap reshuffling yüzünden alt-grupların PnL'i
           baseline'a TOPLANMIYORDU → karşılaştırma yanıltıcıydı.

DOĞRU YÖNTEM:
  1. Baseline'ı BİR KEZ çalıştır → kanonik trade listesi (giriş ts, yön, pnl).
  2. Her trade'i GİRİŞ ANINDAKİ BTC.D seviyesi + eğimiyle etiketle.
  3. Bucket analizi yap — alt-grupların PnL'i TAM OLARAK baseline'a eşittir.
  4. Train/test split: bir sinyal hem train HEM test'te tutarlıysa gerçektir.

Bu sayede "BTC.D rejimi trade sonucunu öngörüyor mu?" sorusu önyargısız yanıtlanır.

Run: python research_btcd_clean.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import bollinger_bands, atr

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.03
SL_M  = 3.0
TP_M  = 5.0
MH    = 48
SPLIT = pd.Timestamp("2026-01-01")


# ── Veri ──────────────────────────────────────────────────────────────────────

def load_btc_1h():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"]).resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def load_btcd_1h(btc_index):
    """BTCDOMUSDT-4h-*.csv → 1h forward-fill. 100x normalize."""
    files = sorted(glob.glob("/home/user/Bot2/BTCDOMUSDT-4h-*.csv"))
    if not files:
        return None
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","close"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    btcd = full["close"]
    if btcd.max() > 100:        # Binance 100x (5028 = %50.28)
        btcd = btcd / 100.0
    return btcd.reindex(btc_index, method="ffill")


# ── Baseline: kanonik trade listesi (BİR KEZ) ─────────────────────────────────

def run_baseline(df_1h):
    """Doğrulanmış BB-fade. Her trade GİRİŞ ts'iyle kaydedilir."""
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    n = len(c); balance = BAL; open_t = None; trades = []
    for i in range(60, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]
            held = i - open_t["i"]; ep = None; reason = None
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
                trades.append({
                    "ts_entry": open_t["ts"], "ts_exit": df_1h.index[i],
                    "dir": d, "pnl": pnl, "reason": reason,
                })
                open_t = None
            continue
        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue
        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * RISK) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}
    return trades


# ── Trade'leri BTC.D rejimiyle etiketle ───────────────────────────────────────

def annotate(trades, btcd_1h):
    """
    Her trade'e GİRİŞ anındaki:
      - dom_level: BTC.D yüzdesi
      - dom_chg_24h: son 24 saatteki değişim (yüzde puan)
      - dom_chg_72h: son 72 saatteki değişim
      - dom_vs_ma20d: 20-günlük ortalamadan sapma
    """
    out = []
    for t in trades:
        ts = t["ts_entry"]
        if ts not in btcd_1h.index:
            continue
        level = btcd_1h.loc[ts]
        if np.isnan(level):
            continue
        ts_24 = ts - pd.Timedelta(hours=24)
        ts_72 = ts - pd.Timedelta(hours=72)
        ts_ma = ts - pd.Timedelta(days=20)
        chg_24 = level - btcd_1h.asof(ts_24) if ts_24 >= btcd_1h.index[0] else np.nan
        chg_72 = level - btcd_1h.asof(ts_72) if ts_72 >= btcd_1h.index[0] else np.nan
        ma20   = btcd_1h.loc[ts_ma:ts].mean() if ts_ma >= btcd_1h.index[0] else np.nan
        vs_ma  = level - ma20 if not np.isnan(ma20) else np.nan
        out.append({**t, "dom_level": level, "dom_chg_24h": chg_24,
                    "dom_chg_72h": chg_72, "dom_vs_ma20d": vs_ma})
    return out


# ── İstatistik yardımcıları ───────────────────────────────────────────────────

def summarize(trades, label):
    if not trades:
        return f"{label:<46} 0t"
    p = np.array([t["pnl"] for t in trades])
    wr = (p > 0).mean()
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    ptr = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    pte = np.array([t["pnl"] for t in te]) if te else np.array([])
    s_tr = f"WR{(ptr>0).mean():.0%} ${ptr.sum():>+6.0f}" if len(ptr) else "—"
    s_te = f"WR{(pte>0).mean():.0%} ${pte.sum():>+6.0f}" if len(pte) else "—"
    return (f"{label:<46} {len(p):>3}t WR{wr:.0%} ${p.sum():>+7.0f} "
            f"({p.sum()/100:>+5.1f}%) | TR {s_tr} | TE {s_te}")


def bucket(trades, key, edges, labels):
    """edges'e göre bucket'la, her birinin WR+PnL'i. TOPLAM = baseline."""
    print(f"\n  {key} dilimlerine göre (TOPLAM = baseline, partition dürüst):")
    print(f"  {'Dilim':<30}{'Trade':>6}{'WR':>6}{'PnL':>9}{'TR':>14}{'TE':>14}")
    total = 0.0; total_n = 0
    for i, lbl in enumerate(labels):
        grp = [t for t in trades
               if not np.isnan(t[key]) and edges[i] <= t[key] < edges[i+1]]
        if not grp:
            print(f"  {lbl:<30}{0:>6}")
            continue
        p = np.array([t["pnl"] for t in grp])
        wr = (p > 0).mean()
        tr = [t for t in grp if t["ts_entry"] < SPLIT]
        te = [t for t in grp if t["ts_entry"] >= SPLIT]
        ptr = sum(t["pnl"] for t in tr); pte = sum(t["pnl"] for t in te)
        wtr = (np.array([t["pnl"] for t in tr])>0).mean() if tr else 0
        wte = (np.array([t["pnl"] for t in te])>0).mean() if te else 0
        s_tr = f"WR{wtr:.0%} ${ptr:>+5.0f}" if tr else "—"
        s_te = f"WR{wte:.0%} ${pte:>+5.0f}" if te else "—"
        print(f"  {lbl:<30}{len(p):>6}{wr*100:>5.0f}%{p.sum():>+9.0f}"
              f"{s_tr:>14}{s_te:>14}")
        total += p.sum(); total_n += len(p)
    print(f"  {'— bucket toplamı':<30}{total_n:>6}{'':>6}{total:>+9.0f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    df_btc = load_btc_1h()
    btcd   = load_btcd_1h(df_btc.index)
    print(f"BTC 1h: {len(df_btc)} bar  ({df_btc.index[0]:%Y-%m-%d} → {df_btc.index[-1]:%Y-%m-%d})")
    if btcd is None:
        print("BTCDOMUSDT-4h-*.csv bulunamadı."); return
    valid = btcd.dropna()
    print(f"BTC.D:  {len(valid)} bar geçerli  "
          f"({valid.index[0]:%Y-%m-%d} → {valid.index[-1]:%Y-%m-%d})  "
          f"ort {valid.mean():.1f}%  min {valid.min():.1f}%  max {valid.max():.1f}%")
    print("=" * 120)

    # 1) Kanonik baseline (BİR KEZ)
    base = run_baseline(df_btc)
    print("\n" + summarize(base, "BASELINE (tüm trade'ler)"))

    # 2) BTC.D ile etiketle
    ann = annotate(base, btcd)
    print(summarize(ann, "BASELINE ∩ BTC.D kapsamı (etiketli)"))
    drop = len(base) - len(ann)
    if drop:
        print(f"  ({drop} trade BTC.D kapsamı dışında — warmup/eksik ay)")

    # 3) Bucket analizleri (hepsi additive, baseline'a eşit)
    print("\n" + "=" * 120)
    print("\n[A] BTC.D SEVİYESİ (mutlak yüzde)")
    bucket(ann, "dom_level",
           [0, 42, 46, 50, 54, 100],
           ["<%42 (düşük dom)", "%42-46", "%46-50", "%50-54", ">%54 (yüksek dom)"])

    print("\n[B] BTC.D 24-SAATLİK DEĞİŞİM (momentum)")
    bucket(ann, "dom_chg_24h",
           [-100, -0.5, -0.1, 0.1, 0.5, 100],
           ["güçlü düşüş (<-0.5)", "hafif düşüş (-0.5/-0.1)",
            "yatay (-0.1/+0.1)", "hafif yükseliş (+0.1/+0.5)",
            "güçlü yükseliş (>+0.5)"])

    print("\n[C] BTC.D 72-SAATLİK DEĞİŞİM (3 günlük trend)")
    bucket(ann, "dom_chg_72h",
           [-100, -1.0, -0.3, 0.3, 1.0, 100],
           ["güçlü düşüş (<-1.0)", "hafif düşüş (-1.0/-0.3)",
            "yatay (-0.3/+0.3)", "hafif yükseliş (+0.3/+1.0)",
            "güçlü yükseliş (>+1.0)"])

    print("\n[D] BTC.D 20-GÜNLÜK ORTALAMADAN SAPMA")
    bucket(ann, "dom_vs_ma20d",
           [-100, -1.0, -0.3, 0.3, 1.0, 100],
           ["MA'nın çok altı (<-1.0)", "MA altı (-1.0/-0.3)",
            "MA civarı (-0.3/+0.3)", "MA üstü (+0.3/+1.0)",
            "MA'nın çok üstü (>+1.0)"])

    # 4) Yön × rejim (DÜRÜST: gerçek eşiklerle)
    print("\n" + "=" * 120)
    print("\n[E] YÖN × BTC.D 72h TREND (dürüst — gerçek değişim eşiği)")
    print(f"  {'Grup':<46}{'Trade':>6}{'WR':>6}{'PnL':>9}{'TR':>14}{'TE':>14}")
    combos = [
        ("LONG  & dom düşüyor (chg72<-0.3)",  1, lambda x: x < -0.3),
        ("LONG  & dom yükseliyor (chg72>+0.3)",1, lambda x: x > 0.3),
        ("SHORT & dom düşüyor (chg72<-0.3)",  -1, lambda x: x < -0.3),
        ("SHORT & dom yükseliyor (chg72>+0.3)",-1, lambda x: x > 0.3),
    ]
    for lbl, d, cond in combos:
        grp = [t for t in ann if t["dir"] == d
               and not np.isnan(t["dom_chg_72h"]) and cond(t["dom_chg_72h"])]
        if not grp:
            print(f"  {lbl:<46}{0:>6}"); continue
        p = np.array([t["pnl"] for t in grp]); wr = (p>0).mean()
        tr = [t for t in grp if t["ts_entry"] < SPLIT]
        te = [t for t in grp if t["ts_entry"] >= SPLIT]
        ptr = sum(t["pnl"] for t in tr); pte = sum(t["pnl"] for t in te)
        wtr = (np.array([t["pnl"] for t in tr])>0).mean() if tr else 0
        wte = (np.array([t["pnl"] for t in te])>0).mean() if te else 0
        s_tr = f"WR{wtr:.0%} ${ptr:>+5.0f}" if tr else "—"
        s_te = f"WR{wte:.0%} ${pte:>+5.0f}" if te else "—"
        print(f"  {lbl:<46}{len(p):>6}{wr*100:>5.0f}%{p.sum():>+9.0f}{s_tr:>14}{s_te:>14}")

    print("\n" + "=" * 120)
    print("\nYORUM REHBERİ:")
    print("  • Bir rejim GERÇEKTEN edge ekliyorsa: hem TRAIN hem TEST pozitif olmalı.")
    print("  • Sadece birinde pozitifse → tesadüf/overfit, canlıya ALMA.")
    print("  • Bucket toplamı baseline'a eşit → partition dürüst, PnL'ler karşılaştırılabilir.")


if __name__ == "__main__":
    main()


# ── DOĞRULAMA: "dom çöküşünde trade alma" filtresini gerçek backtest'le ──────────

def run_filtered(df_1h, btcd_1h, skip_dom_crash=False, crash_thresh=-1.0):
    """Baseline + opsiyonel: BTC.D 72h'de crash_thresh'den fazla düşüyorsa atla."""
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    n = len(c); balance = BAL; open_t = None; trades = []
    for i in range(60, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]
            held = i - open_t["i"]; ep = None; reason = None
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
                trades.append({"ts_entry": open_t["ts"], "pnl": pnl})
                open_t = None
            continue
        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue
        # BTC.D crash filtresi
        if skip_dom_crash:
            ts = df_1h.index[i]
            lvl = btcd_1h.loc[ts] if ts in btcd_1h.index else np.nan
            ts72 = ts - pd.Timedelta(hours=72)
            if ts72 >= btcd_1h.index[0] and not np.isnan(lvl):
                chg72 = lvl - btcd_1h.asof(ts72)
                if chg72 < crash_thresh:
                    continue   # dom çöküyor → atla
        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * RISK) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}
    return trades


def verify():
    df_btc = load_btc_1h()
    btcd   = load_btcd_1h(df_btc.index)
    print("\n" + "=" * 120)
    print("\n[DOĞRULAMA] Gerçek sıralı backtest — pozisyon boyutu doğru hesaplanır\n")
    base = run_filtered(df_btc, btcd, skip_dom_crash=False)
    print(summarize_v(base, "BASELINE"))
    for th in [-1.5, -1.0, -0.7]:
        filt = run_filtered(df_btc, btcd, skip_dom_crash=True, crash_thresh=th)
        print(summarize_v(filt, f"BTC.D 72h < {th}pp ÇÖKÜŞÜ ATLA"))


def summarize_v(trades, label):
    p = np.array([t["pnl"] for t in trades])
    wr = (p > 0).mean()
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd = ((pk-eq)/pk).max()
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    ptr = np.array([t["pnl"] for t in tr]); pte = np.array([t["pnl"] for t in te])
    s_tr = f"WR{(ptr>0).mean():.0%} ${ptr.sum():>+6.0f}" if len(ptr) else "—"
    s_te = f"WR{(pte>0).mean():.0%} ${pte.sum():>+6.0f}" if len(pte) else "—"
    return (f"{label:<40} {len(p):>3}t WR{wr:.0%} ${p.sum():>+7.0f} "
            f"({p.sum()/100:>+5.1f}%) DD{dd*100:.0f}% | TR {s_tr} | TE {s_te}")


if __name__ == "__main__":
    main()
    verify()
