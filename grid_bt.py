"""
grid_bt.py — Grid bot backtest (DÜRÜST). Nötr grid: fiyat bir seviyeyi aşağı
kesince AL, yukarı kesince SAT. Range'de salınımdan kazanır; TREND'de aralıktan
çıkınca ters pozisyonla KANAR (grid'in bilinen zaafı). Bu yüzden net P&L kadar
MAX DRAWDOWN'u da raporlar — asıl gerçek orada.

Model: sabit merkez (ilk fiyat), ±N seviye, spacing%%. Her seviye kesişince
unit_usd'lik işlem, taker fee iki tarafta. Pozisyon ±N unit ile sınırlı
(aralıktan çıkınca daha fazla emir yok, kapalı pozisyon mark-to-market kanar).
Fiyat serisi = 1h close (cache). Gerçekçi ama basit; grid'in edge'i var mı yok
mu görmeye yeter.

Kullanım:
  python grid_bt.py SOL,ETH,XRP,DOGE           # VPS (MEXC)
  py grid_bt.py SOL,ETH,XRP,DOGE local          # PC (cache, çevrimdışı)
"""
import sys, bisect
import numpy as np, pandas as pd
import fast_bt

BAL = 190.0
FEE = 0.0002   # taker/işlem — grid çok işlem yapar, fee önemli (kötümser)
# Denenecek gridler: (spacing, N_seviye)
GRIDS = [(0.005, 20), (0.01, 15), (0.02, 10), (0.01, 30)]


def grid_sim(close, years, spacing, N, unit_usd):
    center = close[0]
    lines = sorted(center * (1 + i * spacing) for i in range(-N, N + 1))
    pos = 0.0; cash = 0.0; fees = 0.0
    prev = bisect.bisect_right(lines, close[0])   # başlangıçta altta kalan çizgi sayısı
    peak = 0.0; maxdd = 0.0
    per_year = {}
    for t in range(len(close)):
        c = close[t]
        idx = bisect.bisect_right(lines, c)
        while idx < prev:                          # fiyat düştü → çizgilerde AL
            prev -= 1; p = lines[prev]; q = unit_usd / p
            cash -= p * q; fees += p * q * FEE; pos += q
        while idx > prev:                          # fiyat çıktı → çizgilerde SAT
            p = lines[prev]; q = unit_usd / p
            cash += p * q; fees += p * q * FEE; pos -= q; prev += 1
        eq = cash + pos * c - fees
        peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
        per_year[years[t]] = eq
    final = cash + pos * close[-1] - fees
    return final, maxdd, fees, pos * close[-1], per_year


def run(coin, close, years):
    print(f"\n{'='*66}\n=== {coin} — grid ({len(close)} bar) ===", flush=True)
    best = None
    for spacing, N in GRIDS:
        unit = BAL / N                              # tam açılımda ~BAL notional (kaldıraçsız)
        final, maxdd, fees, open_mtm, py = grid_sim(close, years, spacing, N, unit)
        # yıl-yıl artımsal
        yrs = sorted(py); prev_eq = 0.0; yrbits = []
        for y in yrs:
            yrbits.append(f"{y}:${py[y]-prev_eq:+.0f}"); prev_eq = py[y]
        tag = f"aralık±{spacing*N*100:.0f}% adım{spacing*100:.1f}% N{N}"
        print(f"  {tag:30s} net${final:+7.2f}  maxDD${maxdd:6.1f}  fee${fees:.1f}  "
              f"açıkPoz${open_mtm:+.0f}   {' '.join(yrbits)}", flush=True)
        if best is None or final > best[0]:
            best = (final, maxdd, tag)
    return dict(coin=coin, final=best[0], maxdd=best[1], tag=best[2])


def main():
    coins = [c.strip().upper() for c in (sys.argv[1] if len(sys.argv) > 1 else "BTC").split(",")]
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    print("GRID BOT backtest (nötr, sabit merkez) — net P&L + MAX DRAWDOWN")
    print(f"{coins}  fee%{FEE*100} unit=BAL/N (kaldıraçsız tam açılım)")
    rows = []
    for coin in coins:
        try:
            m = fast_bt.load(coin, source=source)
        except Exception as e:
            print(f"  {coin} veri hatası: {e}", flush=True); continue
        rows.append(run(coin, m["close"].values, np.array([d.year for d in m.index])))
    print(f"\n{'='*66}\n=== ÖZET — grid (en iyi grid/coin) ===", flush=True)
    for r in sorted(rows, key=lambda x: -x["final"]):
        dd_ratio = r["final"] / r["maxdd"] if r["maxdd"] > 0 else 9.99
        flag = "⚠️DD>net" if r["maxdd"] > abs(r["final"]) else ""
        print(f"  {r['coin']:5s}  net${r['final']:+7.2f}  maxDD${r['maxdd']:6.1f}  "
              f"net/DD={dd_ratio:4.2f}  ({r['tag']}) {flag}", flush=True)
    print("\n  DÜRÜST OKUMA: net+ olsa bile maxDD net'ten büyükse → o kâr için")
    print("  göze alınan risk çok; trend geldiğinde yediğin DD kârı siler. net/DD<1 = kötü.")
    print("  Sağlam grid: net+ VE net/DD makul (>0.5) VE çok coinde. Nadir.")


if __name__ == "__main__":
    main()
