"""
nw_kama_tracker.py — NW+KAMA event-1D İLERİ (forward) kağıt takibi. ETH + AVAX.

NEDEN: validate_nw_kama.py taramasında (10 coin × 4 config) yalnız ETH (4/4)
ve AVAX (3/4) güçlü çıktı — bu, çoklu-karşılaştırma şansının öngördüğü sayının
ta kendisi (~2.5 coin). "Şans mı, gerçek mi?" sorusunu geçmiş veri artık
cevaplayamaz; TEK dürüst hakem ileri veri. Bu tracker, geçen testin AYNI
config'lerini (tek satır değişmeden) FORWARD_EPOCH'tan itibaren kağıt üstünde
izler. Karar kuralı ÖN-KAYITLI:

  6-8 hafta sonra birleşik n>=15 ve PF>=1.3 ise → küçük canlı sleeve tasarımı
  konuşulur. Aksi halde fikir mühürlenir. (Config seçmece yok, kural budur.)

Mekanik (validate_nw_kama ile birebir):
  sinyal  : sigs(df, "event", h, win, mult, er, lb) — NW bandı son lb bar
            içinde extreme + KAMA aynı yönde KESİŞİM şu bar
  giriş   : sinyal gününün kapanışı
  çıkış   : SL=2×ATR14, TP=4×ATR14, max-hold 15 gün, bar içinde SL öncelikli
  poz.    : config başına aynı anda tek pozisyon

Durum dosyası YOK — her koşu, borsadan çekilen günlük barlarla EPOCH'tan
bugüne deterministik yeniden hesap yapar ve çıktı dosyalarını baştan yazar
(cron kaçarsa hiçbir şey kaybolmaz). Kapanan trade'ler nw_kama_trades.csv'ye,
açık pozisyonlar + özet ekrana ve nw_kama_status.txt'ye.

Kurulum (VPS):
  venv/bin/python nw_kama_tracker.py            # elle koş / cron hedefi
  crontab: 15 0 * * *  cd /opt/bot2 && venv/bin/python nw_kama_tracker.py >> nw_kama_tracker.log 2>&1
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from validate_nw_kama import sigs                       # noqa: E402
from indicators import atr as atr_fn                    # noqa: E402

# ── ÖN-KAYIT (2026-07-13) — bundan sonrası değiştirilemez ────────────────────
FORWARD_EPOCH = pd.Timestamp("2026-07-14", tz="UTC")   # ilk sayılacak giriş günü
COINS   = ["ETH/USDT", "AVAX/USDT"]
CONFIGS = [  # (h, win, mult, er, lb) — validate GRID'in event-1D satırları
    (3, 15, 1.5, 5, 1),
    (3, 15, 2.0, 5, 2),
    (4, 20, 1.5, 8, 2),
    (5, 25, 2.0, 10, 2),
]
SL_M, TP_M, MAX_HOLD = 2.0, 4.0, 15
TRADES_CSV = Path(__file__).parent / "nw_kama_trades.csv"
STATUS_TXT = Path(__file__).parent / "nw_kama_status.txt"


def fetch_daily(symbol: str, limit: int = 300) -> pd.DataFrame:
    """MEXC public 1d OHLCV (API key gerekmez). Son (oluşan) bar atılır —
    yalnız KAPANMIŞ günlük barlarla çalışırız."""
    import ccxt
    ex = ccxt.mexc()
    raw = ex.fetch_ohlcv(symbol, "1d", limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop(columns=["ts"]).astype(float)
    return df.iloc[:-1]   # forming barı at


def simulate_forward(df: pd.DataFrame, cfg) -> tuple[list[dict], dict | None]:
    """Config için epoch sonrası girişleri simüle et. Döner: (kapananlar, açık)."""
    h, win, mult, er, lb = cfg
    entries = sigs(df, "event", h, win, mult, er, lb)
    atr_a = atr_fn(df["high"], df["low"], df["close"], 14).values
    hi = df["high"].values; lo = df["low"].values; c = df["close"].values
    idx = df.index
    label = f"h{h}w{win}m{mult}"

    closed: list[dict] = []
    open_pos: dict | None = None
    occupied_until = -1
    for (t, d) in entries:
        if idx[t] < FORWARD_EPOCH or t <= occupied_until:
            continue
        a = atr_a[t]
        if np.isnan(a) or a <= 0:
            continue
        entry = c[t]
        sl = entry - d * SL_M * a
        tp = entry + d * TP_M * a
        exit_p = None; reason = None; j_exit = None
        for j in range(t + 1, min(t + 1 + MAX_HOLD, len(c))):
            if d == 1:
                if lo[j] <= sl: exit_p, reason, j_exit = sl, "sl", j; break
                if hi[j] >= tp: exit_p, reason, j_exit = tp, "tp", j; break
            else:
                if hi[j] >= sl: exit_p, reason, j_exit = sl, "sl", j; break
                if lo[j] <= tp: exit_p, reason, j_exit = tp, "tp", j; break
        if exit_p is None:
            if t + MAX_HOLD < len(c):
                j_exit = t + MAX_HOLD
                exit_p, reason = c[j_exit], "mh"
            else:
                # hâlâ açık — forward pozisyon
                open_pos = {"config": label, "dir": d, "entry_ts": str(idx[t].date()),
                            "entry": round(entry, 4), "sl": round(sl, 4),
                            "tp": round(tp, 4), "held": len(c) - 1 - t}
                occupied_until = len(c)
                continue
        r_mult = (exit_p - entry) / (SL_M * a) * d   # R cinsinden sonuç
        closed.append({"config": label, "dir": d,
                       "entry_ts": str(idx[t].date()), "exit_ts": str(idx[j_exit].date()),
                       "entry": round(entry, 4), "exit": round(exit_p, 4),
                       "reason": reason, "r": round(r_mult, 3)})
        occupied_until = j_exit
    return closed, open_pos


def main() -> None:
    all_closed: list[dict] = []
    all_open: list[dict] = []
    lines = []
    for sym in COINS:
        try:
            df = fetch_daily(sym)
        except Exception as e:
            lines.append(f"{sym}: veri hatası: {e}")
            continue
        for cfg in CONFIGS:
            closed, op = simulate_forward(df, cfg)
            for row in closed:
                row["coin"] = sym.split("/")[0]
            all_closed.extend(closed)
            if op:
                op["coin"] = sym.split("/")[0]
                all_open.append(op)

    # Çıktılar deterministik — dosyaları baştan yaz (idempotent).
    with open(TRADES_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["coin", "config", "dir", "entry_ts",
                                          "exit_ts", "entry", "exit", "reason", "r"])
        w.writeheader()
        for row in sorted(all_closed, key=lambda r: r["entry_ts"]):
            w.writerow(row)

    rs = [t["r"] for t in all_closed]
    n = len(rs)
    wr = (sum(1 for r in rs if r > 0) / n) if n else 0.0
    gp = sum(r for r in rs if r > 0); gl = -sum(r for r in rs if r < 0)
    pf = (gp / gl) if gl > 0 else (9.99 if gp > 0 else 0.0)

    lines.append("=" * 64)
    lines.append("  NW+KAMA FORWARD TAKIP (event-1D, ETH+AVAX, epoch 2026-07-14)")
    lines.append("=" * 64)
    lines.append(f"  kapanan: n={n}  WR={wr:.0%}  PF={pf:.2f}  toplam={sum(rs):+.2f}R")
    for t in sorted(all_closed, key=lambda r: r["entry_ts"]):
        lines.append(f"    {t['entry_ts']}→{t['exit_ts']} {t['coin']:<5s} {t['config']:<10s} "
                     f"{'L' if t['dir']==1 else 'S'} {t['reason']:>2s} {t['r']:+.2f}R")
    if all_open:
        lines.append("  açık pozisyonlar:")
        for p in all_open:
            lines.append(f"    {p['entry_ts']} {p['coin']:<5s} {p['config']:<10s} "
                         f"{'L' if p['dir']==1 else 'S'} @{p['entry']} sl={p['sl']} "
                         f"tp={p['tp']} ({p['held']}g)")
    else:
        lines.append("  açık pozisyon yok")
    lines.append("-" * 64)
    lines.append("  ÖN-KAYITLI KARAR: 6-8 haftada n>=15 ve PF>=1.3 → sleeve tasarımı;")
    lines.append("  aksi halde mühürlenir. Config seçmece / kural değişikliği YOK.")

    out = "\n".join(lines)
    print(out)
    STATUS_TXT.write_text(out + "\n")


if __name__ == "__main__":
    main()
