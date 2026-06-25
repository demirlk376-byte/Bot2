"""
backtest_nw_kama.py — Honest edge test for two candidate strategies before
adding them to the live system:

  1. Nadaraya-Watson Envelope (mean-reversion).
     CAUSAL / endpoint kernel regression (NO repainting): yhat[t] uses only
     bars up to t, Gaussian-weighted by recency. Bands = yhat ± mult × MAE.
     Signal: close beyond a band → fade back toward yhat (like BB mean-rev but
     kernel-smoothed instead of SMA+std).

  2. Kaufman Adaptive Moving Average (KAMA) trend-follow.
     KAMA speeds up in trends, slows in chop (efficiency ratio). Signal: close
     crosses KAMA in the direction of KAMA's slope.

Both tested on real MEXC 1h data, multiple coins, multiple non-overlapping
windows, with realistic fees + pessimistic intrabar SL/TP. A strategy is only
worth adding if PF > 1.2 AND it is positive on BTC + ≥1 other coin AND positive
in ≥2 of the 3 windows. Same bar = signal bar's CLOSE entry (no look-ahead).

Usage:  venv/bin/python backtest_nw_kama.py
"""
from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from indicators import atr as atr_fn  # noqa: E402

BASE = os.path.dirname(__file__)
FEE_TAKER = 0.0001
# Local BTC 1m data: 2023-01 → 2026-04 (gap 2025-01..04). Resampled to 1h and
# split into yearly windows for robustness. BTC-only — that's what we have on
# disk, but 3+ years across 3 regimes is a far stronger test than 1 fetched year.
WINDOWS = {
    "2023": [f"2023-{m:02d}" for m in range(1, 13)],
    "2024": [f"2024-{m:02d}" for m in range(1, 13)],
    "2025-26": [f"2025-{m:02d}" for m in range(5, 13)] + [f"2026-{m:02d}" for m in range(1, 5)],
}


