"""
Multi-month walk-forward backtest across all available data.
Loads all monthly CSVs, concatenates into continuous series, resamples,
and runs the engine month-by-month for per-regime analysis.
"""
from __future__ import annotations

import glob
import sys
import time

import pandas as pd

sys.path.insert(0, "/home/user/Bot2")

from config import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig, TelegramConfig
from backtester import Backtester


def load_all() -> pd.DataFrame:
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts", "open", "high", "low", "close", "volume",
                      "ct", "qv", "count", "tbv", "tbqv", "ign"]
        df = df[["ts", "open", "high", "low", "close", "volume"]].copy()
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]].astype(float)
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    full = full.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    full.index = pd.to_datetime(full["ts"], unit="ms")
    full.drop(columns=["ts"], inplace=True)
    return full


def resample(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df_1m.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


def make_config() -> AppConfig:
    return AppConfig(
        exchange=ExchangeConfig(api_key="", api_secret="", paper_mode=True,
                                leverage=10, margin_mode="isolated", symbol="BTC/USDT:USDT"),
        risk=RiskConfig(max_risk_per_trade=0.02, atr_sl_multiplier=1.5,
                        rr_ratio=2.0, max_positions=1, daily_max_loss=0.05),
        strategy=StrategyConfig(primary_tf="5m", confirm_tf="15m"),
        telegram=TelegramConfig(token="", chat_id="", enabled=False),
        db_path="./test.db", log_level="ERROR", paper_initial_balance=10000.0,
    )


def monthly_breakdown(result, df_5m: pd.DataFrame) -> dict:
    months: dict[str, list] = {}
    for t in result.trade_log:
        if t.entry_idx < len(df_5m):
            ts = df_5m.index[t.entry_idx]
            m = ts.strftime("%Y-%m")
        else:
            m = "?"
        months.setdefault(m, []).append(t.pnl_usdt)
    return months


def main():
    print("=" * 72)
    print("MULTI-MONTH BACKTEST — 12 ay (May 2025 → Apr 2026)")
    print("=" * 72)

    df_1m = load_all()
    print(f"\nToplam 1m mum: {len(df_1m):,}")
    print(f"Tarih: {df_1m.index[0].strftime('%Y-%m-%d')} → {df_1m.index[-1].strftime('%Y-%m-%d')}")

    df_5m = resample(df_1m, "5min")
    df_15m = resample(df_1m, "15min")
    df_1h = resample(df_1m, "1h")
    print(f"5m: {len(df_5m):,} | 15m: {len(df_15m):,} | 1h: {len(df_1h):,}")

    cfg = make_config()
    bt = Backtester(cfg)

    print("\nBacktest çalışıyor (tüm 12 ay)...")
    t0 = time.time()
    result = bt.run(df_5m, df_15m, df_1h=df_1h, initial_balance=10000.0)
    print(f"Tamamlandı ({time.time()-t0:.0f}s)\n")

    bt.print_report(result)

    print("\n--- AYLIK PERFORMANS ---")
    months = monthly_breakdown(result, df_5m)
    cum = 0.0
    print(f'{"Ay":9s} {"İşlem":>6s} {"Galip":>6s} {"WR":>6s} {"PnL":>10s} {"Kümül.":>10s}')
    for m in sorted(months.keys()):
        pnls = months[m]
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / len(pnls) if pnls else 0
        s = sum(pnls)
        cum += s
        print(f"{m:9s} {len(pnls):>6d} {wins:>6d} {wr:>5.0%} {s:>+10.2f} {cum:>+10.2f}")

    print("\n--- STRATEJİ BAZINDA ---")
    strats: dict[str, list] = {}
    for t in result.trade_log:
        strats.setdefault(t.dominant_strategy, []).append(t.pnl_usdt)
    for s, pnls in sorted(strats.items(), key=lambda x: sum(x[1]), reverse=True):
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {s:12s}: {len(pnls):4d} işlem | WR {wins/len(pnls):>4.0%} | PnL ${sum(pnls):>+9.2f}")

    print("\n--- ÇIKIŞ NEDENİ ---")
    exits: dict[str, list] = {}
    for t in result.trade_log:
        exits.setdefault(t.exit_reason, []).append(t.pnl_usdt)
    for r, pnls in sorted(exits.items()):
        print(f"  {r:16s}: {len(pnls):4d} | ${sum(pnls):>+9.2f}")


if __name__ == "__main__":
    main()
