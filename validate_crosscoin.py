"""
validate_crosscoin.py — does each strategy sleeve's edge TRANSFER to each coin?

Evidence engine for widening the per-coin allowlists (IFVG/Donchian/Squeeze are
currently BTC-only; FVG/ORB run all coins). For every (sleeve, coin) it runs the
sleeve STANDALONE (no portfolio competition — we want the raw edge) on real data
with the same realistic fill model the bot uses, and reports PF / WR / return with
an honest TRAIN/TEST split and yearly breakdown. A sleeve "PASSES" on a coin only
if it is robustly positive in BOTH train and test — exactly the bar that kept BB
and S/R off the coins where they did not transfer.

Data: local 1m CSVs if present (BTCUSDT-1m-*.csv, or data/<SYM>-1m-*.csv), else
1h klines from data.binance.vision (works on the VPS; may be blocked elsewhere).

Run on the VPS:
    venv/bin/python validate_crosscoin.py                       # all coins, all sleeves
    venv/bin/python validate_crosscoin.py BTCUSDT ETHUSDT       # subset of coins
"""
from __future__ import annotations

import glob
import io
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")
from indicators import atr as atr_fn, ema as ema_fn
from strategies.mean_reversion import MeanReversionStrategy
from strategies.squeeze import SqueezeStrategy
from strategies.sr_breakout import SrBreakoutStrategy
from strategies.fvg import FvgStrategy
from strategies.ifvg import IfvgStrategy
from strategies.donchian import DonchianStrategy
from config import load_config

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
YEARS = [2023, 2024, 2025, 2026]
SPLIT = pd.Timestamp("2026-01-01", tz="UTC")
REF_BAL = 10000.0
COST = {"mkt": 0.0004, "stop": 0.0004, "lim": 0.0002}
SLIP = {"mkt": 0.0003, "stop": 0.0005, "lim": 0.0}
PASS_TRAIN, PASS_TEST, PASS_N = 1.20, 1.10, 30


def _to_1h(sym: str) -> pd.DataFrame | None:
    """Local 1m CSV (resampled) if available, else binance.vision 1h download."""
    files = sorted(glob.glob(f"{sym}-1m-*.csv")) or sorted(glob.glob(f"data/{sym}-1m-*.csv"))
    if files:
        fr = []
        for f in files:
            d = pd.read_csv(f, header=None).iloc[:, :6]
            d.columns = ["ts", "open", "high", "low", "close", "volume"]
            d = d[pd.to_numeric(d["ts"], errors="coerce").notna()]
            fr.append(d.astype(float))
        df = pd.concat(fr, ignore_index=True).drop_duplicates("ts").sort_values("ts")
        unit = "us" if df["ts"].iloc[0] > 1e15 else "ms"
        df.index = pd.to_datetime(df["ts"], unit=unit, utc=True)
        df = df.drop(columns=["ts"])
        return df.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                                      "close": "last", "volume": "sum"}).dropna()
    # remote 1h
    import requests
    base = "https://data.binance.vision/data/spot/monthly/klines"
    fr = []
    for y in YEARS:
        for m in range(1, 13):
            url = f"{base}/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip"
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200:
                    continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z, z.open(z.namelist()[0]) as fh:
                    d = pd.read_csv(fh, header=None,
                                    names=["ts", "open", "high", "low", "close", "volume",
                                           "ct", "qv", "n", "a", "b", "c"])
                d = d[pd.to_numeric(d["ts"], errors="coerce").notna()]
                d["ts"] = pd.to_numeric(d["ts"])
                unit = "us" if d["ts"].iloc[0] > 1e15 else "ms"
                d.index = pd.to_datetime(d["ts"], unit=unit, utc=True)
                fr.append(d[["open", "high", "low", "close", "volume"]].astype(float))
            except Exception:
                continue
    return pd.concat(fr).sort_index() if fr else None


