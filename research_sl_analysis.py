"""
Diagnostic: analyze the 113 SL hits to find what features predict them.
Goal: find non-overfitting filters that reduce false entries.

Features analyzed at each trade entry:
  - ADX (trend strength)
  - RSI momentum (is RSI rising or falling before the signal?)
  - RSI divergence (price extreme vs RSI direction)
  - Consecutive closes near/below the BB band
  - Volatility rank (current ATR vs recent ATR history)
  - Price momentum (sum of returns over last 5 candles)
  - BTC performance in last 24h (macro momentum)
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")

from indicators import bollinger_bands, rsi, atr, adx


def load_all():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts", "open", "high", "low", "close", "volume",
                      "ct", "qv", "count", "tbv", "tbqv", "ign"]
        frames.append(df[["ts", "open", "high", "low", "close", "volume"]].astype(float))
    full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"])


def resample(df, rule):
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def precompute(df_1h):
    close = df_1h["close"]; high = df_1h["high"]; low = df_1h["low"]; vol = df_1h["volume"]
    upper, middle, lower = bollinger_bands(close, 20, 2.0)
    rsi_s  = rsi(close, 14)
    atr_s  = atr(high, low, close, 14)
    adx_s  = adx(high, low, close, 14)
    vol_ma = vol.rolling(20).mean()
    bb_pos = (close - lower) / (upper - lower).replace(0, np.nan)
    atr_rank = atr_s / atr_s.rolling(50).mean()  # ATR relative to recent history
    ret5 = close.pct_change().rolling(5).sum()    # 5-candle return

    return dict(
        close=close.values, high=high.values, low=low.values, volume=vol.values,
        upper=upper.values, lower=lower.values, middle=middle.values,
        bb_pos=bb_pos.values, rsi=rsi_s.values, atr=atr_s.values,
        adx=adx_s.values, vol_ma=vol_ma.values, atr_rank=atr_rank.values,
        ret5=ret5.values, index=df_1h.index,
    )


COST_PER_SIDE = 0.0004; SL_MULT = 3.0; TP_MULT = 5.0; BALANCE = 10_000.0
RISK_PCT = 0.02; MAX_HOLD = 48


def backtest_with_features(pre, vol_filter=True):
    close   = pre["close"]; high = pre["high"]; low = pre["low"]
    volume  = pre["volume"]; bb_pos = pre["bb_pos"]
    rsi_v   = pre["rsi"]; atr_v = pre["atr"]; adx_v = pre["adx"]
    vol_ma  = pre["vol_ma"]; atr_rank = pre["atr_rank"]; ret5 = pre["ret5"]
    n = len(close); warmup = 60

    balance = BALANCE; open_t = None; trades = []

    for i in range(warmup, n):
        if np.isnan(atr_v[i]) or atr_v[i] <= 0:
            continue

        if open_t is not None:
            d = open_t["dir"]; entry = open_t["entry"]
            sl = open_t["sl"]; tp = open_t["tp"]
            qty = open_t["qty"]; held = i - open_t["i"]

            exit_p = None; reason = None
            if d == 1:
                if low[i] <= sl:   exit_p, reason = sl, "sl"
                elif high[i] >= tp: exit_p, reason = tp, "tp"
            else:
                if high[i] >= sl:  exit_p, reason = sl, "sl"
                elif low[i] <= tp: exit_p, reason = tp, "tp"

            if exit_p is None and held >= MAX_HOLD:
                exit_p, reason = close[i], "mh"

            if exit_p is not None:
                gross = d * (exit_p - entry) * qty
                fees  = (entry + exit_p) * qty * COST_PER_SIDE
                net   = gross - fees
                balance += net
                t = dict(open_t)  # copy entry features
                t.update({"exit": exit_p, "pnl": net, "reason": reason, "hold": held})
                trades.append(t)
                open_t = None
            continue

        bpos = bb_pos[i]
        if np.isnan(bpos):
            continue
        long_ok = bpos < 0.0; short_ok = bpos > 1.0
        if not long_ok and not short_ok:
            continue
        direction = 1 if long_ok else -1

        if vol_filter and not np.isnan(vol_ma[i]) and volume[i] < vol_ma[i]:
            continue

        a = atr_v[i]; entry_price = close[i]
        sl_dist = SL_MULT * a; tp_dist = TP_MULT * a
        if direction == 1:
            sl_price = entry_price - sl_dist; tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist; tp_price = entry_price - tp_dist

        sl_dist_pct = sl_dist / entry_price
        qty = round((balance * RISK_PCT) / (entry_price * sl_dist_pct), 3)
        qty = min(qty, balance * 0.5 / entry_price)
        if qty < 0.001:
            continue

        # Capture entry features for diagnostic
        rsi_now   = rsi_v[i] if not np.isnan(rsi_v[i]) else 50.0
        rsi_5ago  = rsi_v[i-5] if i >= 5 and not np.isnan(rsi_v[i-5]) else 50.0
        rsi_3ago  = rsi_v[i-3] if i >= 3 and not np.isnan(rsi_v[i-3]) else 50.0
        adx_now   = adx_v[i] if not np.isnan(adx_v[i]) else 20.0
        atrr      = atr_rank[i] if not np.isnan(atr_rank[i]) else 1.0
        r5        = ret5[i] if not np.isnan(ret5[i]) else 0.0

        # RSI divergence: for long, is RSI rising (recovering) even though price still at extreme?
        rsi_rising = rsi_now > rsi_5ago  # RSI recovering = divergence for long

        open_t = {
            "i": i, "ts": pre["index"][i], "dir": direction,
            "entry": entry_price, "sl": sl_price, "tp": tp_price, "qty": qty,
            "rsi_now": rsi_now, "rsi_5ago": rsi_5ago, "rsi_3ago": rsi_3ago,
            "rsi_rising": rsi_rising,
            "adx": adx_now, "atr_rank": atrr, "ret5": r5, "bb_pos": bpos,
        }

    return trades


def analyze_features(trades, label=""):
    sl_hits = [t for t in trades if t["reason"] == "sl"]
    wins    = [t for t in trades if t["reason"] in ("tp", "mh") and t["pnl"] > 0]

    print(f"\n{'='*70}")
    print(f"  {label}: {len(trades)} trades | SL={len(sl_hits)} | Win={len(wins)}")
    print(f"{'='*70}")

    def stat(name, key, fmt=".1f", fn=None):
        def val(t):
            v = t.get(key, t.get("dir", 0))
            return fn(t) if fn else v
        sl_vals = [val(t) for t in sl_hits]
        win_vals = [val(t) for t in wins]
        print(f"  {name:<35s}  SL_mean={np.mean(sl_vals):{fmt}}  WIN_mean={np.mean(win_vals):{fmt}}  "
              f"  |delta|={abs(np.mean(sl_vals)-np.mean(win_vals)):{fmt}}")

    stat("ADX at entry", "adx")
    stat("RSI at entry (abs)", "rsi_now")
    stat("RSI 5 bars ago", "rsi_5ago")
    stat("RSI change (now-5ago)", None, ".2f",
         fn=lambda t: (t["rsi_now"] - t["rsi_5ago"]) * t["dir"])  # positive = divergence
    stat("ATR rank (vs 50-bar avg)", "atr_rank", ".3f")
    stat("5-bar momentum", None, ".4f",
         fn=lambda t: t["ret5"] * t["dir"])  # positive = with-direction momentum
    stat("|bb_pos| depth", None, ".3f",
         fn=lambda t: abs(t["bb_pos"]))

    # RSI divergence split
    div_sl = sum(1 for t in sl_hits if t["rsi_rising"] == (t["dir"] == 1))
    div_win = sum(1 for t in wins if t["rsi_rising"] == (t["dir"] == 1))
    nodiv_sl = len(sl_hits) - div_sl
    nodiv_win = len(wins) - div_win
    print(f"\n  RSI diverging (rising for long, falling for short):")
    print(f"    With divergence:    {div_sl} SL | {div_win} wins  → WR {div_win/(div_sl+div_win)*100:.0f}%" if div_sl+div_win>0 else "    With divergence: 0")
    print(f"    Without divergence: {nodiv_sl} SL | {nodiv_win} wins → WR {nodiv_win/(nodiv_sl+nodiv_win)*100:.0f}%" if nodiv_sl+nodiv_win>0 else "    Without: 0")

    # ADX buckets
    print(f"\n  Win rate by ADX bucket:")
    for lo, hi in [(0,20),(20,25),(25,30),(30,35),(35,100)]:
        sl_n = sum(1 for t in sl_hits if lo <= t["adx"] < hi)
        wn_n = sum(1 for t in wins  if lo <= t["adx"] < hi)
        tot = sl_n + wn_n
        if tot > 0:
            print(f"    ADX {lo:>3d}-{hi:<3d}: {tot:>3d} trades  WR {wn_n/tot*100:.0f}%  "
                  f"SL={sl_n} Win={wn_n}")

    # 5-bar momentum buckets (for direction-adjusted momentum)
    print(f"\n  Win rate by 5-bar momentum (direction-adjusted, negative = against you):")
    momenta = [(t["ret5"] * t["dir"]) for t in sl_hits + wins]
    pcts = np.percentile(momenta, [0, 33, 67, 100])
    for lo_pct, hi_pct in zip(pcts, pcts[1:]):
        sl_n = sum(1 for t in sl_hits if lo_pct <= t["ret5"]*t["dir"] < hi_pct)
        wn_n = sum(1 for t in wins  if lo_pct <= t["ret5"]*t["dir"] < hi_pct)
        tot = sl_n + wn_n
        if tot > 0:
            print(f"    ret5∈[{lo_pct*100:+.1f}%,{hi_pct*100:+.1f}%): {tot:>3d} trades  "
                  f"WR {wn_n/tot*100:.0f}%  SL={sl_n} Win={wn_n}")


def test_rsi_divergence_filter(pre, vol_filter=True):
    """Test adding RSI divergence as entry filter."""
    close  = pre["close"]; high = pre["high"]; low = pre["low"]
    volume = pre["volume"]; bb_pos = pre["bb_pos"]
    rsi_v  = pre["rsi"]; atr_v = pre["atr"]; vol_ma = pre["vol_ma"]
    n = len(close); warmup = 60

    def _run(rsi_div_required, rsi_lookback=5):
        balance = BALANCE; open_t = None; trades = []

        for i in range(max(warmup, rsi_lookback + 1), n):
            if np.isnan(atr_v[i]) or atr_v[i] <= 0:
                continue

            if open_t is not None:
                d = open_t["dir"]; entry = open_t["entry"]
                sl = open_t["sl"]; tp = open_t["tp"]
                qty = open_t["qty"]; held = i - open_t["i"]

                exit_p = None; reason = None
                if d == 1:
                    if low[i] <= sl:    exit_p, reason = sl, "sl"
                    elif high[i] >= tp: exit_p, reason = tp, "tp"
                else:
                    if high[i] >= sl:   exit_p, reason = sl, "sl"
                    elif low[i] <= tp:  exit_p, reason = tp, "tp"

                if exit_p is None and held >= MAX_HOLD:
                    exit_p, reason = close[i], "mh"

                if exit_p is not None:
                    gross = d * (exit_p - entry) * qty
                    fees  = (entry + exit_p) * qty * COST_PER_SIDE
                    net   = gross - fees
                    balance += net
                    trades.append({"pnl": net, "reason": reason,
                                   "ts": pre["index"][i], "dir": d})
                    open_t = None
                continue

            bpos = bb_pos[i]
            if np.isnan(bpos):
                continue
            long_ok = bpos < 0.0; short_ok = bpos > 1.0
            if not long_ok and not short_ok:
                continue
            direction = 1 if long_ok else -1

            if vol_filter and not np.isnan(vol_ma[i]) and volume[i] < vol_ma[i]:
                continue

            # RSI divergence filter
            if rsi_div_required:
                rsi_now = rsi_v[i]; rsi_prev = rsi_v[i - rsi_lookback]
                if np.isnan(rsi_now) or np.isnan(rsi_prev):
                    pass  # allow if no data
                elif direction == 1 and rsi_now <= rsi_prev:
                    continue  # long needs RSI rising (recovering)
                elif direction == -1 and rsi_now >= rsi_prev:
                    continue  # short needs RSI falling

            a = atr_v[i]; entry_price = close[i]
            sl_dist = SL_MULT * a; tp_dist = TP_MULT * a
            if direction == 1:
                sl_price = entry_price - sl_dist; tp_price = entry_price + tp_dist
            else:
                sl_price = entry_price + sl_dist; tp_price = entry_price - tp_dist

            sl_dist_pct = sl_dist / entry_price
            qty = round((balance * RISK_PCT) / (entry_price * sl_dist_pct), 3)
            qty = min(qty, balance * 0.5 / entry_price)
            if qty < 0.001:
                continue

            open_t = {"i": i, "ts": pre["index"][i], "dir": direction,
                      "entry": entry_price, "sl": sl_price, "tp": tp_price, "qty": qty}

        return trades

    split = pd.Timestamp("2026-01-01")

    print("\n=== RSI DIVERGENCE FILTER TEST ===")
    print("(With volume filter already applied)")
    print(f"{'Variant':<40s}  ALL  |  TRAIN WR PF $  |  TEST WR PF $  | maxDD")

    for label, div_req, lookback in [
        ("No divergence filter (baseline+vol)", False, 5),
        ("RSI diverge lb=3", True, 3),
        ("RSI diverge lb=5", True, 5),
        ("RSI diverge lb=7", True, 7),
        ("RSI diverge lb=10", True, 10),
    ]:
        trades = _run(div_req, lookback)
        tr_t = [t for t in trades if t["ts"] < split]
        te_t = [t for t in trades if t["ts"] >= split]

        def sc(tt):
            if not tt: return dict(n=0,wr=0,pnl=0,pf=0,dd=0)
            p = np.array([t["pnl"] for t in tt])
            pos=p[p>0].sum(); neg=-p[p<0].sum()
            pf = pos/neg if neg>0 else float("inf")
            eq=BALANCE+np.cumsum(p); peak=np.maximum.accumulate(eq)
            return dict(n=len(p),wr=(p>0).mean(),pnl=p.sum(),pf=pf,dd=((peak-eq)/peak).max())

        tr = sc(tr_t); te = sc(te_t)
        tot = tr["pnl"] + te["pnl"]
        print(f"{label:<40s}  {tr['n']+te['n']:>3d}t {tot/100:>+5.1f}%  |  "
              f"TRAIN {tr['n']:>3d}t WR{tr['wr']:>3.0%} PF{tr['pf']:.2f} ${tr['pnl']:>+7.0f}  |  "
              f"TEST  {te['n']:>3d}t WR{te['wr']:>3.0%} PF{te['pf']:.2f} ${te['pnl']:>+7.0f}  |  "
              f"maxDD {max(tr['dd'],te['dd'])*100:.1f}%")


def main():
    df_1m = load_all()
    df_1h = resample(df_1m, "1h")
    pre = precompute(df_1h)

    # Run backtest with features, get trade-level data
    trades = backtest_with_features(pre, vol_filter=True)

    split = pd.Timestamp("2026-01-01")
    analyze_features([t for t in trades if t["ts"] < split],
                     "TRAIN (May-Dec 2025) — feature analysis of SL hits vs wins")
    analyze_features([t for t in trades if t["ts"] >= split],
                     "TEST (Jan-Apr 2026) — feature analysis of SL hits vs wins")
    analyze_features(trades, "ALL 12 MONTHS")

    # Test RSI divergence filter
    test_rsi_divergence_filter(pre, vol_filter=True)


if __name__ == "__main__":
    main()
