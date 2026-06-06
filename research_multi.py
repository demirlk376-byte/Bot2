"""
research_multi.py

Aynı BB fade edge'ini BTC dışındaki likit coinlerde test et.
Hedef: gerçek çeşitlendirme mi yoksa korelasyon tuzağı mı?

Sıfır parametre ayarı: BTC'den öğrenilen SL=3×ATR, TP=5×ATR aynen kullanılır.
Bir coin ancak kendi OOS döneminde pozitif ise portfolyoya eklenir.

Veri gereksinimi:
  - BTC:  ./BTCUSDT-1m-YYYY-MM.csv           (mevcut)
  - SOL:  ./sol_data/SOLUSDT-1m-YYYY-MM.csv  (download_data.py ile indir)
  - BNB:  ./bnb_data/BNBUSDT-1m-YYYY-MM.csv
  - XRP:  ./xrp_data/XRPUSDT-1m-YYYY-MM.csv

  Ya da tüm CSV'leri aynı klasöre koyup --flat ile çalıştır.

Kullanım:
  python research_multi.py
  python research_multi.py --coins SOL BNB XRP
  python research_multi.py --flat   (tüm *USDT* csv'ler aynı klasörde)

Run: python research_multi.py
"""
from __future__ import annotations

import argparse
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

DATA_DIRS = {
    "BTC": ".",
    "SOL": "sol_data",
    "BNB": "bnb_data",
    "XRP": "xrp_data",
    "ETH": "eth_data",
}


# ── Data ──────────────────────────────────────────────────────────────────────

def load(symbol: str, base: str = ".") -> pd.DataFrame | None:
    sym_upper = symbol.upper()
    if not sym_upper.endswith("USDT"):
        sym_upper += "USDT"

    # Klasör belirle
    short = sym_upper.replace("USDT","")
    data_dir = DATA_DIRS.get(short, f"{short.lower()}_data")
    pattern  = str(Path(base) / data_dir / f"{sym_upper}-1m-*.csv")
    files    = sorted(glob.glob(pattern))

    if not files:
        # Flat mod: aynı klasörde ara
        pattern = str(Path(base) / f"{sym_upper}-1m-*.csv")
        files   = sorted(glob.glob(pattern))

    if not files:
        return None

    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))

    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample_1h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


# ── Backtest ──────────────────────────────────────────────────────────────────

