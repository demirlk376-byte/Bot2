"""
Production-faithful backtest: uses the ACTUAL production strategy and risk
modules (MeanReversionStrategy, RiskManager) on 1h data, with max-hold exit.

This confirms the shipped engine reproduces the validated research edge.
Run: python production_backtest.py
"""
from __future__ import annotations

import glob
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/Bot2")

from config import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig, TelegramConfig
from indicators import bollinger_bands, rsi, atr
from strategies.mean_reversion import MeanReversionStrategy
from risk import RiskManager


@dataclass
class Trade:
    ts: pd.Timestamp
    direction: int
    entry: float
    exit: float
    qty: float
    pnl: float
    reason: str
    hold: int


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


def make_config():
    return AppConfig(
        exchange=ExchangeConfig(api_key="", api_secret="", paper_mode=True,
                                leverage=10, margin_mode="isolated", symbol="BTC/USDT:USDT"),
        risk=RiskConfig(max_risk_per_trade=0.02, atr_sl_multiplier=3.0,
                        rr_ratio=1.667, max_positions=1, daily_max_loss=0.05,
                        max_hold_candles=48),
        strategy=StrategyConfig(primary_tf="1h", confirm_tf="4h"),
        telegram=TelegramConfig(token="", chat_id="", enabled=False),
        db_path="./test.db", log_level="ERROR", paper_initial_balance=10000.0,
    )


# Cost model: applied per side as a fraction of notional traded at that price.
# 0.04% per side → 0.08% round trip (limit/maker entry + market exit + slippage).
COST_PER_SIDE = 0.0004


def run(df_1h, cfg) -> list[Trade]:
    strat = MeanReversionStrategy(cfg.strategy)
    risk = RiskManager(cfg.risk)
    max_hold = cfg.risk.max_hold_candles

    # Precompute ATR once for speed (strategy recomputes BB/RSI on small slices)
    atr_series = atr(df_1h["high"], df_1h["low"], df_1h["close"], cfg.strategy.atr_period)

    balance = 10000.0
    trades: list[Trade] = []
    open_t = None
    n = len(df_1h)
    high = df_1h["high"].values
    low = df_1h["low"].values
    close = df_1h["close"].values
    warmup = 60

    for i in range(warmup, n):
        # manage open trade
        if open_t is not None:
            d = open_t["dir"]
            entry = open_t["entry"]
            sl = open_t["sl"]
            tp = open_t["tp"]
            qty = open_t["qty"]
            held = i - open_t["i"]

            exit_p = None
            reason = None
            if d == 1:
                if low[i] <= sl:
                    exit_p, reason = sl, "sl_hit"
                elif high[i] >= tp:
                    exit_p, reason = tp, "tp_hit"
            else:
                if high[i] >= sl:
                    exit_p, reason = sl, "sl_hit"
                elif low[i] <= tp:
                    exit_p, reason = tp, "tp_hit"

            if exit_p is None and held >= max_hold:
                exit_p, reason = close[i], "max_hold"

            if exit_p is not None:
                # apply round-trip cost on notional (entry + exit legs)
                gross = d * (exit_p - entry) * qty
                fees = (entry + exit_p) * qty * COST_PER_SIDE
                net = gross - fees
                balance += net
                trades.append(Trade(open_t["ts"], d, entry, exit_p, qty, net, reason, held))
                open_t = None
            continue

        # look for entry
        a = atr_series.iloc[i]
        if np.isnan(a) or a <= 0:
            continue

        window = df_1h.iloc[: i + 1]
        sig = strat.analyze(window)
        if sig.direction == 0:
            continue

        entry_price = close[i]
        setup = risk.build_trade_setup(
            direction=sig.direction, entry_price=entry_price, atr=a,
            balance=balance, leverage=cfg.exchange.leverage, symbol=cfg.exchange.symbol,
        )
        if setup is None:
            continue

        open_t = {
            "i": i, "ts": df_1h.index[i], "dir": sig.direction,
            "entry": entry_price, "sl": setup.sl_price, "tp": setup.tp_price,
            "qty": setup.quantity,
        }

    return trades


def report(name, trades):
    if not trades:
        print(f"{name}: 0 trades"); return
    pnls = np.array([t.pnl for t in trades])
    wins = (pnls > 0).sum()
    pf = pnls[pnls > 0].sum() / (-pnls[pnls < 0].sum()) if (pnls < 0).any() else float("inf")
    eq = 10000 + np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max()
    print(f"{name}: {len(trades)} trades | WR {wins/len(trades):.0%} | "
          f"PnL ${pnls.sum():+.2f} ({pnls.sum()/100:.1f}%) | PF {pf:.2f} | maxDD {dd*100:.1f}%")


def main():
    df_1m = load_all()
    df_1h = resample(df_1m, "1h")
    cfg = make_config()

    print("=" * 64)
    print("PRODUCTION BACKTEST — gerçek strateji + risk modülleri (1h)")
    print("SL=3xATR TP=5xATR maxHold=48h | $10k başlangıç, %2 risk/işlem")
    print("=" * 64)

    trades = run(df_1h, cfg)
    split = pd.Timestamp("2026-01-01")
    tr = [t for t in trades if t.ts < split]
    te = [t for t in trades if t.ts >= split]

    report("\nTÜM 12 AY ", trades)
    report("TRAIN 25/05-12", tr)
    report("TEST  26/01-04", te)

    # monthly
    print("\nAylık:")
    m: dict = {}
    for t in trades:
        m.setdefault(t.ts.strftime("%Y-%m"), []).append(t.pnl)
    cum = 0
    for k in sorted(m):
        p = np.array(m[k]); cum += p.sum()
        print(f"  {k}: {len(p):>3d}t WR{(p>0).mean():>4.0%} ${p.sum():>+8.2f} (kümül ${cum:>+9.2f})")

    print("\nÇıkış nedenleri:")
    ex: dict = {}
    for t in trades:
        ex.setdefault(t.reason, []).append(t.pnl)
    for k, v in sorted(ex.items()):
        print(f"  {k:10s}: {len(v):>3d} | ${sum(v):>+8.2f}")
    holds = [t.hold for t in trades]
    print(f"\nTutma süresi: medyan {np.median(holds):.0f}h, ort {np.mean(holds):.0f}h, "
          f"<24h {(np.array(holds)<24).mean():.0%}")


if __name__ == "__main__":
    main()