def _bt(df, direction, sl, tp, max_hold, entry, exec_kind, risk):
    """Standalone fill sim: SL/TP from next bar, adverse entry slippage, realistic
    cost, non-compounding sizing off REF_BAL with cap_fraction=1.0."""
    n = len(df); H = df["high"].values; L = df["low"].values; C = df["close"].values
    idx = df.index; trades = []; open_t = None
    cps = COST[exec_kind]; slp = SLIP[exec_kind]
    for i in range(n):
        if open_t is not None:
            if i > open_t["i"]:
                d = open_t["dir"]; e = open_t["e"]; s = open_t["sl"]; t = open_t["tp"]
                held = i - open_t["i"]; xp = None
                if d == 1:
                    if L[i] <= s: xp = s
                    elif H[i] >= t: xp = t
                else:
                    if H[i] >= s: xp = s
                    elif L[i] <= t: xp = t
                if xp is None and held >= max_hold: xp = C[i]
                if xp is not None:
                    qty = open_t["notional"] / e
                    pnl = d * (xp - e) * qty - (e + xp) * qty * cps
                    trades.append({"ts": open_t["ts"], "pnl": pnl})
                    open_t = None
            if open_t is not None:
                continue
        if direction[i] != 0:
            d = int(direction[i]); e = (entry[i] if entry is not None else C[i])
            s = sl[i]; t = tp[i]
            if e <= 0 or s <= 0 or t <= 0: continue
            e *= (1 + d * slp)
            if d == 1 and not (s < e < t): continue
            if d == -1 and not (t < e < s): continue
            sld = abs(e - s) / e
            if sld <= 0: continue
            notional = min(risk / sld, 1.0) * REF_BAL
            open_t = {"i": i, "ts": idx[i], "dir": d, "e": e, "sl": s, "tp": t, "notional": notional}
    return trades


def _stats(tr):
    if not tr:
        return None
    p = np.array([t["pnl"] for t in tr])
    def pf(a):
        g = a[a > 0].sum(); l = -a[a < 0].sum()
        return g / l if l > 0 else (9.99 if g > 0 else 0.0)
    trn = np.array([t["pnl"] for t in tr if t["ts"] < SPLIT])
    tst = np.array([t["pnl"] for t in tr if t["ts"] >= SPLIT])
    yr = {}
    for t in tr:
        yr.setdefault(t["ts"].year, []).append(t["pnl"])
    ys = " ".join(f"{y}:{pf(np.array(v)):.2f}" for y, v in sorted(yr.items()))
    return {"n": len(p), "pf": pf(p), "wr": (p > 0).mean(), "ret": p.sum() / REF_BAL * 100,
            "tr_pf": pf(trn) if len(trn) else 0.0, "te_pf": pf(tst) if len(tst) else 0.0,
            "tr_n": len(trn), "te_n": len(tst), "yearly": ys}


# ── per-sleeve standalone signal generators (current params) ────────────────
def gen(df, sleeve, cfg):
    n = len(df); H = df["high"].values; L = df["low"].values; C = df["close"].values
    idx = df.index; a1 = atr_fn(df["high"], df["low"], df["close"], 14).values
    dirn = np.zeros(n, int); sl = np.zeros(n); tp = np.zeros(n); ent = np.zeros(n)
    if sleeve == "orb":
        hour = idx.hour.values; dts = idx.normalize().values
        ohi = {}; olo = {}; traded = set()
        for i in range(n):
            if hour[i] == 14: ohi[dts[i]] = H[i]; olo[dts[i]] = L[i]
        for i in range(n):
            d = dts[i]
            if hour[i] <= 14 or d in traded or d not in ohi: continue
            oh, ol = ohi[d], olo[d]; rng = oh - ol
            if rng <= 0: continue
            if C[i] > oh: dirn[i] = 1; ent[i] = oh; sl[i] = ol; tp[i] = oh + 2 * rng; traded.add(d)
            elif C[i] < ol: dirn[i] = -1; ent[i] = ol; sl[i] = oh; tp[i] = ol - 2 * rng; traded.add(d)
        return dirn, sl, tp, ent, 6, "stop", getattr(cfg.risk, "orb_risk_pct", 0.05)
    # class-driven sleeves
    strat = {"bb": MeanReversionStrategy(cfg.strategy), "sr": SrBreakoutStrategy(),
             "fvg": FvgStrategy(), "ifvg": IfvgStrategy(min_gap_atr=0.75, rr=2.0),
             "squeeze": SqueezeStrategy()}[sleeve]
    WIN = 260
    for i in range(n):
        av = a1[i]
        if np.isnan(av) or av <= 0: continue
        w = df.iloc[max(0, i - WIN + 1):i + 1]
        if sleeve == "bb":
            s = strat.analyze(w)
            if s.direction != 0:
                e = C[i]; sld = cfg.risk.atr_sl_multiplier * av
                dirn[i] = s.direction; ent[i] = e
                sl[i] = e - s.direction * sld; tp[i] = e + s.direction * cfg.risk.rr_ratio * sld
        else:
            s = strat.analyze(w, av)
            if s.direction != 0 and s.sl_price > 0 and s.tp_price > 0:
                dirn[i] = s.direction; sl[i] = s.sl_price; tp[i] = s.tp_price
                ent[i] = getattr(s, "entry_price", 0.0) or C[i]
    mh = {"bb": 48, "sr": 48, "fvg": 24, "ifvg": 24, "squeeze": 48}[sleeve]
    ek = {"bb": "mkt", "sr": "mkt", "fvg": "lim", "ifvg": "lim", "squeeze": "mkt"}[sleeve]
    rk = {"bb": cfg.risk.max_risk_per_trade, "sr": cfg.risk.max_risk_per_trade,
          "fvg": getattr(cfg.risk, "fvg_risk_pct", 0.02),
          "ifvg": getattr(cfg.risk, "ifvg_risk_pct", 0.02),
          "squeeze": getattr(cfg.risk, "squeeze_risk_pct", 0.02)}[sleeve]
    return dirn, sl, tp, ent, mh, ek, rk


