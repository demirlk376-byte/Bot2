"""
backtest_live.py — Mevcut live sistemin 30 günlük gerçekçi backtesti.

Karşılaştırma:
  OLD: Market entry (eski sistem) — yapısal seviye geçildikten sonra close'a dolar
  NEW: Limit entry (yeni sistem)  — seviyeye dönen fiyata limit emir

Neden sadece Asia BO ve ORB karşılaştırılıyor?
  • FVG/IFVG: Zaten retest (limit) girişi — her iki modelde aynı.
  • S/R Breakout: SL/TP fill fiyatına göre hesaplanır — her iki modelde aynı.
  • Squeeze/MR:   ATR tabanlı — her iki modelde aynı.
  • Asia BO / ORB: SL/TP YAPISAL SEVİYEYE ankrajlı, fill=close → R/R çöküşü.

Kullanım (VPS'te):
    cd /opt/bot2 && venv/bin/python backtest_live.py

Çıktı:
  • Her strateji için: Trade sayısı, Fill oranı, WR, PF, Toplam P&L
  • OLD vs NEW yan yana karşılaştırma tablosu
"""
from __future__ import annotations

import asyncio
import math
import sys
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import numpy as np

# ── Ensure project root is on path ───────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from indicators import atr as atr_fn, find_sr_levels, is_volume_spike, ema as ema_fn
from strategies.asia_bo import AsiaBoStrategy
from strategies.orb import OrbStrategy
from strategies.fvg import FvgStrategy
from strategies.ifvg import IfvgStrategy
from strategies.sr_breakout import SrBreakoutStrategy
from strategies.squeeze import SqueezeStrategy
from strategies.mean_reversion import MeanReversionStrategy
from config import load_config

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
]
DAYS = 30
# Warmup candles (for EMA200, ATR etc.)
WARMUP = 210
# Total candles to fetch
TOTAL_CANDLES = DAYS * 24 + WARMUP

STARTING_BALANCE = 95.0   # Mevcut hesap bakiyesi
LEVERAGE        = 10
FEE_TAKER       = 0.0001  # %0.01 taker
FEE_MAKER       = 0.0     # %0    maker
MAX_HOLD        = 48       # candle (=48h)

# Risk per trade (config defaults)
RISK_ASIA  = 0.03   # %3
RISK_ORB   = 0.05   # %5
RISK_FVG   = 0.02   # %2
RISK_IFVG  = 0.02   # %2
RISK_SR    = 0.02   # %2
RISK_SQ    = 0.02   # %2
RISK_MR    = 0.02   # %2


# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class BtTrade:
    symbol: str
    strategy: str
    direction: int
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float
    entry_idx: int
    exit_idx: int = -1
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_usdt: float = 0.0
    model: str = "old"      # "old" or "new"
    rr_at_fill: float = 0.0


@dataclass
class RunResult:
    strategy: str
    model: str
    symbol: str
    total_signals: int = 0
    total_filled: int = 0
    winners: int = 0
    losers: int = 0
    total_pnl: float = 0.0
    gross_win: float = 0.0
    gross_loss: float = 0.0
    trades: list = field(default_factory=list)

    @property
    def fill_rate(self) -> float:
        return self.total_filled / self.total_signals if self.total_signals else 0.0

    @property
    def win_rate(self) -> float:
        n = self.winners + self.losers
        return self.winners / n if n else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_win / self.gross_loss if self.gross_loss > 0 else float("inf")


# ── Fetch OHLCV (public endpoint, no auth) ────────────────────────────────────
async def fetch_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    import ccxt.async_support as ccxt
    ex = ccxt.mexc({
        "options": {"defaultType": "swap", "defaultSubType": "linear"},
        "enableRateLimit": True,
    })
    try:
        raw = await ex.fetch_ohlcv(symbol, "1h", limit=limit)
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df.index = df.index.tz_convert("UTC")
        df.drop(columns=["ts"], inplace=True)
        return df
    finally:
        await ex.close()


