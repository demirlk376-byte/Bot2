"""
research_quality.py

Sinyal KALİTESİ trade sonucunu öngörüyor mu? Kaliteye göre risk almak mantıklı mı?

SORU: "Kaliteli sinyalde daha fazla risk al" (kullanıcı: kaldıraç artır vb).
      Bunun işe yaraması için kaliteli sinyallerin GERÇEKTEN daha iyi sonuç
      vermesi gerekir. Önce bunu kanıtla, sonra sizing'i test et.

YÖNTEM (dürüst, additive — research_btcd_clean ile aynı disiplin):
  1. Baseline'ı BİR KEZ çalıştır → kanonik trade listesi.
  2. Her trade'i GİRİŞ anındaki kalite metrikleriyle etiketle:
       - bb_dist:   BB dışına ne kadar taştı (|bb_pos|, ne kadar büyükse o kadar extreme)
       - vol_ratio: hacim / 20-MA (ne kadar büyükse o kadar güçlü kapitülasyon)
       - atr_pct:   ATR'nin son 200 bardaki yüzdelik sırası
       - body_ratio:mum gövdesi / ATR (büyük gövde = güçlü hareket)
  3. Her metriğe göre bucket'la → kalite arttıkça WR/PnL artıyor mu?
  4. Hem TRAIN hem TEST'te tutarlıysa → gerçek. Sonra sizing testi.

DOĞRULAMA: Kalite-ağırlıklı pozisyon boyutu gerçek sıralı backtest'le baseline'ı
geçiyor mu?

Run: python research_quality.py
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


def run_baseline_with_quality(df_1h):
    """Baseline trade'ler + her birinin GİRİŞ anı kalite metrikleri."""
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    o   = df_1h["open"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
    atr_arr = atr_s.values

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
                trades.append({**open_t["q"], "ts_entry": open_t["ts"],
                               "dir": d, "pnl": pnl, "reason": reason})
                open_t = None
            continue
        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue

        # ── KALİTE METRİKLERİ (giriş anında, lookahead yok) ──
        # BB dışına taşma: bpos<0 ise -bpos, bpos>1 ise bpos-1 (her ikisi de >0)
        bb_dist = (-bpos) if bpos < 0 else (bpos - 1)
        vol_ratio = vol[i] / vol_ma[i] if vol_ma[i] > 0 else 1.0
        atr_window = atr_arr[max(0, i-200):i+1]
        atr_window = atr_window[~np.isnan(atr_window)]
        atr_pct = (atr_window < a).mean() if len(atr_window) else 0.5
        body_ratio = abs(c[i] - o[i]) / a if a > 0 else 0.0

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * RISK) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty,
                  "q": {"bb_dist": bb_dist, "vol_ratio": vol_ratio,
                        "atr_pct": atr_pct, "body_ratio": body_ratio}}
    return trades


def bucket(trades, key, n_buckets=4):
    """Trade'leri key'e göre quantile bucket'lara böl, WR+PnL göster."""
    vals = np.array([t[key] for t in trades])
    qs = np.quantile(vals, np.linspace(0, 1, n_buckets + 1))
    print(f"\n  [{key}] kalite arttıkça sonuç (Q1=düşük → Q{n_buckets}=yüksek):")
    print(f"  {'Bucket':<22}{'Trade':>6}{'WR':>6}{'PnL':>9}{'avgPnL':>9}"
          f"{'TR':>13}{'TE':>13}")
    for b in range(n_buckets):
        lo_q, hi_q = qs[b], qs[b+1]
        if b == n_buckets - 1:
            grp = [t for t in trades if lo_q <= t[key] <= hi_q]
        else:
            grp = [t for t in trades if lo_q <= t[key] < hi_q]
        if not grp:
            continue
        p = np.array([t["pnl"] for t in grp]); wr = (p > 0).mean()
        tr = [t for t in grp if t["ts_entry"] < SPLIT]
        te = [t for t in grp if t["ts_entry"] >= SPLIT]
        ptr = sum(t["pnl"] for t in tr); pte = sum(t["pnl"] for t in te)
        wtr = (np.array([t["pnl"] for t in tr])>0).mean() if tr else 0
        wte = (np.array([t["pnl"] for t in te])>0).mean() if te else 0
        lbl = f"Q{b+1} [{lo_q:.2f}-{hi_q:.2f}]"
        print(f"  {lbl:<22}{len(p):>6}{wr*100:>5.0f}%{p.sum():>+9.0f}"
              f"{p.mean():>+9.1f}"
              f"{f'W{wtr:.0%} ${ptr:+.0f}':>13}{f'W{wte:.0%} ${pte:+.0f}':>13}")


