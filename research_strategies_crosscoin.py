"""
Cross-coin robustness check: BB, ORB, Asia BO, S/R strategies on ETH and SOL.

IDENTICAL params to BTC live-bot (zero re-tuning):
  BB   : 20/2.0 band, vol filter, ATR SL=3x TP=5x, WEEKEND-ONLY, ADX<28
  ORB  : 14:00 UTC 60min range, SL=range, TP=2×range, 6h max hold
  Asia : 00-08 UTC range, 08:00 London breakout, SL=1×ATR TP=2×ATR, 6h max
  S/R  : pivot breakout (vol spike + 0.2% clear), SL=3×ATR TP=5×ATR

Data: data.binance.vision 1h spot 2023-2025
Split: TRAIN 2023-2024 | TEST 2025-2026

Run on VPS:
  python3 research_strategies_crosscoin.py
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

# ── Common params ────────────────────────────────────────────────────────
# Varsayılan: YENİ aday coinler (mevcut 5'li zaten doğrulandı). MEXC futures
# likiditesi yüksek + Binance spot verisi mevcut + fiyat aralığı çeşitli
# (düşük fiyatlı coinler küçük hesapta lot adımı avantajı sağlar).
# Kullanım:
#   python3 research_strategies_crosscoin.py                    # aday tarama
#   python3 research_strategies_crosscoin.py DOGEUSDT SUIUSDT   # seçili coinler
#   python3 research_strategies_crosscoin.py --current          # eski 5'li
import sys
CANDIDATES = ["DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT",
              "LTCUSDT", "DOTUSDT", "NEARUSDT", "SUIUSDT"]
CURRENT    = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
_args = [a for a in sys.argv[1:] if not a.startswith("-")]
COINS   = (CURRENT if "--current" in sys.argv
           else _args if _args else CANDIDATES)
YEARS   = [2023, 2024, 2025, 2026]   # eksik aylar (404) sessizce atlanır
TRAIN   = {2023, 2024}
TEST    = {2025, 2026}
BAL     = 10_000.0
FEE     = 0.0001      # maker entry + market exit (conservative)

# ── Indicator helpers ────────────────────────────────────────────────────
def ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def _atr_arr(high, low, close, p=14) -> np.ndarray:
    h, l, c = np.asarray(high, float), np.asarray(low, float), np.asarray(close, float)
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    a = np.zeros(len(tr)); a[p-1] = tr[:p].mean()
    for i in range(p, len(tr)):
        a[i] = (a[i-1] * (p-1) + tr[i]) / p
    return a

def _adx_arr(high, low, close, p=14) -> np.ndarray:
    h, l, c = np.asarray(high, float), np.asarray(low, float), np.asarray(close, float)
    n = len(h)
    pdm = np.maximum(h[1:] - h[:-1], 0)
    ndm = np.maximum(l[:-1] - l[1:], 0)
    pdm = np.where(pdm > ndm, pdm, 0.0)
    ndm = np.where(ndm > pdm, ndm, 0.0)
    atr14 = _atr_arr(h, l, c, p)
    def smooth(x):
        r = np.zeros(n)
        r[p] = x[:p].sum()
        for i in range(p+1, n):
            r[i] = r[i-1] - r[i-1]/p + x[i-1]
        return r
    pdi = np.zeros(n); ndi = np.zeros(n); dx = np.zeros(n)
    sp = smooth(pdm); sn = smooth(ndm)
    for i in range(p, n):
        if atr14[i] > 0:
            pdi[i] = 100 * sp[i] / atr14[i]
            ndi[i] = 100 * sn[i] / atr14[i]
        s = pdi[i] + ndi[i]
        dx[i] = 100 * abs(pdi[i] - ndi[i]) / s if s > 0 else 0.0
    adx_ = np.zeros(n)
    adx_[2*p-1] = dx[p:2*p].mean()
    for i in range(2*p, n):
        adx_[i] = (adx_[i-1]*(p-1) + dx[i]) / p
    return adx_

def _bb(close: np.ndarray, p=20, std=2.0):
    s = pd.Series(close)
    mid = s.rolling(p).mean().values
    sigma = s.rolling(p).std(ddof=0).values
    return mid + std*sigma, mid, mid - std*sigma   # upper, mid, lower

def _vol_ma(vol: np.ndarray, p=20) -> np.ndarray:
    return pd.Series(vol).rolling(p).mean().values

def _pivot_levels(high, low, close, lookback=48, n_levels=5):
    """Find S/R clusters from rolling highs/lows."""
    h = np.asarray(high, float); l = np.asarray(low, float)
    highs = []; lows = []
    for i in range(lookback, len(h)-1):
        if h[i] == h[max(0,i-lookback):i+1].max():
            highs.append(h[i])
        if l[i] == l[max(0,i-lookback):i+1].min():
            lows.append(l[i])
    return highs[-n_levels:], lows[-n_levels:]


# ── Data download (reuse from research_fvg_crosscoin.py) ────────────────
def load_data(symbol: str, years: list) -> pd.DataFrame:
    base = "https://data.binance.vision/data/spot/monthly/klines"
    frames = []
    for y in years:
        for m in range(1, 13):
            fname = f"{symbol}-1h-{y}-{m:02d}.zip"
            url = f"{base}/{symbol}/1h/{fname}"
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200: continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    with z.open(z.namelist()[0]) as f:
                        df = pd.read_csv(f, header=None,
                            names=["ts","open","high","low","close","volume",
                                   "ct","qv","n","tbbv","tbqv","ig"])
                df = df[pd.to_numeric(df["ts"], errors="coerce").notna()].copy()
                df["ts"] = pd.to_numeric(df["ts"])
                unit = "us" if df["ts"].iloc[0] > 1e15 else "ms"
                df["ts"] = pd.to_datetime(df["ts"], unit=unit, utc=True)
                df = df.set_index("ts")[["open","high","low","close","volume"]].astype(float)
                frames.append(df)
            except Exception as e:
                print(f"  warn {symbol} {y}-{m:02d}: {e}")
    if not frames: raise RuntimeError(f"No data for {symbol}")
    return pd.concat(frames).sort_index()


# ── Stats helper ─────────────────────────────────────────────────────────
def _stats(trades: list) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "wr": 0.0, "pnl": 0.0}
    t = pd.DataFrame(trades)
    w = t[t["pnl"] > 0]; l = t[t["pnl"] <= 0]
    gw = w["pnl"].sum() if len(w) else 0.0
    gl = abs(l["pnl"].sum()) if len(l) else 0.001
    return {"n": len(t), "pf": round(gw/gl if gl>0 else 99,2),
            "wr": round(len(w)/len(t)*100,1), "pnl": round(t["pnl"].sum(),1)}

def _by_year(trades: list) -> dict:
    out = {}
    for yr, grp in pd.DataFrame(trades).groupby("year"):
        w = grp[grp["pnl"] > 0]; l = grp[grp["pnl"] <= 0]
        gw = w["pnl"].sum() if len(w) else 0.0
        gl = abs(l["pnl"].sum()) if len(l) else 0.001
        out[int(yr)] = {"n": len(grp), "pf": round(gw/gl if gl>0 else 99,2),
                        "wr": round(len(w)/len(grp)*100,1), "pnl": round(grp["pnl"].sum(),1)}
    return out


# ════════════════════════════════════════════════════════════════════════
#  STRATEGY 1: BB Mean Reversion  (WEEKEND-ONLY, ADX<28 filter)
# ════════════════════════════════════════════════════════════════════════
def backtest_bb(df: pd.DataFrame) -> list:
    """Bollinger-band fade. Weekend-only, vol filter, SL=3×ATR TP=5×ATR."""
    RISK_PCT = 0.08; SL_M = 3.0; TP_M = 5.0; ADX_TREND = 28
    h = df["high"].values; l = df["low"].values
    c = df["close"].values; v = df["volume"].values
    idx = df.index; n = len(c)

    atr14  = _atr_arr(h, l, c, 14)
    adx14  = _adx_arr(h, l, c, 14)
    upper, _, lower = _bb(c, 20, 2.0)
    vol_ma = _vol_ma(v, 20)

    trades = []; pos = None

    for i in range(50, n):
        # Max-hold 48 bars
        if pos and (i - pos["open_bar"]) >= 48:
            pnl = pos["dir"] * (c[i] - pos["entry"]) / pos["entry"] * pos["risk_usdt"] / (pos["sl_dist"] / pos["entry"])
            trades.append({"pnl": pnl - pos["notional"]*FEE, "year": idx[i].year})
            pos = None

        # SL/TP check
        if pos:
            if pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue
                if h[i] >= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"] * TP_M/SL_M - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue
            else:
                if h[i] >= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue
                if l[i] <= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"] * TP_M/SL_M - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue

        if pos: continue

        # Weekend only (Sat=5, Sun=6)
        dow = idx[i].weekday()
        if dow not in (5, 6): continue

        atr_v = atr14[i]; adx_v = adx14[i]
        if atr_v <= 0 or adx_v >= ADX_TREND: continue
        if vol_ma[i] <= 0 or np.isnan(upper[i]): continue

        # Volume spike (above 20-bar avg)
        if v[i] <= vol_ma[i]: continue

        ep = None; sl = None; tp = None; direction = 0
        if c[i] < lower[i]:    # bullish fade
            direction = 1; ep = c[i]; sl = ep - SL_M*atr_v; tp = ep + TP_M*atr_v
        elif c[i] > upper[i]:  # bearish fade
            direction = -1; ep = c[i]; sl = ep + SL_M*atr_v; tp = ep - TP_M*atr_v

        if direction == 0: continue
        risk_usdt = BAL * RISK_PCT
        sl_dist   = abs(ep - sl)
        notional  = (risk_usdt / sl_dist) * ep
        pos = {"dir": direction, "entry": ep, "sl": sl, "tp": tp,
               "risk_usdt": risk_usdt, "sl_dist": sl_dist,
               "notional": notional, "open_bar": i}

    return trades


# ════════════════════════════════════════════════════════════════════════
#  STRATEGY 2: ORB  (NY open 14:00 UTC, 60min range, RR 2.0)
# ════════════════════════════════════════════════════════════════════════
def backtest_orb(df: pd.DataFrame) -> list:
    """Opening Range Breakout: 14:00 UTC candle defines range, first break = trade."""
    RISK_PCT = 0.05; RR = 2.0; MAX_HOLD = 6
    h = df["high"].values; l = df["low"].values
    c = df["close"].values; idx = df.index; n = len(c)

    trades = []; pos = None
    orb_high = None; orb_low = None; orb_date = None; traded_today = False

    for i in range(1, n):
        ts = idx[i]; bar_date = ts.date()

        # Reset daily state at midnight UTC
        if orb_date != bar_date:
            orb_high = orb_low = orb_date = None
            traded_today = False

        # SL/TP or max-hold
        if pos:
            if (i - pos["open_bar"]) >= MAX_HOLD:
                pnl = pos["dir"] * (c[i] - pos["entry"]) / pos["entry"] * pos["risk_usdt"] / (pos["sl_dist"] / pos["entry"])
                trades.append({"pnl": pnl - pos["notional"]*FEE, "year": idx[i].year})
                pos = None
            elif pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None
                elif h[i] >= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"] * RR - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None
            else:
                if h[i] >= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None
                elif l[i] <= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"] * RR - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None

        # Record 14:00 UTC candle as ORB candle
        if ts.hour == 14:
            orb_high = h[i]; orb_low = l[i]; orb_date = bar_date

        # Entry: first 1h close outside ORB after 15:00 UTC
        if orb_high and ts.hour > 14 and not traded_today and not pos:
            rng = orb_high - orb_low
            if rng <= 0: continue
            if c[i] > orb_high:
                ep = orb_high; sl = orb_low; tp = ep + RR * rng
                risk_usdt = BAL * RISK_PCT; sl_dist = rng
                pos = {"dir": 1, "entry": ep, "sl": sl, "tp": tp,
                       "risk_usdt": risk_usdt, "sl_dist": sl_dist,
                       "notional": (risk_usdt/sl_dist)*ep, "open_bar": i}
                traded_today = True
            elif c[i] < orb_low:
                ep = orb_low; sl = orb_high; tp = ep - RR * rng
                risk_usdt = BAL * RISK_PCT; sl_dist = rng
                pos = {"dir": -1, "entry": ep, "sl": sl, "tp": tp,
                       "risk_usdt": risk_usdt, "sl_dist": sl_dist,
                       "notional": (risk_usdt/sl_dist)*ep, "open_bar": i}
                traded_today = True

    return trades


# ════════════════════════════════════════════════════════════════════════
#  STRATEGY 3: Asia BO  (00-08 UTC range, London open breakout)
# ════════════════════════════════════════════════════════════════════════
def backtest_asia(df: pd.DataFrame) -> list:
    """Asia session (00-07 UTC) range → first break after 08:00 UTC."""
    RISK_PCT = 0.03; RR = 2.0; SL_ATR = 1.0; MAX_HOLD = 6
    h = df["high"].values; l = df["low"].values
    c = df["close"].values; idx = df.index; n = len(c)
    atr14 = _atr_arr(h, l, c, 14)

    trades = []; pos = None
    asia_h = None; asia_l = None; asia_date = None; traded_today = False

    for i in range(1, n):
        ts = idx[i]; bar_date = ts.date()

        if asia_date != bar_date:
            asia_h = -np.inf; asia_l = np.inf; asia_date = bar_date
            traded_today = False

        # SL/TP / max-hold
        if pos:
            atr_v = atr14[i]
            if (i - pos["open_bar"]) >= MAX_HOLD:
                pnl = pos["dir"] * (c[i] - pos["entry"]) / pos["entry"] * pos["risk_usdt"] / (pos["sl_dist"] / pos["entry"])
                trades.append({"pnl": pnl - pos["notional"]*FEE, "year": idx[i].year})
                pos = None
            elif pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None
                elif h[i] >= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"] * RR - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None
            else:
                if h[i] >= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None
                elif l[i] <= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"] * RR - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None

        # Build Asia range: candles 00:00-07:59 UTC
        if ts.hour < 8:
            asia_h = max(asia_h, h[i]); asia_l = min(asia_l, l[i])

        # Entry: first 1h close outside Asia range after 08:00 UTC
        if ts.hour >= 8 and asia_h > asia_l and not traded_today and not pos:
            atr_v = atr14[i]
            if atr_v <= 0: continue
            if c[i] > asia_h:
                ep = asia_h; sl = ep - SL_ATR*atr_v; tp = ep + RR*SL_ATR*atr_v
                risk_usdt = BAL * RISK_PCT; sl_dist = SL_ATR*atr_v
                pos = {"dir": 1, "entry": ep, "sl": sl, "tp": tp,
                       "risk_usdt": risk_usdt, "sl_dist": sl_dist,
                       "notional": (risk_usdt/sl_dist)*ep, "open_bar": i}
                traded_today = True
            elif c[i] < asia_l:
                ep = asia_l; sl = ep + SL_ATR*atr_v; tp = ep - RR*SL_ATR*atr_v
                risk_usdt = BAL * RISK_PCT; sl_dist = SL_ATR*atr_v
                pos = {"dir": -1, "entry": ep, "sl": sl, "tp": tp,
                       "risk_usdt": risk_usdt, "sl_dist": sl_dist,
                       "notional": (risk_usdt/sl_dist)*ep, "open_bar": i}
                traded_today = True

    return trades


# ════════════════════════════════════════════════════════════════════════
#  STRATEGY 4: S/R Breakout  (pivot-based, vol spike, SL=3×ATR TP=5×ATR)
# ════════════════════════════════════════════════════════════════════════
def backtest_sr(df: pd.DataFrame) -> list:
    """S/R level breakout: rolling pivot highs/lows, vol spike, ATR SL/TP."""
    RISK_PCT = 0.08; SL_M = 3.0; TP_M = 5.0; LOOKBACK = 48; TOL = 0.002
    h = df["high"].values; l = df["low"].values
    c = df["close"].values; v = df["volume"].values
    idx = df.index; n = len(c)
    atr14  = _atr_arr(h, l, c, 14)
    vol_ma = _vol_ma(v, 20)

    trades = []; pos = None

    for i in range(LOOKBACK + 20, n):
        atr_v = atr14[i]
        if atr_v <= 0: continue

        # Max-hold 48 bars
        if pos and (i - pos["open_bar"]) >= 48:
            pnl = pos["dir"] * (c[i] - pos["entry"]) / pos["entry"] * pos["risk_usdt"] / (pos["sl_dist"] / pos["entry"])
            trades.append({"pnl": pnl - pos["notional"]*FEE, "year": idx[i].year})
            pos = None

        # SL/TP
        if pos:
            if pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue
                if h[i] >= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"]*TP_M/SL_M - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue
            else:
                if h[i] >= pos["sl"]:
                    trades.append({"pnl": -pos["risk_usdt"] - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue
                if l[i] <= pos["tp"]:
                    trades.append({"pnl": pos["risk_usdt"]*TP_M/SL_M - pos["notional"]*FEE, "year": idx[i].year})
                    pos = None; continue

        if pos: continue
        if vol_ma[i] <= 0: continue

        # Volume spike required
        if v[i] <= vol_ma[i] * 1.5: continue

        # Find pivot highs/lows in lookback window
        win_h = h[i-LOOKBACK:i]; win_l = l[i-LOOKBACK:i]
        # Resistance: local max within lookback
        resist = [win_h[j] for j in range(1, len(win_h)-1)
                  if win_h[j] >= win_h[j-1] and win_h[j] >= win_h[j+1]]
        support = [win_l[j] for j in range(1, len(win_l)-1)
                   if win_l[j] <= win_l[j-1] and win_l[j] <= win_l[j+1]]

        ep = c[i]; direction = 0
        # Bullish breakout: close clearly above a resistance level
        for lvl in resist:
            if ep > lvl * (1 + TOL):
                direction = 1; break
        # Bearish breakout: close clearly below a support level
        if direction == 0:
            for lvl in support:
                if ep < lvl * (1 - TOL):
                    direction = -1; break

        if direction == 0: continue

        sl = ep - direction * SL_M * atr_v
        tp = ep + direction * TP_M * atr_v
        risk_usdt = BAL * RISK_PCT
        sl_dist   = abs(ep - sl)
        notional  = (risk_usdt / sl_dist) * ep
        pos = {"dir": direction, "entry": ep, "sl": sl, "tp": tp,
               "risk_usdt": risk_usdt, "sl_dist": sl_dist,
               "notional": notional, "open_bar": i}

    return trades


# ── Print helper ─────────────────────────────────────────────────────────
STRATEGIES = [
    ("BB Mean-Rev", backtest_bb,  {"BTC TRAIN 23-24": (1.24, 416), "BTC TEST 25-26": (1.18, 210)}),
    ("ORB (14 UTC)", backtest_orb, {"BTC TRAIN":       (1.44, 156), "BTC TEST":       (1.29, 78)}),
    ("Asia BO",      backtest_asia,{"BTC TRAIN":       (2.15, 84),  "BTC TEST":       (1.61, 42)}),
    ("S/R Breakout", backtest_sr,  {"BTC TRAIN 23-24": (1.72, 198), "BTC TEST 25-26": (1.41, 99)}),
]

def print_result(name: str, all_trades: list, btc_ref: dict, coin: str):
    if not all_trades:
        print(f"  {name}: NO TRADES")
        return
    t = pd.DataFrame(all_trades)
    train = t[t["year"].isin(TRAIN)]; test = t[t["year"].isin(TEST)]
    rs_tr = _stats(train.to_dict("records")); rs_te = _stats(test.to_dict("records"))

    def verdict(pf, threshold): return "✅" if pf >= threshold else ("⚠️" if pf >= 1.0 else "❌")

    print(f"\n  [{coin}]  {name}")
    items = list(btc_ref.items())
    print(f"  {'Period':<16} {'PF':>6} {'WR':>7} {'n':>5}    BTC ref")
    print(f"  {'-'*52}")
    bpf_tr = items[0][1][0] if items else 0
    bpf_te = items[1][1][0] if len(items) > 1 else 0
    print(f"  {'TRAIN 2023-24':<16} {rs_tr['pf']:>6.2f} {rs_tr['wr']:>6.1f}% {rs_tr['n']:>5}    PF {bpf_tr:.2f}  {verdict(rs_tr['pf'], 1.10)}")
    print(f"  {'TEST  2025-26':<16} {rs_te['pf']:>6.2f} {rs_te['wr']:>6.1f}% {rs_te['n']:>5}    PF {bpf_te:.2f}  {verdict(rs_te['pf'], 1.05)}")

    if all_trades:
        by_yr = _by_year(all_trades)
        parts = []
        for yr in sorted(by_yr):
            y = by_yr[yr]; tag = "TR" if yr in TRAIN else "TE"
            ok = "✅" if y["pf"] >= 1.05 else ("⚠️" if y["pf"] >= 1.0 else "❌")
            parts.append(f"{yr}[{tag}]:PF{y['pf']:.2f}{ok}")
        print(f"  {' | '.join(parts)}")


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print(f"Strategy Cross-Coin Robustness — {', '.join(c.replace('USDT','') for c in COINS)}  (BTC params, no retuning)")
    print("TRAIN 2023-2024  |  TEST 2025-2026")
    print("=" * 65)

    for coin in COINS:
        print(f"\n{'─'*65}")
        print(f"  Downloading {coin} 1h  {YEARS[0]}-{YEARS[-1]}...")
        try:
            df = load_data(coin, YEARS)
        except RuntimeError as e:
            print(f"  ERROR: {e}"); continue
        print(f"  {len(df):,} bars  ({df.index[0].date()} → {df.index[-1].date()})")

        for name, fn, btc_ref in STRATEGIES:
            trades = fn(df)
            print_result(name, trades, btc_ref, coin)

    print(f"\n{'='*65}")
    print("SUMMARY KEY:")
    print("  ✅ = PF >= 1.10 (train) / 1.05 (test)  — edge transfers, safe to add")
    print("  ⚠️  = PF 1.00-1.10  — marginal, do not add to live bot")
    print("  ❌ = PF < 1.00  — edge does NOT transfer, BTC-specific or noise")
    print("="*65)

if __name__ == "__main__":
    main()