# ── Position sizing ───────────────────────────────────────────────────────────
def size_position(balance: float, entry: float, sl: float,
                  risk_pct: float, fee: float = FEE_TAKER) -> tuple[float, float]:
    """Returns (quantity_base, margin_used). quantity based on risk$."""
    sl_dist_pct = abs(entry - sl) / entry
    if sl_dist_pct <= 0:
        return 0.0, 0.0
    risk_usd = balance * risk_pct
    qty = risk_usd / (entry * sl_dist_pct)
    # Cap: 50% of balance as notional
    max_qty = balance * 0.5 / entry
    qty = min(qty, max_qty)
    qty = math.floor(qty * 1000) / 1000
    margin = qty * entry / LEVERAGE
    return qty, margin


# ── Backtest one strategy/model on one symbol ─────────────────────────────────
def run_strategy(
    df: pd.DataFrame,
    strategy_name: str,
    model: str,          # "old" | "new"
    symbol: str,
    risk_pct: float,
    sl_atr: float = 0.0,
    rr: float = 2.0,
) -> RunResult:
    """
    strategy_name: "asia_bo" | "orb" | "fvg" | "ifvg" | "sr_breakout" | "squeeze" | "mr"
    model:         "old"  → market fill at close
                   "new"  → limit at structural level (retrace check via next candle range)
    """
    res = RunResult(strategy=strategy_name, model=model, symbol=symbol)

    # Instantiate strategy
    if strategy_name == "asia_bo":
        strat = AsiaBoStrategy()
    elif strategy_name == "orb":
        strat = OrbStrategy()
    elif strategy_name == "fvg":
        strat = FvgStrategy()
    elif strategy_name == "ifvg":
        strat = IfvgStrategy()
    elif strategy_name == "sr_breakout":
        strat = SrBreakoutStrategy()
    elif strategy_name == "squeeze":
        strat = SqueezeStrategy()
    elif strategy_name == "mr":
        from config import StrategyConfig
        strat = MeanReversionStrategy(StrategyConfig())
    else:
        return res

    # Open trade tracking
    open_trade: Optional[BtTrade] = None
    balance = STARTING_BALANCE

    n = len(df)
    for i in range(WARMUP, n):
        sub = df.iloc[:i + 1].copy()
        candle = df.iloc[i]

        atr_v = float(atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1])
        if pd.isna(atr_v) or atr_v <= 0:
            continue

        # ── Check open trade ────────────────────────────────────────────────
        if open_trade is not None:
            d = open_trade.direction
            hi, lo = float(candle["high"]), float(candle["low"])
            sl, tp = open_trade.sl_price, open_trade.tp_price
            age = i - open_trade.entry_idx

            exit_px = None; exit_reason = ""
            # Pessimistic: SL before TP if both hit same candle
            if d == 1:
                if lo <= sl:
                    exit_px, exit_reason = sl, "sl_hit"
                elif hi >= tp:
                    exit_px, exit_reason = tp, "tp_hit"
            else:
                if hi >= sl:
                    exit_px, exit_reason = sl, "sl_hit"
                elif lo <= tp:
                    exit_px, exit_reason = tp, "tp_hit"

            if exit_px is None and age >= MAX_HOLD:
                exit_px = float(candle["close"])
                exit_reason = "max_hold"

            if exit_px is not None:
                entry = open_trade.entry_price
                qty   = open_trade.quantity
                fee   = (entry + exit_px) * qty * FEE_TAKER
                pnl   = d * (exit_px - entry) * qty - fee
                balance += pnl
                open_trade.exit_idx    = i
                open_trade.exit_price  = exit_px
                open_trade.exit_reason = exit_reason
                open_trade.pnl_usdt    = pnl
                res.trades.append(open_trade)
                res.total_filled += 1
                if pnl >= 0:
                    res.winners += 1; res.gross_win += pnl
                else:
                    res.losers  += 1; res.gross_loss += abs(pnl)
                res.total_pnl += pnl
                open_trade = None
            continue  # don't enter a new trade on the same candle as exit

        # ── Generate signal ──────────────────────────────────────────────────
        try:
            if strategy_name == "asia_bo":
                sig = strat.analyze(sub, atr_v)
            elif strategy_name == "orb":
                sig = strat.analyze(sub)
            elif strategy_name in ("fvg", "ifvg", "sr_breakout", "squeeze"):
                sig = strat.analyze(sub, atr_v)
            elif strategy_name == "mr":
                sig = strat.analyze(sub)
            else:
                continue
        except Exception:
            continue

        if sig.direction == 0:
            continue

        res.total_signals += 1

        # ── Determine entry, SL, TP ──────────────────────────────────────────
        close_px = float(candle["close"])
        direction = sig.direction
        sl_price = tp_price = entry_px = 0.0

        if strategy_name in ("asia_bo", "orb"):
            # Structural levels from signal
            raw_sl = getattr(sig, "sl_price", 0.0)
            raw_tp = getattr(sig, "tp_price", 0.0)
            if raw_sl <= 0 or raw_tp <= 0:
                res.total_signals -= 1
                continue

            if strategy_name == "asia_bo":
                # Structural anchor: asia_low (short) or asia_high (long)
                level = sig.asia_low if direction == -1 else sig.asia_high
            else:
                level = sig.orb_low if direction == -1 else sig.orb_high

            if model == "old":
                # Market fill: fills at close (already past the level)
                slippage = 1.0005 if direction == 1 else 0.9995
                entry_px = close_px * slippage
                # SL/TP stay at structural levels
                sl_price = raw_sl
                tp_price = raw_tp
            else:
                # NEW: limit at level, fills if NEXT candle range includes level
                if i + 1 >= n:
                    res.total_signals -= 1
                    continue
                next_c = df.iloc[i + 1]
                if direction == -1:  # short: limit SELL at level (above close)
                    filled = float(next_c["high"]) >= level
                else:                # long: limit BUY at level (below close)
                    filled = float(next_c["low"]) <= level
                if not filled:
                    continue  # limit didn't fill → trade skipped
                entry_px = level
                sl_price = raw_sl
                tp_price = raw_tp

        elif strategy_name in ("fvg", "ifvg"):
            # FVG is already a retest (limit) strategy; entry_price = zone level
            raw_entry = getattr(sig, "entry_price", 0.0)
            raw_sl = getattr(sig, "sl_price", 0.0)
            raw_tp = getattr(sig, "tp_price", 0.0)
            if raw_sl <= 0 or raw_tp <= 0 or raw_entry <= 0:
                res.total_signals -= 1
                continue
            entry_px = raw_entry
            sl_price = raw_sl
            tp_price = raw_tp

        elif strategy_name == "sr_breakout":
            # S/R: SL/TP computed from close (fill-anchored) — same for old/new
            raw_sl = getattr(sig, "sl_price", 0.0)
            raw_tp = getattr(sig, "tp_price", 0.0)
            if raw_sl <= 0 or raw_tp <= 0:
                res.total_signals -= 1
                continue
            entry_px = close_px
            sl_price = raw_sl
            tp_price = raw_tp

        elif strategy_name in ("squeeze", "mr"):
            # ATR-based SL/TP from close
            sl_dist = atr_v * (sl_atr if sl_atr > 0 else 2.0)
            tp_dist = sl_dist * rr
            if direction == 1:
                sl_price = close_px - sl_dist
                tp_price = close_px + tp_dist
            else:
                sl_price = close_px + sl_dist
                tp_price = close_px - tp_dist
            entry_px = close_px

        # ── Validate R/R ─────────────────────────────────────────────────────
        if entry_px <= 0 or sl_price <= 0 or tp_price <= 0:
            res.total_signals -= 1
            continue

        if direction == 1:
            if not (sl_price < entry_px < tp_price):
                res.total_signals -= 1; continue
        else:
            if not (tp_price < entry_px < sl_price):
                res.total_signals -= 1; continue

        sl_dist_v = abs(entry_px - sl_price)
        tp_dist_v = abs(tp_price - entry_px)
        rr_actual = tp_dist_v / sl_dist_v if sl_dist_v > 0 else 0.0
        if rr_actual < 1.0:
            res.total_signals -= 1
            continue

        # ── Size position ─────────────────────────────────────────────────────
        qty, margin = size_position(balance, entry_px, sl_price, risk_pct)
        if qty <= 0 or margin > balance * 0.95:
            continue

        fee_entry = entry_px * qty * FEE_TAKER
        balance -= margin + fee_entry

        open_trade = BtTrade(
            symbol=symbol,
            strategy=strategy_name,
            direction=direction,
            entry_price=entry_px,
            sl_price=sl_price,
            tp_price=tp_price,
            quantity=qty,
            entry_idx=i,
            model=model,
            rr_at_fill=rr_actual,
        )

    # Force-close any open trade at last bar
    if open_trade is not None:
        last = df.iloc[-1]
        d = open_trade.direction
        exit_px = float(last["close"])
        fee = (open_trade.entry_price + exit_px) * open_trade.quantity * FEE_TAKER
        pnl = d * (exit_px - open_trade.entry_price) * open_trade.quantity - fee
        balance += pnl
        open_trade.exit_idx = n - 1
        open_trade.exit_price = exit_px
        open_trade.exit_reason = "end_of_data"
        open_trade.pnl_usdt = pnl
        res.trades.append(open_trade)
        res.total_filled += 1
        if pnl >= 0:
            res.winners += 1; res.gross_win += pnl
        else:
            res.losers  += 1; res.gross_loss += abs(pnl)
        res.total_pnl += pnl

    return res