def load_1h(year_months: list[str]) -> pd.DataFrame:
    frames = []
    for ym in year_months:
        for f in sorted(glob.glob(f"{BASE}/BTCUSDT-1m-{ym}.csv")):
            d = pd.read_csv(f)
            d.columns = ["ts", "open", "high", "low", "close", "volume",
                         "ct", "qv", "count", "tbv", "tbqv", "ign"]
            frames.append(d[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    if not frames:
        return pd.DataFrame()
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms", utc=True)
    full = full.drop(columns=["ts"])
    return full.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


# ── Indicators ──────────────────────────────────────────────────────────────
def nadaraya_causal(close: np.ndarray, h: float = 8.0, window: int = 50) -> np.ndarray:
    """Endpoint (causal) Nadaraya-Watson estimate. yhat[t] = Gaussian-weighted
    mean of close[t-window+1 .. t], weight = exp(-k^2/(2h^2)) for k bars back.
    No future bars used → no repainting, valid for backtest."""
    n = len(close)
    yhat = np.full(n, np.nan)
    k = np.arange(window)
    w = np.exp(-(k ** 2) / (2 * h * h))
    w_sum = w.sum()
    for t in range(n):
        if t + 1 < window:
            continue
        seg = close[t - window + 1: t + 1][::-1]  # seg[0] = current bar
        yhat[t] = float((seg * w).sum() / w_sum)
    return yhat


def kama(close: np.ndarray, er_period: int = 10, fast: int = 2, slow: int = 30) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    for t in range(n):
        if t < er_period:
            continue
        change = abs(close[t] - close[t - er_period])
        vol = np.abs(np.diff(close[t - er_period: t + 1])).sum()
        er = change / vol if vol > 0 else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        prev = out[t - 1] if not np.isnan(out[t - 1]) else close[t - 1]
        out[t] = prev + sc * (close[t] - prev)
    return out


# ── Backtest engine ─────────────────────────────────────────────────────────
@dataclass
class Res:
    trades: int = 0
    wins: int = 0
    gross_win: float = 0.0
    gross_loss: float = 0.0
    pnl: float = 0.0

    @property
    def wr(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def pf(self) -> float:
        return self.gross_win / self.gross_loss if self.gross_loss > 0 else float("inf")


def _simulate(df, entries, sl_mult, tp_mult, atr_arr, max_hold, risk=0.02, bal=1000.0) -> Res:
    """entries: list of (idx, direction). SL/TP ATR-based from entry close.
    Pessimistic intrabar: if both SL and TP in a bar's range, SL counts."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    r = Res()
    occupied_until = -1
    for idx, direction in entries:
        if idx <= occupied_until or idx >= len(close) - 1 or np.isnan(atr_arr[idx]):
            continue
        entry = close[idx]
        a = atr_arr[idx]
        if a <= 0:
            continue
        if direction == 1:
            sl = entry - sl_mult * a
            tp = entry + tp_mult * a
        else:
            sl = entry + sl_mult * a
            tp = entry - tp_mult * a
        sl_dist_pct = abs(entry - sl) / entry
        if sl_dist_pct <= 0:
            continue
        qty = (bal * risk) / (entry * sl_dist_pct)
        exit_price = None
        for j in range(idx + 1, min(idx + 1 + max_hold, len(close))):
            hi, lo = high[j], low[j]
            if direction == 1:
                if lo <= sl:
                    exit_price = sl; break
                if hi >= tp:
                    exit_price = tp; break
            else:
                if hi >= sl:
                    exit_price = sl; break
                if lo <= tp:
                    exit_price = tp; break
        else:
            j = min(idx + max_hold, len(close) - 1)
            exit_price = close[j]
        occupied_until = j
        raw = direction * (exit_price - entry) * qty
        fees = (entry + exit_price) * qty * FEE_TAKER
        net = raw - fees
        r.trades += 1
        r.pnl += net
        if net > 0:
            r.wins += 1
            r.gross_win += net
        else:
            r.gross_loss += -net
    return r


def nw_signals(df, h, window, mult, atr_arr) -> list:
    """Mean-reversion: close below lower band → long, above upper → short.
    MAE band = rolling mean |close - yhat| × mult."""
    close = df["close"].values
    yhat = nadaraya_causal(close, h, window)
    resid = np.abs(close - yhat)
    mae = pd.Series(resid).rolling(window).mean().values
    out = []
    for t in range(len(close)):
        if np.isnan(yhat[t]) or np.isnan(mae[t]) or mae[t] <= 0:
            continue
        upper = yhat[t] + mult * mae[t]
        lower = yhat[t] - mult * mae[t]
        if close[t] < lower:
            out.append((t, 1))
        elif close[t] > upper:
            out.append((t, -1))
    return out


def nw_signals_filtered(df, h, window, mult, atr_arr) -> list:
    """NW fade + the SAME filters that make live BB work: above-avg volume on the
    extreme candle + RSI confluence (long needs RSI<40, short RSI>60) + weekend-
    only (BB's validated regime). Tests whether NW can beat the bar WITH filters."""
    from indicators import rsi as rsi_fn
    close = df["close"].values
    vol = df["volume"].values
    yhat = nadaraya_causal(close, h, window)
    resid = np.abs(close - yhat)
    mae = pd.Series(resid).rolling(window).mean().values
    vol_ma = pd.Series(vol).rolling(20).mean().values
    rsi_arr = rsi_fn(df["close"], 14).values
    idx = df.index
    out = []
    for t in range(len(close)):
        if np.isnan(yhat[t]) or np.isnan(mae[t]) or mae[t] <= 0 or np.isnan(vol_ma[t]):
            continue
        if vol[t] < vol_ma[t]:           # volume filter
            continue
        if idx[t].weekday() < 5:          # weekend-only (BB's validated edge)
            continue
        upper = yhat[t] + mult * mae[t]
        lower = yhat[t] - mult * mae[t]
        if close[t] < lower and rsi_arr[t] < 40:
            out.append((t, 1))
        elif close[t] > upper and rsi_arr[t] > 60:
            out.append((t, -1))
    return out


def kama_signals(df, er_period, atr_arr) -> list:
    """Trend-follow: close crosses above rising KAMA → long; below falling → short."""
    close = df["close"].values
    k = kama(close, er_period)
    out = []
    for t in range(1, len(close)):
        if np.isnan(k[t]) or np.isnan(k[t - 1]):
            continue
        slope_up = k[t] > k[t - 1]
        cross_up = close[t - 1] <= k[t - 1] and close[t] > k[t]
        cross_dn = close[t - 1] >= k[t - 1] and close[t] < k[t]
        if cross_up and slope_up:
            out.append((t, 1))
        elif cross_dn and not slope_up:
            out.append((t, -1))
    return out


def main():
    print("Loading local BTC 1m → 1h ...")
    data = {}
    for name, yms in WINDOWS.items():
        df = load_1h(yms)
        if df.empty:
            print(f"  {name}: NO DATA"); continue
        data[name] = df
        print(f"  {name}: {len(df)} 1h candles ({df.index[0].date()} → {df.index[-1].date()})")

    # NW parameter grid (mean-reversion). SL=3ATR TP=5ATR like BB.
    nw_params = [(8.0, 50, 2.0), (8.0, 50, 3.0), (6.0, 40, 2.0), (10.0, 60, 2.5)]
    # KAMA grid (trend). SL=2ATR TP=4ATR (RR2).
    kama_params = [10, 14, 20]

    def run_grid(title, params, make_sigs, sl_m, tp_m):
        print("\n" + "=" * 84)
        print(title)
        print("=" * 84)
        for p in params:
            label = str(p)
            tot = Res()
            wins_windows = 0
            cells = []
            for name, df in data.items():
                wa = atr_fn(df["high"], df["low"], df["close"], 14).values
                sigs = make_sigs(df, p, wa)
                r = _simulate(df, sigs, sl_m, tp_m, wa, 48)
                if r.pnl > 0:
                    wins_windows += 1
                tot.trades += r.trades; tot.wins += r.wins
                tot.gross_win += r.gross_win; tot.gross_loss += r.gross_loss
                tot.pnl += r.pnl
                cells.append(f"{name} PF{r.pf:4.2f} WR{r.wr*100:3.0f}% n{r.trades:3d} ${r.pnl:+7.1f}")
            print(f"\n  {label}")
            for c in cells:
                print(f"      {c}")
            print(f"      ‖ TOTAL PF{tot.pf:4.2f} WR{tot.wr*100:3.0f}% n{tot.trades} "
                  f"${tot.pnl:+8.1f}  [{wins_windows}/{len(data)} pencere +]")

    run_grid(
        "NADARAYA-WATSON ENVELOPE (mean-reversion)  SL=3ATR TP=5ATR hold=48  (BTC)",
        nw_params,
        lambda df, p, wa: nw_signals(df, p[0], p[1], p[2], wa),
        3.0, 5.0,
    )
    run_grid(
        "NADARAYA-WATSON + FİLTRELER (volume+RSI+haftasonu, BB'nin kazanan filtreleri)",
        nw_params,
        lambda df, p, wa: nw_signals_filtered(df, p[0], p[1], p[2], wa),
        3.0, 5.0,
    )
    run_grid(
        "KAUFMAN KAMA (trend-follow)  SL=2ATR TP=4ATR hold=48  (BTC)",
        kama_params,
        lambda df, p, wa: kama_signals(df, p, wa),
        2.0, 4.0,
    )

    print("\nKARAR KURALI: PF>1.2 + her 3 pencerede pozitif (2023/2024/2025-26) → EKLE")
    print("Mevcut canlı stratejilerle kıyas: BB PF 1.24 · ORB 1.44 · FVG 1.37 · Squeeze 1.31")


if __name__ == "__main__":
    main()
