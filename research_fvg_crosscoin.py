"""
Cross-coin robustness check: FVG strategy on ETH and SOL.

Tests the IDENTICAL FVG params validated on BTC 1h:
  gap >= 0.5×ATR, RR 2.5, EMA200 trend, limit retest entry,
  same-bar SL counted as loss, look-ahead fixed.

Downloads data from data.binance.vision (zip files, spot 1h).
Zero re-tuning — same params as BTC to avoid overfitting.

Run on VPS:
  python research_fvg_crosscoin.py

Requires: pip install requests pandas numpy ta
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

# ── Params (IDENTICAL to BTC validated params) ──────────────────────────
MIN_GAP_ATR = 0.5
RR = 2.5
EMA_PERIOD = 200
SL_BUFFER_ATR = 0.3
ZONE_EXPIRE = 24        # bars a zone stays active
BAL = 10_000.0
RISK_PCT = 0.02         # 2% risk per trade
FEE = 0.0001            # maker entry (limit), conservative

COINS = ["ETHUSDT", "SOLUSDT"]
YEARS = [2023, 2024, 2025]
TRAIN_YEARS = {2023, 2024}
TEST_YEARS  = {2025}


# ── Data download ────────────────────────────────────────────────────────
def _download_month(symbol: str, year: int, month: int) -> pd.DataFrame | None:
    base = "https://data.binance.vision/data/spot/monthly/klines"
    fname = f"{symbol}-1h-{year}-{month:02d}.zip"
    url = f"{base}/{symbol}/1h/{fname}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open(z.namelist()[0]) as f:
                df = pd.read_csv(f, header=None,
                    names=["ts","open","high","low","close","volume",
                           "close_ts","qv","trades","tbbv","tbqv","ignore"])
        # Newer files ship with a header row — drop it if "ts" isn't numeric.
        df = df[pd.to_numeric(df["ts"], errors="coerce").notna()].copy()
        df["ts"] = pd.to_numeric(df["ts"])
        # Binance switched some files from ms to µs timestamps — detect by magnitude.
        unit = "us" if df["ts"].iloc[0] > 1e15 else "ms"
        df["ts"] = pd.to_datetime(df["ts"], unit=unit, utc=True)
        df = df.set_index("ts")[["open","high","low","close","volume"]].astype(float)
        return df
    except Exception as e:
        print(f"  warn: {symbol} {year}-{month:02d}: {e}")
        return None


def load_data(symbol: str, years: list[int]) -> pd.DataFrame:
    frames = []
    for y in years:
        for m in range(1, 13):
            df = _download_month(symbol, y, m)
            if df is not None:
                frames.append(df)
    if not frames:
        raise RuntimeError(f"No data for {symbol}")
    return pd.concat(frames).sort_index()


# ── Indicators ───────────────────────────────────────────────────────────
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr_wilder(high, low, close, period=14) -> np.ndarray:
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    c = np.array(close, dtype=float)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    atr_arr = np.zeros(len(tr))
    atr_arr[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr_arr[i] = (atr_arr[i - 1] * (period - 1) + tr[i]) / period
    return atr_arr


# ── FVG Backtest ─────────────────────────────────────────────────────────
def run_fvg_backtest(df: pd.DataFrame, label: str = "") -> dict:
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    n     = len(df)

    atr_arr  = atr_wilder(high, low, close, 14)
    ema_arr  = ema(df["close"], EMA_PERIOD).values

    trades = []
    active_zones: list[dict] = []  # {"dir","top","bottom","born","age"}
    pos = None  # {"dir","entry","sl","tp","open_bar"}

    def close_trade(exit_px, bar_i, reason):
        nonlocal pos
        if pos is None:
            return
        pnl_pct = pos["dir"] * (exit_px - pos["entry"]) / pos["entry"]
        pnl_usdt = pnl_pct * pos["risk_usdt"] / (pos["sl_dist"] / pos["entry"])
        fee_usdt = pos["notional"] * FEE
        trades.append({
            "bar": bar_i,
            "dir": pos["dir"],
            "entry": pos["entry"],
            "exit": exit_px,
            "pnl": pnl_usdt - fee_usdt,
            "reason": reason,
            "year": df.index[bar_i].year,
        })
        pos = None

    for i in range(max(EMA_PERIOD, 14) + 3, n):
        atr_val = atr_arr[i]
        if atr_val <= 0:
            continue

        # ── SL/TP check for open position ──
        if pos is not None:
            o = close[i - 1]  # pessimistic: use previous close for limit orders
            if pos["dir"] == 1:
                if low[i] <= pos["sl"]:
                    close_trade(pos["sl"], i, "sl")
                elif high[i] >= pos["tp"]:
                    close_trade(pos["tp"], i, "tp")
            else:
                if high[i] >= pos["sl"]:
                    close_trade(pos["sl"], i, "sl")
                elif low[i] <= pos["tp"]:
                    close_trade(pos["tp"], i, "tp")

        # ── Age/expire zones ──
        active_zones = [z for z in active_zones if z["age"] < ZONE_EXPIRE and z["born"] < i]
        for z in active_zones:
            z["age"] += 1

        # ── Detect new FVG on bar i (3-candle: i-2, i-1, i) ──
        # Bullish: high[i-2] < low[i], gap >= 0.5*ATR
        if high[i - 2] < low[i] and (low[i] - high[i - 2]) >= MIN_GAP_ATR * atr_val:
            active_zones.append({
                "dir": 1, "top": float(low[i]), "bottom": float(high[i - 2]),
                "age": 0, "born": i,
            })
        # Bearish: low[i-2] > high[i], gap >= 0.5*ATR
        if low[i - 2] > high[i] and (low[i - 2] - high[i]) >= MIN_GAP_ATR * atr_val:
            active_zones.append({
                "dir": -1, "top": float(low[i - 2]), "bottom": float(high[i]),
                "age": 0, "born": i,
            })

        # ── Entry check ──
        if pos is not None:
            continue  # already in trade

        ema_val = ema_arr[i]
        if np.isnan(ema_val):
            continue

        cur_low   = low[i]
        cur_high  = high[i]
        cur_close = close[i]

        for z in list(active_zones):
            if z["born"] >= i:
                continue  # look-ahead fix: zone born this bar, no entry

            top    = z["top"]
            bottom = z["bottom"]
            sl_dist = (top - bottom) + SL_BUFFER_ATR * atr_val

            # Bullish FVG retest: price dips into zone, closes above bottom
            if z["dir"] == 1 and cur_low <= top and cur_close > bottom:
                if cur_close <= ema_val:
                    continue  # must be above EMA200
                ep = top
                risk_usdt = BAL * RISK_PCT
                qty       = risk_usdt / sl_dist
                notional  = qty * ep
                active_zones.remove(z)
                pos = {
                    "dir": 1, "entry": ep, "sl": ep - sl_dist,
                    "tp": ep + RR * sl_dist,
                    "risk_usdt": risk_usdt, "sl_dist": sl_dist,
                    "notional": notional, "open_bar": i,
                }
                break

            # Bearish FVG retest: price rallies into zone, closes below top
            if z["dir"] == -1 and cur_high >= bottom and cur_close < top:
                if cur_close >= ema_val:
                    continue  # must be below EMA200
                ep = bottom
                risk_usdt = BAL * RISK_PCT
                qty       = risk_usdt / sl_dist
                notional  = qty * ep
                active_zones.remove(z)
                pos = {
                    "dir": -1, "entry": ep, "sl": ep + sl_dist,
                    "tp": ep - RR * sl_dist,
                    "risk_usdt": risk_usdt, "sl_dist": sl_dist,
                    "notional": notional, "open_bar": i,
                }
                break

    # ── Stats ──
    if not trades:
        return {"label": label, "n": 0, "pf": 0.0, "wr": 0.0, "years": {}}

    t = pd.DataFrame(trades)
    wins = t[t["pnl"] > 0]
    loss = t[t["pnl"] <= 0]
    gross_w = wins["pnl"].sum() if len(wins) else 0.0
    gross_l = abs(loss["pnl"].sum()) if len(loss) else 0.001
    pf = gross_w / gross_l if gross_l > 0 else 99.0

    by_year = {}
    for yr, grp in t.groupby("year"):
        w = grp[grp["pnl"] > 0]
        l = grp[grp["pnl"] <= 0]
        gw = w["pnl"].sum() if len(w) else 0.0
        gl = abs(l["pnl"].sum()) if len(l) else 0.001
        by_year[int(yr)] = {
            "n": len(grp),
            "pf": round(gw / gl if gl > 0 else 99.0, 2),
            "wr": round(len(w) / len(grp) * 100, 1),
            "pnl": round(grp["pnl"].sum(), 1),
        }

    return {
        "label": label,
        "n": len(t),
        "pf": round(pf, 2),
        "wr": round(len(wins) / len(t) * 100, 1),
        "pnl_total": round(t["pnl"].sum(), 1),
        "years": by_year,
    }


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("FVG Cross-Coin Robustness Check  (params: BTC 1h validated)")
    print(f"gap>=0.5×ATR, RR={RR}, EMA{EMA_PERIOD}, look-ahead fixed")
    print(f"Same-bar SL counted as loss  |  Fee: {FEE*100:.2f}% (maker)")
    print("=" * 62)

    # BTC reference (print from memory — already computed)
    print("\n[REFERENCE — BTC 1h  2023-2026]")
    print("  TRAIN 2023-24 : PF 1.43  n=416")
    print("  TEST  2025-26 : PF 1.28  n=230")
    print("  year-by-year: 2023:1.43 | 2024:1.44 | 2025:1.17 | 2026:1.55")

    for symbol in COINS:
        print(f"\n{'─'*62}")
        print(f"  Downloading {symbol} 1h  {YEARS[0]}-{YEARS[-1]}...")
        try:
            df = load_data(symbol, YEARS)
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            continue
        print(f"  {len(df):,} bars loaded ({df.index[0].date()} → {df.index[-1].date()})")

        # Train
        df_train = df[df.index.year.isin(TRAIN_YEARS)]
        res_train = run_fvg_backtest(df_train, f"{symbol} TRAIN {sorted(TRAIN_YEARS)}")

        # Test
        df_test = df[df.index.year.isin(TEST_YEARS)]
        res_test = run_fvg_backtest(df_test, f"{symbol} TEST  {sorted(TEST_YEARS)}")

        print(f"\n  {symbol}  —  FVG 1h")
        print(f"  {'Period':<12} {'PF':>6} {'WR':>7} {'n':>5} {'PnL':>9}")
        print(f"  {'-'*44}")

        t_pf = res_train['pf']; t_wr = res_train['wr']; t_n = res_train['n']
        v_pf = res_test['pf'];  v_wr = res_test['wr'];  v_n = res_test['n']
        t_pnl = res_train.get('pnl_total', 0)
        v_pnl = res_test.get('pnl_total', 0)

        verdict_t = "✅" if t_pf >= 1.15 else ("⚠️" if t_pf >= 1.0 else "❌")
        verdict_v = "✅" if v_pf >= 1.10 else ("⚠️" if v_pf >= 1.0 else "❌")

        print(f"  {'TRAIN 23-24':<12} {t_pf:>6.2f} {t_wr:>6.1f}% {t_n:>5}  ${t_pnl:>8.0f}  {verdict_t}")
        print(f"  {'TEST  2025':<12} {v_pf:>6.2f} {v_wr:>6.1f}% {v_n:>5}  ${v_pnl:>8.0f}  {verdict_v}")

        print(f"\n  Year-by-year breakdown:")
        all_yrs = {}
        all_yrs.update(res_train["years"])
        all_yrs.update(res_test["years"])
        for yr in sorted(all_yrs):
            y = all_yrs[yr]
            tag = "TRAIN" if yr in TRAIN_YEARS else "TEST "
            ok = "✅" if y["pf"] >= 1.10 else ("⚠️" if y["pf"] >= 1.0 else "❌")
            print(f"    {yr} [{tag}]  PF {y['pf']:.2f}  WR {y['wr']:.1f}%  n={y['n']}  "
                  f"PnL ${y['pnl']:+.0f}  {ok}")

    print(f"\n{'='*62}")
    print("VERDICT KEY:")
    print("  ✅ PF>=1.15 (train) / PF>=1.10 (test)  — edge transfers")
    print("  ⚠️  PF 1.00-1.15  — marginal / noise")
    print("  ❌ PF<1.00  — edge does NOT transfer")
    print()
    print("If ETH + SOL both show ✅ on train+test → add to bot.")
    print("If only BTC works → FVG is BTC-specific, keep bot BTC-only.")
    print("="*62)


if __name__ == "__main__":
    main()