def summarize(trades, label):
    p = np.array([t["pnl"] for t in trades]); wr = (p > 0).mean()
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd = ((pk-eq)/pk).max()
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    ptr = np.array([t["pnl"] for t in tr]); pte = np.array([t["pnl"] for t in te])
    s_tr = f"WR{(ptr>0).mean():.0%} ${ptr.sum():>+6.0f}" if len(ptr) else "—"
    s_te = f"WR{(pte>0).mean():.0%} ${pte.sum():>+6.0f}" if len(pte) else "—"
    return (f"{label:<44} {len(p):>3}t WR{wr:.0%} ${p.sum():>+7.0f} "
            f"({p.sum()/100:>+5.1f}%) DD{dd*100:.0f}% | TR {s_tr} | TE {s_te}")


# ── Kalite-ağırlıklı sizing (gerçek sıralı backtest) ──────────────────────────

def run_quality_sized(df_1h, score_fn, base_risk=RISK, max_mult=2.0):
    """
    score_fn(q) -> 0..1 arası kalite skoru.
    risk = base_risk * (1 + score * (max_mult - 1))  → kalite yüksekse risk artar.
    """
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    o   = df_1h["open"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values
    atr_arr = atr_s.values

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
        bb_dist = (-bpos) if bpos < 0 else (bpos - 1)
        vol_ratio = vol[i] / vol_ma[i] if vol_ma[i] > 0 else 1.0
        atr_window = atr_arr[max(0, i-200):i+1]
        atr_window = atr_window[~np.isnan(atr_window)]
        atr_pct = (atr_window < a).mean() if len(atr_window) else 0.5
        body_ratio = abs(c[i] - o[i]) / a if a > 0 else 0.0
        q = {"bb_dist": bb_dist, "vol_ratio": vol_ratio,
             "atr_pct": atr_pct, "body_ratio": body_ratio}
        score = max(0.0, min(1.0, score_fn(q)))
        risk = base_risk * (1 + score * (max_mult - 1))

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * risk) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}
    return trades


def main():
    df = load_btc_1h()
    print(f"BTC 1h: {len(df)} bar ({df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d})")
    print("=" * 110)

    trades = run_baseline_with_quality(df)
    print("\n" + summarize(trades, "BASELINE (sabit risk %3)"))

    print("\n" + "=" * 110)
    print("\n[ADIM 1] Kalite metrikleri sonucu öngörüyor mu? (additive, toplam=baseline)")
    for key in ["bb_dist", "vol_ratio", "atr_pct", "body_ratio"]:
        bucket(trades, key, n_buckets=4)

    print("\n" + "=" * 110)
    print("\n[ADIM 2] Kalite-ağırlıklı pozisyon boyutu — baseline'ı geçer mi?")
    print("  (risk = %3 × (1 + skor); skor=1 → risk %6'ya kadar)\n")

    # Çeşitli skor fonksiyonları
    score_fns = [
        ("bb_dist skoru (taşma×3, clip)",
         lambda q: q["bb_dist"] * 3.0),
        ("vol_ratio skoru ((vr-1)/2)",
         lambda q: (q["vol_ratio"] - 1.0) / 2.0),
        ("body_ratio skoru (br/2)",
         lambda q: q["body_ratio"] / 2.0),
        ("düşük ATR percentile tercih (1-atr_pct)",
         lambda q: 1.0 - q["atr_pct"]),
        ("kombine (bb_dist + vol + body) ort",
         lambda q: (min(1,q["bb_dist"]*3) + min(1,(q["vol_ratio"]-1)/2)
                    + min(1,q["body_ratio"]/2)) / 3.0),
    ]
    print("  " + summarize(trades, "BASELINE referans").strip())
    print()
    for label, fn in score_fns:
        t = run_quality_sized(df, fn, base_risk=RISK, max_mult=2.0)
        print("  " + summarize(t, label).strip())

    print("\n" + "=" * 110)
    print("\nYORUM:")
    print("  • ADIM 1'de bir metrik için Q4 (yüksek kalite) hem TR hem TE'de Q1'den")
    print("    belirgin iyiyse → o metrik gerçek kalite sinyali.")
    print("  • ADIM 2'de bir sizing baseline'ı HEM toplam HEM risk-ayarlı (DD) geçerse")
    print("    → kaliteye göre risk almak değerli. Geçmezse → sabit risk daha iyi.")


if __name__ == "__main__":
    main()
