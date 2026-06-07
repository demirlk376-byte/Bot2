"""
research_sniper.py

SNIPER MODU: "Yalnızca A+ ve şartlı-A setupları al."

FİKİR: Tek tek filtreler (saat, VWAP, hacim, BTC.D) ayrı ayrı çürüdü. Ama belki
birden fazla LEHTE confluence AYNI ANDA varsa = gerçek A+ setup = daha iyi sonuç.
Az ama öz. "Tetiği her sinyalde değil, sadece en iyilerinde çek."

DÜRÜST OUT-OF-SAMPLE DİSİPLİN (look-ahead YOK):
  1. Baseline'ı BİR KEZ çalıştır → kanonik trade'ler, her biri çoklu metrikle etiketli.
  2. Confluence eşiklerini SADECE 2025 (train) verisinden belirle.
  3. Her trade'e o eşiklerle puan ver → grade (A+, A, B, C).
  4. Grade'leri hiç görülmemiş 2026 (test) verisinde uygula.
  5. A+/A setupları, baseline'a göre TEST'te daha mı iyi? Karşılaştır.

Eğer A+ setupları test'te de belirgin daha iyiyse → sniper modu GERÇEK.
Eğer değilse → tek-filtre dersinin aynısı: edge bölünemez, dokunma.

Kullanılan confluence'lar (geçmiş testlerde EN AZINDAN bir sinyal verenler):
  • atr_pct   — yüksek ATR yüzdeliği (quality testinde iki dönemde de + idi)
  • bb_overshoot — KÜÇÜK taşma (quality testinde küçük taşma daha iyiydi)
  • capitulation — düşük taker-buy (long'da satış tükenmesi; orderflow proxy)
  • vwap_edge  — derin VWAP iskontosu (orderflow_vwap testinde iki dönemde de +)

Run: python research_sniper.py
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


def load_1h_with_flow():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts", "open", "high", "low", "close",
                          "volume", "taker_buy_volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
         .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms")
    m = m.drop(columns=["ts"])
    return m.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum", "taker_buy_volume": "sum"}
    ).dropna()


def run_baseline_annotated(df_1h):
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    tbv = df_1h["taker_buy_volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    atr_pct_s = atr_s.rolling(200).apply(
        lambda w: (w.iloc[-1] >= w).mean(), raw=False).values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    typical = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3.0
    win = 168
    pv = (typical * df_1h["volume"]).rolling(win).sum()
    vv = df_1h["volume"].rolling(win).sum()
    vwap = (pv / vv).values

    n = len(c); balance = BAL; open_t = None; trades = []
    for i in range(200, n):
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]; qty = open_t["qty"]
            held = i - open_t["i"]; ep = None
            if d == 1:
                if lo[i] <= sl: ep = sl
                elif h[i] >= tp: ep = tp
            else:
                if h[i] >= sl: ep = sl
                elif lo[i] <= tp: ep = tp
            if ep is None and held >= MH: ep = c[i]
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                trades.append({**open_t["meta"], "ts_entry": open_t["ts"],
                               "dir": d, "pnl": pnl})
                open_t = None
            continue
        bpos = bb_pos[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        direction = 1 if bpos < 0 else -1
        if np.isnan(vol_ma[i]) or vol[i] < vol_ma[i]:
            continue

        # ── confluence metrikleri (giriş anı) ──
        # bb_overshoot: BB dışına taşma büyüklüğü (küçük = daha iyiydi → tersini ödüllendir)
        overshoot = (-bpos) if direction == 1 else (bpos - 1)
        atr_pct = atr_pct_s[i]
        tb_ratio = tbv[i] / vol[i] if vol[i] > 0 else 0.5
        capitulation = (1 - tb_ratio) if direction == 1 else tb_ratio
        vw = vwap[i]
        vwap_dev = (c[i] - vw) / vw if (not np.isnan(vw) and vw > 0) else np.nan
        vwap_edge = (-vwap_dev) if direction == 1 else vwap_dev

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * RISK) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty,
                  "meta": {"overshoot": overshoot, "atr_pct": atr_pct,
                           "capitulation": capitulation, "vwap_edge": vwap_edge}}
    return trades


def grade_trades(trades, thresholds):
    """Her trade'e confluence puanı ver (0–4), grade ata. Eşikler train'den gelir."""
    for t in trades:
        score = 0
        # atr_pct: yüksek iyi
        if not np.isnan(t["atr_pct"]) and t["atr_pct"] >= thresholds["atr_pct"]:
            score += 1
        # overshoot: KÜÇÜK iyi → eşiğin ALTINDA ise puan
        if not np.isnan(t["overshoot"]) and t["overshoot"] <= thresholds["overshoot"]:
            score += 1
        # capitulation: yüksek iyi
        if not np.isnan(t["capitulation"]) and t["capitulation"] >= thresholds["capitulation"]:
            score += 1
        # vwap_edge: yüksek (derin iskonto) iyi
        if not np.isnan(t["vwap_edge"]) and t["vwap_edge"] >= thresholds["vwap_edge"]:
            score += 1
        t["score"] = score
        t["grade"] = ("A+" if score == 4 else "A" if score == 3 else
                      "B" if score == 2 else "C")
    return trades


def stats(grp):
    if not grp:
        return "—"
    p = np.array([t["pnl"] for t in grp])
    return f"{len(p):>3}t WR{(p>0).mean():.0%} ${p.sum():>+7.0f}"


def main():
    df_1h = load_1h_with_flow()
    print(f"BTC 1h: {len(df_1h)} bar "
          f"({df_1h.index[0]:%Y-%m-%d}→{df_1h.index[-1]:%Y-%m-%d})")
    print("=" * 95)

    trades = run_baseline_annotated(df_1h)
    base_p = np.array([t["pnl"] for t in trades])
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    print(f"\nBASELINE: {len(base_p)}t WR{(base_p>0).mean():.0%} "
          f"${base_p.sum():+.0f} ({base_p.sum()/100:+.1f}%)")
    print(f"  TRAIN(2025): {stats(tr)}   TEST(2026): {stats(te)}")

    # ── Eşikleri SADECE train'den belirle (medyan) ──
    def med(key):
        v = np.array([t[key] for t in tr if not np.isnan(t[key])])
        return np.median(v)
    thresholds = {
        "atr_pct": med("atr_pct"),
        "overshoot": med("overshoot"),       # bunun ALTI iyi
        "capitulation": med("capitulation"),
        "vwap_edge": med("vwap_edge"),
    }
    print(f"\nConfluence eşikleri (SADECE train medyanı):")
    for k, v in thresholds.items():
        print(f"  {k:<14} {v:+.4f}")

    grade_trades(trades, thresholds)

    print("\n" + "=" * 95)
    print("\n[1] GRADE DAĞILIMI — eşik train'den, sonuç ayrı ayrı TRAIN/TEST")
    print(f"  {'Grade':<6}{'Tüm dönem':<22}{'TRAIN(2025)':<22}{'TEST(2026)':<22}")
    for g in ["A+", "A", "B", "C"]:
        allg = [t for t in trades if t["grade"] == g]
        trg = [t for t in allg if t["ts_entry"] < SPLIT]
        teg = [t for t in allg if t["ts_entry"] >= SPLIT]
        print(f"  {g:<6}{stats(allg):<22}{stats(trg):<22}{stats(teg):<22}")

    print("\n" + "=" * 95)
    print("\n[2] SNIPER SİMÜLASYONU — 'sadece şu grade'leri al' (out-of-sample TEST)")
    te_base = sum(t["pnl"] for t in te)
    print(f"  {'Sadece bunları al':<28}{'TEST trade':>12}{'TEST PnL':>12}"
          f"{'baseline farkı':>16}")
    print(f"  {'(hepsi = baseline)':<28}{len(te):>12}{te_base:>+12.0f}{0:>+16.0f}")
    for allowed in [["A+"], ["A+", "A"], ["A+", "A", "B"]]:
        sel = [t for t in te if t["grade"] in allowed]
        s = sum(t["pnl"] for t in sel)
        lbl = "+".join(allowed)
        print(f"  {lbl:<28}{len(sel):>12}{s:>+12.0f}{s - te_base:>+16.0f}")

    print("\n" + "=" * 95)
    print("\n[3] AYNI ŞEY TRAIN'DE (referans — burada iyi olması BEKLENİR)")
    tr_base = sum(t["pnl"] for t in tr)
    print(f"  {'Sadece bunları al':<28}{'TRAIN trade':>12}{'TRAIN PnL':>12}"
          f"{'baseline farkı':>16}")
    print(f"  {'(hepsi = baseline)':<28}{len(tr):>12}{tr_base:>+12.0f}{0:>+16.0f}")
    for allowed in [["A+"], ["A+", "A"], ["A+", "A", "B"]]:
        sel = [t for t in tr if t["grade"] in allowed]
        s = sum(t["pnl"] for t in sel)
        lbl = "+".join(allowed)
        print(f"  {lbl:<28}{len(sel):>12}{s:>+12.0f}{s - tr_base:>+16.0f}")

    print("\n" + "=" * 95)
    print("\nKARAR KURALI:")
    print("  • A+/A train'de İYİ + test'te DE baseline'ı geçiyorsa → sniper GERÇEK, uygula.")
    print("  • Train'de iyi ama test'te baseline'ın ALTINDA → overfit, tek-filtre dersi tekrar.")
    print("  • Sniper az trade demek: $ düşse bile WR yüksek + DD düşükse, küçük")
    print("    sermaye için psikolojik olarak tercih edilebilir — ama önce GERÇEK olmalı.")


if __name__ == "__main__":
    main()
