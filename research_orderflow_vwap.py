"""
research_orderflow_vwap.py

İki YENİ sinyali dürüst metodolojiyle test eder:

1) ORDER FLOW PROXY — taker-buy delta
   Binance CSV'de taker_buy_volume var: agresif alıcı hacmi.
   taker_buy_ratio = taker_buy_volume / volume  (0.5 üstü = alım baskın).
   Gerçek order book yok ama bu, geçmişte backtest edilebilen tek order-flow
   proxy'si. HİÇ test edilmedi.
   Hipotez: BB altına düşüşte (long sinyali) AGRESİF SATIŞ baskınsa
   (düşük taker_buy_ratio) = kapitülasyon = reversion daha güçlü olabilir.

2) ANCHORED VWAP
   Son N-gün'e (veya rolling) demirlenmiş VWAP. Fiyatın VWAP'tan sapması.
   Hipotez: VWAP'ın çok altındaki long sinyalleri (derin iskonto) daha iyi döner.
   HİÇ test edilmedi.

YÖNTEM (research_btcd_clean ile aynı dürüst additive disiplin):
  1. Baseline'ı BİR KEZ çalıştır → kanonik trade listesi.
  2. Her trade'i GİRİŞ anındaki metriklerle etiketle.
  3. Bucket'la — alt grupların PnL toplamı = baseline. Önyargı yok.
  4. Hem TRAIN hem TEST'te tutarlıysa → gerçek sinyal.

Run: python research_orderflow_vwap.py
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


def load_1m_and_1h():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume",
                          "taker_buy_volume"]].astype(float))
    m = (pd.concat(frames, ignore_index=True)
         .drop_duplicates(subset="ts").sort_values("ts"))
    m.index = pd.to_datetime(m["ts"], unit="ms")
    m = m.drop(columns=["ts"])
    # 1h: taker_buy_volume da topla
    h = m.resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last",
         "volume":"sum","taker_buy_volume":"sum"}
    ).dropna()
    return m, h


def run_baseline_annotated(df_1h):
    """Baseline trade'ler + giriş anı: taker_buy_ratio ve VWAP sapması."""
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    tbv = df_1h["taker_buy_volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    # Anchored VWAP: rolling 7 gün (168 saat) — pratikte "son haftaya demirli"
    typical = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3.0
    win = 168
    pv = (typical * df_1h["volume"]).rolling(win).sum()
    vv = df_1h["volume"].rolling(win).sum()
    vwap = (pv / vv).values

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

        # ── metrikler (giriş anı) ──
        tb_ratio = tbv[i] / vol[i] if vol[i] > 0 else 0.5
        # yöne göre "lehte order flow": long ise satış baskısı (1-ratio),
        # short ise alış baskısı (ratio). Yüksek = sinyal yönüyle çelişen baskı
        # tükeniyor demek (kapitülasyon teorisi).
        capitulation = (1 - tb_ratio) if direction == 1 else tb_ratio
        vw = vwap[i]
        vwap_dev = (c[i] - vw) / vw if (not np.isnan(vw) and vw > 0) else np.nan
        # yöne göre VWAP iskontosu: long ise ne kadar VWAP altında (negatif dev iyi)
        vwap_edge = (-vwap_dev) if direction == 1 else vwap_dev

        ep = c[i]; sl_d = SL_M * a
        sl = ep - direction * sl_d; tp = ep + direction * TP_M * a
        qty = min(round((balance * RISK) / (ep * (sl_d / ep)), 3),
                  balance * 0.5 / ep)
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty,
                  "meta": {"tb_ratio": tb_ratio, "capitulation": capitulation,
                           "vwap_dev": vwap_dev, "vwap_edge": vwap_edge}}
    return trades