# ── Print comparison table ────────────────────────────────────────────────────
def print_table(all_results: dict, symbols: list[str]) -> None:
    sep = "─" * 108

    print("\n" + "═" * 108)
    print("  MEVCUT SİSTEM 30 GÜNLÜK BACKTEST  —  Başlangıç bakiyesi: ${:.2f}".format(STARTING_BALANCE))
    print("═" * 108)

    strat_names = {
        "asia_bo":    "Asia BO",
        "orb":        "ORB",
        "fvg":        "FVG",
        "sr_breakout":"S/R BO",
        "squeeze":    "Squeeze",
        "mr":         "BB/MR",
    }

    # Aggregate by strategy + model across all symbols
    agg: dict[tuple, dict] = {}
    for sym in symbols:
        for strat in strat_names:
            for model in ("old", "new"):
                key = (strat, model)
                r = all_results.get((sym, strat, model))
                if r is None:
                    continue
                if key not in agg:
                    agg[key] = dict(signals=0, filled=0, winners=0, losers=0,
                                    gross_win=0.0, gross_loss=0.0, total_pnl=0.0,
                                    rr_vals=[])
                a = agg[key]
                a["signals"]    += r.total_signals
                a["filled"]     += r.total_filled
                a["winners"]    += r.winners
                a["losers"]     += r.losers
                a["gross_win"]  += r.gross_win
                a["gross_loss"] += r.gross_loss
                a["total_pnl"]  += r.total_pnl
                for t in r.trades:
                    a["rr_vals"].append(t.rr_at_fill)

    def pf(a):
        return a["gross_win"] / a["gross_loss"] if a["gross_loss"] > 0 else float("inf")
    def wr(a):
        n = a["winners"] + a["losers"]
        return a["winners"] / n if n else 0.0
    def fill_r(a):
        return a["filled"] / a["signals"] if a["signals"] else 0.0
    def avg_rr(a):
        return sum(a["rr_vals"]) / len(a["rr_vals"]) if a["rr_vals"] else 0.0

    # Table header
    print(f"\n{'Strateji':<12} {'Model':<6} {'Sinyal':>7} {'Dolan':>7} {'Fill%':>6} "
          f"{'WR%':>6} {'PF':>6} {'Avg R/R':>8} {'P&L($)':>10}")
    print(sep)

    strats_to_show = ["asia_bo", "orb", "fvg", "sr_breakout", "squeeze", "mr"]
    # Which strategies differ between old/new
    differs = {"asia_bo", "orb"}

    for strat in strats_to_show:
        label = strat_names[strat]
        for model in ("old", "new"):
            # For strategies that are identical between old/new, print only once
            if strat not in differs and model == "new":
                continue

            key = (strat, model)
            if key not in agg:
                continue
            a = agg[key]
            n_filled = a["filled"]
            pf_val = pf(a)
            pf_str = f"{pf_val:.2f}" if pf_val != float("inf") else "  ∞"
            fill_pct = fill_r(a) * 100
            wr_pct   = wr(a) * 100
            rr_avg   = avg_rr(a)
            pnl      = a["total_pnl"]

            model_label = "" if strat not in differs else f"({model})"
            row_label   = f"{label} {model_label}".strip()
            marker = "✅" if pf_val >= 1.5 else ("⚠️ " if pf_val >= 1.0 else "❌")
            print(f"{row_label:<18} {a['signals']:>7} {n_filled:>7} {fill_pct:>5.0f}% "
                  f"{wr_pct:>5.0f}% {pf_str:>6} {rr_avg:>8.2f} {pnl:>+10.2f}  {marker}")

        if strat in differs:
            print(sep)

    # Per-symbol detail
    print(f"\n{'─'*108}")
    print("  PER COIN DETAYI (Asia BO + ORB — 2 modelin karşılaştırması)")
    print(f"{'─'*108}")
    print(f"{'Coin':<8} {'Asia OLD':>10} {'Asia NEW':>10}   {'ORB OLD':>10} {'ORB NEW':>10}")
    print(f"{'':8} {'P&L($)':>10} {'P&L($)':>10}   {'P&L($)':>10} {'P&L($)':>10}")
    print("─" * 64)
    for sym in symbols:
        coin = sym.split("/")[0]
        a_old = all_results.get((sym, "asia_bo", "old"))
        a_new = all_results.get((sym, "asia_bo", "new"))
        o_old = all_results.get((sym, "orb",     "old"))
        o_new = all_results.get((sym, "orb",     "new"))
        def pnl_str(r): return f"{r.total_pnl:+.2f}" if r else "  n/a"
        print(f"{coin:<8} {pnl_str(a_old):>10} {pnl_str(a_new):>10}   "
              f"{pnl_str(o_old):>10} {pnl_str(o_new):>10}")

    # Summary
    print(f"\n{'═'*108}")
    all_old_pnl = sum(
        all_results[(sym, s, "old")].total_pnl
        for sym in symbols for s in strat_names
        if (sym, s, "old") in all_results
    )
    all_new_pnl = sum(
        all_results[(sym, s, "new")].total_pnl
        for sym in symbols for s in strat_names
        if (sym, s, "new") in all_results
    )
    print(f"  30 GÜN TOPLAM P&L  |  ESKİ SİSTEM: {all_old_pnl:+.2f}$  |  "
          f"YENİ SİSTEM: {all_new_pnl:+.2f}$  |  FARK: {all_new_pnl-all_old_pnl:+.2f}$")
    print(f"  (FVG/S/R/Squeeze/MR modeller arası aynı olduğundan toplama 1 kez eklendi)")
    print("═" * 108 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────────
async def main() -> None:
    print(f"\nVeri çekiliyor: {len(SYMBOLS)} coin × {TOTAL_CANDLES} mum (1h) ...")

    # Fetch all data
    dfs: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        coin = sym.split("/")[0]
        print(f"  {coin}... ", end="", flush=True)
        try:
            df = await fetch_ohlcv(sym, TOTAL_CANDLES)
            dfs[sym] = df
            print(f"OK ({len(df)} mum, {df.index[0].date()} – {df.index[-1].date()})")
        except Exception as e:
            print(f"HATA: {e}")

    all_results: dict = {}

    strat_configs = [
        # (name,        risk_pct,  sl_atr, rr,   run_old, run_new)
        ("asia_bo",     RISK_ASIA, 1.0,    2.0,  True,  True),
        ("orb",         RISK_ORB,  1.0,    2.0,  True,  True),
        ("fvg",         RISK_FVG,  0.0,    2.5,  True,  False),  # old==new
        ("sr_breakout", RISK_SR,   3.0,    3.0,  True,  False),  # old==new
        ("squeeze",     RISK_SQ,   2.0,    2.5,  True,  False),  # old==new
        ("mr",          RISK_MR,   1.5,    2.0,  True,  False),  # old==new
    ]

    for sym in SYMBOLS:
        df = dfs.get(sym)
        if df is None:
            continue
        coin = sym.split("/")[0]
        print(f"\n  [{coin}] strateji koşturuluyor ...")

        for name, risk, sl_a, rr_v, do_old, do_new in strat_configs:
            for model in ("old", "new"):
                if model == "old" and not do_old:
                    continue
                if model == "new" and not do_new:
                    # For strategies where old==new, store old result as "new" too
                    all_results[(sym, name, "new")] = all_results.get((sym, name, "old"))
                    continue
                try:
                    r = run_strategy(df, name, model, sym, risk, sl_atr=sl_a, rr=rr_v)
                    all_results[(sym, name, model)] = r
                    print(f"    {name:14} {model}: {r.total_signals:3} sinyal, "
                          f"{r.total_filled:3} trade, pnl={r.total_pnl:+.2f}$")
                except Exception as e:
                    print(f"    {name} {model}: HATA — {e}")
                    import traceback; traceback.print_exc()

    print_table(all_results, SYMBOLS)


if __name__ == "__main__":
    asyncio.run(main())