def run(df_1h: pd.DataFrame) -> list[dict]:
    c   = df_1h["close"].values
    h   = df_1h["high"].values
    lo  = df_1h["low"].values
    vol = df_1h["volume"].values
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean().values
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan)).values

    n = len(c); balance = BAL; open_t = None; trades = []
    peak = BAL; max_dd = 0.0

    for i in range(60, n):
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
            if ep is None and held >= MH:
                ep, reason = c[i], "mh"
            if ep is not None:
                pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
                balance += pnl
                peak = max(peak, balance)
                max_dd = max(max_dd, (peak - balance) / peak)
                trades.append({
                    "ts": df_1h.index[i],
                    "ts_entry": open_t["ts"],
                    "pnl": pnl, "reason": reason,
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
        sl = ep - direction * sl_d
        tp = ep + direction * TP_M * a
        qty = min(
            round((balance * RISK) / (ep * (sl_d / ep)), 3),
            balance * 0.5 / ep
        )
        if qty < 0.001:
            continue
        open_t = {"i": i, "ts": df_1h.index[i], "dir": direction,
                  "entry": ep, "sl": sl, "tp": tp, "qty": qty}

    return trades


# ── Stats ─────────────────────────────────────────────────────────────────────

def stat_line(symbol: str, trades: list[dict], n_months: int) -> str:
    if not trades:
        return f"{symbol:<6}  0 trade  — veri yok veya sinyal üretmedi"

    p  = np.array([t["pnl"] for t in trades])
    wr = (p > 0).mean()
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf = pos / neg if neg > 0 else float("inf")
    eq = BAL + np.cumsum(p)
    pk = np.maximum.accumulate(eq)
    dd = ((pk - eq) / pk).max()

    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    tp_ = np.array([t["pnl"] for t in tr]) if tr else np.array([0.0])
    te_ = np.array([t["pnl"] for t in te]) if te else np.array([0.0])

    monthly_avg = p.sum() / n_months

    oos_ok = "✓ OOS" if (len(te) > 5 and te_.sum() > 0) else "✗ OOS"

    return (
        f"{symbol:<6}  {len(p):>3}t WR{wr:.0%} PF{pf:.2f} "
        f"${p.sum():>+7,.0f} ({p.sum()/100:>+5.1f}%) "
        f"DD{dd*100:.0f}%  avg/mo ${monthly_avg:>+6,.0f}  "
        f"TR WR{(tp_>0).mean():.0%} ${tp_.sum():>+6,.0f}  "
        f"TE WR{(te_>0).mean():.0%} ${te_.sum():>+6,.0f}  {oos_ok}"
    )


def monthly_table(symbol: str, trades: list[dict]) -> str:
    if not trades:
        return ""
    lines = [f"  {symbol} aylık:"]
    by_month: dict[str, list] = {}
    for t in trades:
        key = t["ts_entry"].strftime("%Y-%m")
        by_month.setdefault(key, []).append(t["pnl"])
    for m, pnls in sorted(by_month.items()):
        p = np.array(pnls)
        wr = (p > 0).mean()
        lines.append(f"    {m}  {len(p):>2}t WR{wr:.0%} ${p.sum():>+7,.0f}")
    return "\n".join(lines)


# ── Portfolio simülasyonu ─────────────────────────────────────────────────────

def sim_portfolio(all_trades: dict[str, list], balance_per_coin: float = BAL) -> dict:
    """
    Her coin bağımsız bakiye ile çalışır (gerçekçi: ayrı ayrı MEXC hesabı
    yerine, toplam bakiyeyi N'e böl).
    Coin başı pozisyon: toplam bakiye / N_coin.
    """
    n = len(all_trades)
    if n == 0:
        return {}

    # Birleştir + sırala
    combined = []
    for sym, trades in all_trades.items():
        for t in trades:
            combined.append({**t, "symbol": sym})
    combined.sort(key=lambda x: x["ts"])

    total_bal = balance_per_coin * n
    per_coin  = balance_per_coin
    port_pnl  = []

    # Basit toplam (bağımsız hesaplar)
    total_pnl = sum(t["pnl"] for trades in all_trades.values() for t in trades)
    return {"total_pnl": total_pnl, "total_bal": total_bal}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", nargs="*",
                        default=["BTC","SOL","BNB","XRP","ETH"])
    parser.add_argument("--base", default=".",
                        help="Veri klasörü kökü")
    args = parser.parse_args()

    print(f"\nBB Fade — Multi-Coin Test  (SL={SL_M}×ATR TP={TP_M}×ATR, sıfır tuning)")
    print(f"Train: May 2025 – Dec 2025   Test: Jan 2026 – Apr 2026")
    print("=" * 110)

    results: dict[str, list] = {}
    oos_positive: list[str] = []

    for sym in args.coins:
        df_raw = load(sym, args.base)
        if df_raw is None:
            print(f"{sym:<6}  ✗ veri bulunamadı  →  download_data.py ile indir")
            continue

        df_1h = resample_1h(df_raw)
        months = df_1h.resample("ME").last().shape[0]
        trades = run(df_1h)
        results[sym] = trades

        print(stat_line(sym, trades, months))
        if trades:
            print(monthly_table(sym, trades))

        te = [t for t in trades if t["ts_entry"] >= SPLIT]
        te_pnl = sum(t["pnl"] for t in te)
        if len(te) > 5 and te_pnl > 0:
            oos_positive.append(sym)

    # ── Portfolio özet ────────────────────────────────────────────────────────
    if len(results) >= 2:
        print()
        print("=" * 110)
        print("PORTFOLIO — sadece OOS pozitif coinler")
        oos_trades = {s: results[s] for s in oos_positive if s in results}

        if oos_trades:
            port = sim_portfolio(oos_trades)
            n = len(oos_trades)
            print(f"Seçilen coinler: {list(oos_trades.keys())}  ({n} coin)")
            print(f"Başlangıç bakiye: ${port['total_bal']:,.0f}  "
                  f"(coin başı ${BAL:,.0f})")
            print(f"Toplam PnL: ${port['total_pnl']:>+,.0f}  "
                  f"({port['total_pnl']/port['total_bal']*100:>+.1f}%)")
        else:
            print("OOS döneminde pozitif coin yok → BTC'de kal")

    print()
    print("Korelasyon notu: Eğer birden fazla coin OOS pozitifse,")
    print("kötü ay sayısını karşılaştır — hepsi aynı anda batıyorsa")
    print("gerçek çeşitlendirme değil, sadece kaldıraç demektir.")


if __name__ == "__main__":
    main()