def summarize(trades, label):
    p = np.array([t["pnl"] for t in trades]); wr = (p > 0).mean()
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    s_tr = f"WR{(np.array([t['pnl'] for t in tr])>0).mean():.0%} ${sum(t['pnl'] for t in tr):>+6.0f}" if tr else "—"
    s_te = f"WR{(np.array([t['pnl'] for t in te])>0).mean():.0%} ${sum(t['pnl'] for t in te):>+6.0f}" if te else "—"
    return (f"{label:<40} {len(p):>3}t WR{wr:.0%} ${p.sum():>+7.0f} "
            f"({p.sum()/100:>+5.1f}%) | TR {s_tr} | TE {s_te}")


def bucket(trades, key, n=4):
    vals = np.array([t[key] for t in trades if not np.isnan(t[key])])
    if len(vals) < n:
        print(f"  [{key}] yetersiz veri"); return
    qs = np.quantile(vals, np.linspace(0, 1, n+1))
    print(f"\n  [{key}] Q1=düşük → Q{n}=yüksek (toplam=baseline):")
    print(f"  {'Bucket':<20}{'Trade':>6}{'WR':>6}{'PnL':>9}{'avg':>8}{'TR':>13}{'TE':>13}")
    for b in range(n):
        a0, a1 = qs[b], qs[b+1]
        grp = [t for t in trades if not np.isnan(t[key]) and
               (a0 <= t[key] <= a1 if b == n-1 else a0 <= t[key] < a1)]
        if not grp:
            continue
        pp = np.array([t["pnl"] for t in grp]); wr = (pp > 0).mean()
        tr = [t for t in grp if t["ts_entry"] < SPLIT]
        te = [t for t in grp if t["ts_entry"] >= SPLIT]
        ptr = sum(t["pnl"] for t in tr); pte = sum(t["pnl"] for t in te)
        wtr = (np.array([t["pnl"] for t in tr])>0).mean() if tr else 0
        wte = (np.array([t["pnl"] for t in te])>0).mean() if te else 0
        print(f"  Q{b+1}[{a0:>5.2f},{a1:>5.2f}]{len(pp):>6}{wr*100:>5.0f}%"
              f"{pp.sum():>+9.0f}{pp.mean():>+8.1f}"
              f"{f'W{wtr:.0%}{ptr:+.0f}':>13}{f'W{wte:.0%}{pte:+.0f}':>13}")


def main():
    _, df_1h = load_1m_and_1h()
    print(f"BTC 1h: {len(df_1h)} bar ({df_1h.index[0]:%Y-%m-%d}→{df_1h.index[-1]:%Y-%m-%d})")
    print("=" * 100)

    trades = run_baseline_annotated(df_1h)
    print("\n" + summarize(trades, "BASELINE"))

    print("\n" + "=" * 100)
    print("\n[1] ORDER FLOW PROXY — taker-buy delta")
    print("  tb_ratio: ham agresif-alım oranı (yön bağımsız)")
    bucket(trades, "tb_ratio")
    print("\n  capitulation: yöne göre 'çelişen baskı' (long→satış baskısı yüksek)")
    print("  Yüksek = kapitülasyon teorisi destekleniyorsa daha iyi olmalı")
    bucket(trades, "capitulation")

    print("\n" + "=" * 100)
    print("\n[2] ANCHORED VWAP (7 günlük demir)")
    print("  vwap_dev: fiyatın VWAP'tan sapması (yön bağımsız)")
    bucket(trades, "vwap_dev")
    print("\n  vwap_edge: yöne göre VWAP iskontosu (long→VWAP ne kadar altında)")
    print("  Yüksek = derin iskonto; reversion daha iyi dönerse pozitif olmalı")
    bucket(trades, "vwap_edge")

    print("\n" + "=" * 100)
    print("\nYORUM: Bir metrik için en iyi bucket HEM TR HEM TE'de belirgin pozitifse")
    print("       → gerçek sinyal. Sadece birinde ise → gürültü, canlıya ALMA.")


if __name__ == "__main__":
    main()
