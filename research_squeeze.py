"""
research_squeeze.py — Volatility Squeeze (BB inside Keltner Channel) edge araştırması

FİKİR:
  Bollinger Bands (20, 2.0) Keltner Channel (20 EMA, 1.5×ATR) içine girince piyasa
  enerji biriktiriyor (düşük volatilite = sıkışma). BB dışarı çıkınca momentum
  patlaması — patlamanın YÖNÜNDE gir. Bu tam tersi BB mean-rev: orada fading yapıyoruz,
  burada MOMENTUM takip ediyoruz. Birbirini tamamlıyor.

  Keltner Channel:
    mid   = EMA(close, 20)
    upper = mid + mult × ATR(20)
    lower = mid - mult × ATR(20)
  Squeeze = BB_upper < KC_upper AND BB_lower > KC_lower

TESTLER:
  A) 1h standalone
  B) 4h standalone
  C) MTF: 4h squeeze var + 1h aynı yönde kırılım (4h sıkışıyor, 1h tetikliyor)
  D) MTF: 1h sinyal + 4h momentum aynı yön filtresi

MOmentum Yönü:
  close[i] > kc_mid[i] → long (fiyat KC orta çizgisinin üstünde → yukarı momentum)
  close[i] < kc_mid[i] → short
  (MACD histogram alternatifi de test edilir)

DİSİPLİN: TRAIN(<2026) + TEST(≥2026) + yıl-yıl PF, look-ahead yok.

Run: python research_squeeze.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import atr as atr_fn, ema as ema_fn

COST   = 0.0002   # 0.02% per side (taker)
SPLIT  = pd.Timestamp("2026-01-01", tz="UTC")
RISK   = 0.02
BAL    = 10_000.0


# ── data loading ────────────────────────────────────────────────────────────

def load_1m() -> pd.DataFrame:
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts","open","high","low","close","volume",
                      "ct","qv","count","tbv","tbqv","ign"]
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    m = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m.drop(columns=["ts"])


def resample(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df_1m.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


# ── indicators ──────────────────────────────────────────────────────────────

def bollinger(close: pd.Series, period=20, std=2.0):
    mid = close.rolling(period).mean()
    sd  = close.rolling(period).std()
    return mid + std * sd, mid, mid - std * sd   # upper, mid, lower


def keltner(high: pd.Series, low: pd.Series, close: pd.Series,
            period=20, mult=1.5):
    mid   = ema_fn(close, period)
    at    = atr_fn(high, low, close, period)
    return mid + mult * at, mid, mid - mult * at  # upper, mid, lower


def macd_hist(close: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    ema_fast = ema_fn(close, fast)
    ema_slow = ema_fn(close, slow)
    macd_line = ema_fast - ema_slow
    signal    = ema_fn(macd_line, sig)
    return macd_line - signal


def squeeze_signals(df: pd.DataFrame, kc_mult=1.5,
                    min_squeeze_bars=3, dir_method="price") -> pd.DataFrame:
    """Compute squeeze indicator columns for a OHLCV dataframe."""
    bb_up, bb_mid, bb_lo = bollinger(df["close"])
    kc_up, kc_mid, kc_lo = keltner(df["high"], df["low"], df["close"], mult=kc_mult)
    at = atr_fn(df["high"], df["low"], df["close"], 14)

    in_sq = (bb_up < kc_up) & (bb_lo > kc_lo)
    # count consecutive squeeze bars
    sq_count = in_sq.groupby((~in_sq).cumsum()).cumcount()

    was_sq = in_sq.shift(1).fillna(False)
    # squeeze release: was in squeeze (for at least min_squeeze_bars) → now out
    sq_fire = (~in_sq) & was_sq & (sq_count.shift(1).fillna(0) >= min_squeeze_bars)

    if dir_method == "price":
        direction = np.where(df["close"] > kc_mid, 1, -1)
    else:  # macd
        mh = macd_hist(df["close"])
        direction = np.where(mh > 0, 1, -1)

    out = df.copy()
    out["bb_up"] = bb_up; out["bb_lo"] = bb_lo
    out["kc_up"] = kc_up; out["kc_lo"] = kc_lo; out["kc_mid"] = kc_mid
    out["in_sq"] = in_sq; out["sq_count"] = sq_count; out["sq_fire"] = sq_fire
    out["sq_dir"] = direction
    out["atr14"] = at
    return out


# ── backtester ───────────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, sl_atr=2.0, rr=2.0,
             max_hold=20, label="") -> dict:
    """Simple sequential bar-by-bar backtest (no re-entry while in trade)."""
    bal = BAL
    trades = []
    pos = None  # {"dir", "entry", "sl", "tp", "bars", "ts"}

    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    fire  = df["sq_fire"].values
    dirv  = df["sq_dir"].values
    atr   = df["atr14"].values
    idx   = df.index

    for i in range(1, len(df)):
        if pos is not None:
            d = pos["dir"]
            hit_sl = low[i] <= pos["sl"] if d == 1 else high[i] >= pos["sl"]
            hit_tp = high[i] >= pos["tp"] if d == 1 else low[i] <= pos["tp"]
            expired = (i - pos["bar"]) >= max_hold

            exit_price = None
            reason = ""
            if hit_sl and hit_tp:
                # both hit same bar: pessimistic — SL wins
                exit_price = pos["sl"]; reason = "sl"
            elif hit_sl:
                exit_price = pos["sl"]; reason = "sl"
            elif hit_tp:
                exit_price = pos["tp"]; reason = "tp"
            elif expired:
                exit_price = close[i]; reason = "maxhold"

            if exit_price is not None:
                qty = pos["qty"]
                pnl = (exit_price - pos["entry"]) * d * qty
                fee = (pos["entry"] + exit_price) * qty * COST
                net = pnl - fee
                bal += net
                trades.append({
                    "ts": idx[i], "dir": d, "entry": pos["entry"],
                    "exit": exit_price, "pnl": net, "reason": reason,
                    "year": idx[i].year,
                })
                pos = None

        if pos is None and fire[i] and atr[i] > 0:
            d = int(dirv[i])
            entry = close[i]
            sl    = entry - d * sl_atr * atr[i]
            tp    = entry + d * rr * sl_atr * atr[i]
            sl_d  = abs(entry - sl)
            qty   = (bal * RISK) / sl_d if sl_d > 0 else 0
            if qty > 0:
                pos = {"dir": d, "entry": entry, "sl": sl, "tp": tp,
                       "bar": i, "qty": qty}

    if not trades:
        return {"label": label, "n": 0, "pf": 0, "pf_tr": 0, "pf_te": 0}

    t = pd.DataFrame(trades)
    t["train"] = t["ts"] < SPLIT

    def pf(sub):
        if len(sub) == 0: return float("nan")
        w = sub[sub["pnl"] > 0]["pnl"].sum()
        l = abs(sub[sub["pnl"] < 0]["pnl"].sum())
        return round(w / l, 2) if l > 0 else float("inf")

    def ypf(sub, yr):
        s = sub[sub["year"] == yr]
        return pf(s) if len(s) >= 3 else float("nan")

    tr = t[t["train"]]; te = t[~t["train"]]
    yrs = sorted(t["year"].unique())
    ypfs = {y: ypf(t, y) for y in yrs}

    return {
        "label": label,
        "n": len(t), "n_tr": len(tr), "n_te": len(te),
        "pf": pf(t), "pf_tr": pf(tr), "pf_te": pf(te),
        "wr": round((t["pnl"] > 0).mean() * 100, 1),
        "year_pf": ypfs,
    }


def print_result(r: dict):
    if r["n"] == 0:
        print(f"  {r['label']}: no trades"); return
    ystr = "  ".join(f"{y}:{v:.2f}" for y, v in r.get("year_pf", {}).items()
                     if not (isinstance(v, float) and np.isnan(v)))
    print(f"  {r['label']:50s}  n={r['n']:4d}  PF={r['pf']:.2f}"
          f"  TR={r['pf_tr']:.2f}  TE={r['pf_te']:.2f}  WR={r['wr']:.0f}%"
          f"  [{ystr}]")


# ── MTF helpers ─────────────────────────────────────────────────────────────

def backtest_mtf_4h_sq_1h_entry(df_1h: pd.DataFrame, df_4h_sq: pd.DataFrame,
                                  sl_atr=2.0, rr=2.0, max_hold=20,
                                  label="MTF 4h-sq+1h-entry") -> dict:
    """4h squeeze active → take 1h squeeze fires in the same direction."""
    # Forward-fill 4h squeeze state onto 1h index
    sq4 = df_4h_sq[["in_sq", "sq_dir"]].copy()
    sq4.index = sq4.index + pd.Timedelta("4h")  # shift: 4h bar closes at open+4h
    sq4_ff = sq4.reindex(df_1h.index, method="ffill")

    df = df_1h.copy()
    df["4h_in_sq"] = sq4_ff["in_sq"].fillna(False)
    df["4h_dir"]   = sq4_ff["sq_dir"].fillna(0)

    # Only fire if 4h is in squeeze AND 1h fires AND directions match
    df["sq_fire_mtf"] = (
        df["sq_fire"] &
        df["4h_in_sq"] &
        (df["sq_dir"] == df["4h_dir"])
    )
    df_mod = df.copy()
    df_mod["sq_fire"] = df_mod["sq_fire_mtf"]
    return backtest(df_mod, sl_atr=sl_atr, rr=rr, max_hold=max_hold, label=label)


def backtest_mtf_1h_sq_4h_trend(df_1h: pd.DataFrame, df_4h: pd.DataFrame,
                                  sl_atr=2.0, rr=2.0, max_hold=20,
                                  label="MTF 1h-sq+4h-trend") -> dict:
    """1h squeeze fires + 4h momentum same direction filter."""
    dir4 = df_4h[["sq_dir"]].copy()
    dir4.index = dir4.index + pd.Timedelta("4h")
    dir4_ff = dir4.reindex(df_1h.index, method="ffill")

    df = df_1h.copy()
    df["4h_dir"] = dir4_ff["sq_dir"].fillna(0)
    df["sq_fire_mtf"] = df["sq_fire"] & (df["sq_dir"] == df["4h_dir"])
    df_mod = df.copy()
    df_mod["sq_fire"] = df_mod["sq_fire_mtf"]
    return backtest(df_mod, sl_atr=sl_atr, rr=rr, max_hold=max_hold, label=label)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading data...")
    m1 = load_1m()
    if m1.empty:
        print("No data found."); return

    df_1h = resample(m1, "1h")
    df_4h = resample(m1, "4h")
    df_15m = resample(m1, "15min")
    print(f"1m rows={len(m1):,}  1h bars={len(df_1h)}  4h bars={len(df_4h)}")

    results = []

    # ── SECTION A: 1h standalone ────────────────────────────────────────────
    print("\n=== A) 1h Standalone Squeeze ===")
    for kc_mult in (1.0, 1.5, 2.0):
        for min_sq in (3, 5):
            for dir_m in ("price", "macd"):
                for sl_atr, rr in ((1.5, 2.0), (2.0, 1.5), (2.0, 2.0), (2.0, 2.5)):
                    df = squeeze_signals(df_1h, kc_mult=kc_mult,
                                        min_squeeze_bars=min_sq, dir_method=dir_m)
                    lbl = f"1h KC{kc_mult} sq>={min_sq} {dir_m} SL{sl_atr} RR{rr}"
                    r = backtest(df, sl_atr=sl_atr, rr=rr, label=lbl)
                    results.append(r)
                    print_result(r)

    # ── SECTION B: 4h standalone ────────────────────────────────────────────
    print("\n=== B) 4h Standalone Squeeze ===")
    for kc_mult in (1.0, 1.5, 2.0):
        for min_sq in (2, 3):
            for dir_m in ("price", "macd"):
                for sl_atr, rr in ((1.5, 2.0), (2.0, 2.0), (2.0, 2.5)):
                    df = squeeze_signals(df_4h, kc_mult=kc_mult,
                                        min_squeeze_bars=min_sq, dir_method=dir_m)
                    lbl = f"4h KC{kc_mult} sq>={min_sq} {dir_m} SL{sl_atr} RR{rr}"
                    r = backtest(df, sl_atr=sl_atr, rr=rr, max_hold=6, label=lbl)
                    results.append(r)
                    print_result(r)

    # ── SECTION C: MTF — 4h squeeze + 1h entry ──────────────────────────────
    print("\n=== C) MTF: 4h squeeze active → 1h squeeze release in same direction ===")
    for kc_mult in (1.0, 1.5):
        for min_sq_4h in (2, 3):
            for min_sq_1h in (3, 5):
                for dir_m in ("price", "macd"):
                    for sl_atr, rr in ((1.5, 2.0), (2.0, 2.0), (2.0, 2.5)):
                        df1 = squeeze_signals(df_1h, kc_mult=kc_mult,
                                              min_squeeze_bars=min_sq_1h, dir_method=dir_m)
                        df4 = squeeze_signals(df_4h, kc_mult=kc_mult,
                                              min_squeeze_bars=min_sq_4h, dir_method=dir_m)
                        lbl = (f"MTF 4h-sq>={min_sq_4h}+1h-entry>={min_sq_1h} "
                               f"KC{kc_mult} {dir_m} SL{sl_atr} RR{rr}")
                        r = backtest_mtf_4h_sq_1h_entry(
                            df1, df4, sl_atr=sl_atr, rr=rr, label=lbl)
                        results.append(r)
                        print_result(r)

    # ── SECTION D: MTF — 1h squeeze + 4h trend filter ───────────────────────
    print("\n=== D) MTF: 1h squeeze fires + 4h momentum same direction ===")
    for kc_mult in (1.0, 1.5):
        for min_sq in (3, 5):
            for dir_m in ("price", "macd"):
                for sl_atr, rr in ((1.5, 2.0), (2.0, 2.0), (2.0, 2.5)):
                    df1 = squeeze_signals(df_1h, kc_mult=kc_mult,
                                          min_squeeze_bars=min_sq, dir_method=dir_m)
                    df4 = squeeze_signals(df_4h, kc_mult=kc_mult,
                                          min_squeeze_bars=2, dir_method=dir_m)
                    lbl = (f"MTF 1h-sq>={min_sq}+4h-trend "
                           f"KC{kc_mult} {dir_m} SL{sl_atr} RR{rr}")
                    r = backtest_mtf_1h_sq_4h_trend(
                        df1, df4, sl_atr=sl_atr, rr=rr, label=lbl)
                    results.append(r)
                    print_result(r)

    # ── BEST SUMMARY ────────────────────────────────────────────────────────
    print("\n" + "="*80)
    print("TOP 15 configs by TEST PF (min 10 total trades, both periods positive):")
    good = [r for r in results
            if r.get("n", 0) >= 10
            and r.get("pf_tr", 0) > 1.0
            and r.get("pf_te", 0) > 1.0
            and not (isinstance(r.get("pf_te"), float) and np.isnan(r.get("pf_te", 0)))]
    good.sort(key=lambda x: x.get("pf_te", 0), reverse=True)
    for r in good[:15]:
        print_result(r)

    if not good:
        print("No configs passed train+test filter.")
        print("\nTOP 10 by overall PF (relaxed filter):")
        relaxed = [r for r in results if r.get("n", 0) >= 10]
        relaxed.sort(key=lambda x: x.get("pf", 0), reverse=True)
        for r in relaxed[:10]:
            print_result(r)


if __name__ == "__main__":
    main()
