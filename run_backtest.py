"""
Run backtest on BTCUSDT-1m-2026-01.csv
Resamples 1m → 5m and 15m, then runs the trading engine.
"""
from __future__ import annotations

import sys
import pandas as pd
import numpy as np
from datetime import datetime

# Add project root to path
sys.path.insert(0, "/home/user/Bot2")

from config import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig, TelegramConfig
from backtester import Backtester, BacktestResult


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.index = pd.to_datetime(df["timestamp"], unit="ms")
    df.drop(columns=["timestamp"], inplace=True)
    return df


def resample(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule = {"5m": "5min", "15m": "15min"}.get(timeframe, timeframe)
    df = df_1m.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return df


def print_monthly_breakdown(result: BacktestResult, df_5m: pd.DataFrame) -> None:
    if not result.trade_log:
        return

    print("\n--- WEEKLY BREAKDOWN ---")
    weeks: dict[str, list] = {}
    for t in result.trade_log:
        # Map candle index to timestamp
        if t.entry_idx < len(df_5m):
            ts = df_5m.index[t.entry_idx]
            week = f"W{ts.isocalendar()[1]:02d} ({ts.strftime('%b %d')})"
        else:
            week = "Unknown"
        weeks.setdefault(week, []).append(t.pnl_usdt)

    for week, pnls in sorted(weeks.items()):
        w = sum(pnls)
        win_c = sum(1 for p in pnls if p > 0)
        print(f"  {week}: {len(pnls):2d} trades | {win_c}/{len(pnls)} wins | PnL: ${w:+.2f}")


def print_strategy_breakdown(result: BacktestResult) -> None:
    strats: dict[str, list] = {}
    for t in result.trade_log:
        strats.setdefault(t.dominant_strategy, []).append(t.pnl_usdt)
    print("\n--- BY DOMINANT STRATEGY ---")
    for s, pnls in sorted(strats.items(), key=lambda x: sum(x[1]), reverse=True):
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {s:20s}: {len(pnls):3d} trades | WR {wins/len(pnls):.0%} | PnL ${sum(pnls):+.2f}")


def print_exit_breakdown(result: BacktestResult) -> None:
    exits: dict[str, list] = {}
    for t in result.trade_log:
        exits.setdefault(t.exit_reason, []).append(t.pnl_usdt)
    print("\n--- BY EXIT REASON ---")
    for r, pnls in sorted(exits.items()):
        print(f"  {r:20s}: {len(pnls):3d} trades | PnL ${sum(pnls):+.2f}")


def main():
    print("=" * 60)
    print("BTC/USDT INTRADAY ENGINE — BACKTEST Ocak 2026")
    print("=" * 60)

    csv_path = "/home/user/Bot2/BTCUSDT-1m-2026-01.csv"
    print(f"\nVeri yükleniyor: {csv_path}")
    df_1m = load_csv(csv_path)

    date_range = f"{df_1m.index[0].strftime('%Y-%m-%d')} → {df_1m.index[-1].strftime('%Y-%m-%d')}"
    print(f"Tarih aralığı: {date_range}")
    print(f"1m mum sayısı: {len(df_1m):,}")

    df_5m = resample(df_1m, "5m")
    df_15m = resample(df_1m, "15m")
    print(f"5m mum sayısı:  {len(df_5m):,}")
    print(f"15m mum sayısı: {len(df_15m):,}")

    price_min = df_1m["low"].min()
    price_max = df_1m["high"].max()
    price_open = df_1m["open"].iloc[0]
    price_close = df_1m["close"].iloc[-1]
    monthly_ret = (price_close - price_open) / price_open
    print(f"\nBTC Ocak 2026:")
    print(f"  Açılış: ${price_open:,.2f}  |  Kapanış: ${price_close:,.2f}  |  Aylık: {monthly_ret:+.2%}")
    print(f"  En yüksek: ${price_max:,.2f}  |  En düşük: ${price_min:,.2f}")

    cfg = AppConfig(
        exchange=ExchangeConfig(
            api_key="", api_secret="",
            paper_mode=True, leverage=10,
            margin_mode="isolated", symbol="BTC/USDT:USDT",
        ),
        risk=RiskConfig(
            max_risk_per_trade=0.02,
            atr_sl_multiplier=1.5,
            rr_ratio=2.0,
            max_positions=1,
            daily_max_loss=0.05,
        ),
        strategy=StrategyConfig(
            primary_tf="5m", confirm_tf="15m",
        ),
        telegram=TelegramConfig(token="", chat_id="", enabled=False),
        db_path="./test.db",
        log_level="WARNING",
        paper_initial_balance=10000.0,
    )

    backtester = Backtester(cfg)

    print("\nBacktest çalışıyor...")
    import time
    t0 = time.time()
    result = backtester.run(df_5m, df_15m, initial_balance=10000.0)
    elapsed = time.time() - t0
    print(f"Tamamlandı ({elapsed:.1f}s)\n")

    backtester.print_report(result)
    print_monthly_breakdown(result, df_5m)
    print_strategy_breakdown(result)
    print_exit_breakdown(result)

    if result.equity_curve:
        print("\n--- EQUITY CURVE (her 10 işlemde bir) ---")
        step = max(1, len(result.equity_curve) // 10)
        for i, eq in enumerate(result.equity_curve[::step]):
            pnl = eq - 10000.0
            bar = "█" * int(abs(pnl) / 20)
            sign = "+" if pnl >= 0 else "-"
            print(f"  {sign}${abs(pnl):6.2f}  {bar}")

    if result.trade_log:
        print("\n--- SON 5 İŞLEM ---")
        for t in result.trade_log[-5:]:
            side = "LONG" if t.direction == 1 else "SHORT"
            print(f"  {side:5s} entry=${t.entry_price:,.2f} exit=${t.exit_price:,.2f} "
                  f"pnl=${t.pnl_usdt:+.2f} ({t.exit_reason})")


if __name__ == "__main__":
    main()