def gen_donchian(df, cfg):
    df4 = df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()
    a4 = atr_fn(df4["high"], df4["low"], df4["close"], 14).values
    don = DonchianStrategy(channel=cfg.strategy.donchian_channel, rr=cfg.strategy.donchian_rr,
                           sl_atr=cfg.strategy.donchian_sl_atr, ema_trend=cfg.strategy.donchian_ema_trend)
    n4 = len(df4); dirn = np.zeros(n4, int); sl = np.zeros(n4); tp = np.zeros(n4); ent = np.zeros(n4)
    for j in range(n4):
        av = a4[j]
        if np.isnan(av) or av <= 0: continue
        w = df4.iloc[max(0, j - 260 + 1):j + 1]
        s = don.analyze(w, float(av))
        if s.direction != 0:
            dirn[j] = s.direction; sl[j] = s.sl_price; tp[j] = s.tp_price; ent[j] = s.entry_price
    return df4, dirn, sl, tp, ent, 30, "mkt", getattr(cfg.risk, "donchian_risk_pct", 0.02)


def main():
    coins = [c.upper() for c in sys.argv[1:]] or COINS
    cfg = load_config()
    sleeves = ["orb", "fvg", "ifvg", "donchian", "squeeze", "bb", "sr"]
    results = {}  # (sleeve, coin) -> stats
    for coin in coins:
        print(f"\n# loading {coin} ...", flush=True)
        df = _to_1h(coin)
        if df is None or len(df) < 400:
            print(f"  no data for {coin} — skipped")
            continue
        print(f"  {len(df)} 1h bars {df.index[0].date()}..{df.index[-1].date()}")
        for sv in sleeves:
            try:
                if sv == "donchian":
                    d4, dn, sl, tp, ent, mh, ek, rk = gen_donchian(df, cfg)
                    tr = _bt(d4, dn, sl, tp, mh, ent, ek, rk)
                else:
                    dn, sl, tp, ent, mh, ek, rk = gen(df, sv, cfg)
                    tr = _bt(df, dn, sl, tp, mh, ent, ek, rk)
                results[(sv, coin)] = _stats(tr)
            except Exception as e:
                print(f"  {sv} {coin} error: {e}")
                results[(sv, coin)] = None

    # ── matrix ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  CROSS-COIN PF MATRIX  (PASS = train>%.2f & test>%.2f & n>=%d, both sides)"
          % (PASS_TRAIN, PASS_TEST, PASS_N))
    print("=" * 78)
    hdr = "  sleeve     " + "".join(f"{c.replace('USDT',''):>10}" for c in coins)
    print(hdr)
    for sv in sleeves:
        row = f"  {sv:<10}"
        for coin in coins:
            s = results.get((sv, coin))
            if not s:
                row += f"{'—':>10}"; continue
            passed = s["tr_pf"] >= PASS_TRAIN and s["te_pf"] >= PASS_TEST and s["n"] >= PASS_N
            row += f"{('%.2f%s' % (s['pf'], '✓' if passed else ' ')):>10}"
        print(row)
    print("\n  (cell = overall PF; ✓ = passes train+test bar → safe to widen allowlist to that coin)")

    # ── detail + recommendation ───────────────────────────────────────────────
    print("\n  PER-SLEEVE DETAIL")
    for sv in sleeves:
        print(f"\n  [{sv}]")
        for coin in coins:
            s = results.get((sv, coin))
            if not s:
                continue
            ok = "PASS" if (s["tr_pf"] >= PASS_TRAIN and s["te_pf"] >= PASS_TEST and s["n"] >= PASS_N) else "no"
            print(f"    {coin:<9} n{s['n']:>4} PF{s['pf']:>5.2f} WR{s['wr']:>4.0%} "
                  f"ret{s['ret']:>+6.0f}%  TR{s['tr_pf']:.2f}/TE{s['te_pf']:.2f}  [{ok}]  yr {s['yearly']}")


if __name__ == "__main__":
    main()
