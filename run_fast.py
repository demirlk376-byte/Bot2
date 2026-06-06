"""Run the fast vectorized backtester across all months with train/test split."""
from __future__ import annotations

import glob
import sys
import time

import pandas as pd

sys.path.insert(0, "/home/user/Bot2")

from config import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig, TelegramConfig
from fast_backtest import FastBacktester, FastResult


def load_all() -> pd.DataFrame:
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = ["ts", "open", "high", "low", "close", "volume",
                      "ct", "qv", "count", "tbv", "tbqv", "ign"]
        df = df[["ts", "open", "high", "low", "close", "volume"]].astype(
            {"open": float, "high": float, "low": float, "close": float, "volume": float})
        frames.append(df)
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
        risk=RiskConfig(max_risk_per_trade=0.02, atr_sl_multiplier=1.5,
                        rr_ratio=2.0, max_positions=1, daily_max_loss=0.05),
        strategy=StrategyConfig(primary_tf="5m", confirm_tf="15m"),
        telegram=TelegramConfig(token="", chat_id="", enabled=False),
        db_path="./test.db", log_level="ERROR", paper_initial_balance=10000.0,
    )


def report(name: str, r: FastResult):
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    print(f"İşlem: {r.total_trades} | WR: {r.win_rate:.1%} | PF: {r.profit_factor:.2f}")
    print(f"PnL: ${r.total_pnl_usdt:+.2f} ({r.total_pnl_pct:+.1%}) | "
          f"MaxDD: {r.max_drawdown:.1%} | Sharpe: {r.sharpe:.2f}")


def monthly(r: FastResult):
    months: dict[str, list] = {}
    for t in r.trades:
        m = t.entry_ts.strftime("%Y-%m")
        months.setdefault(m, []).append(t.pnl_usdt)
    print(f"\n{'Ay':9s} {'İşl':>4s} {'WR':>5s} {'PnL':>9s} {'Kümül':>9s}")
    cum = 0
    for m in sorted(months):
        pnls = months[m]
        wins = sum(1 for p in pnls if p > 0)
        cum += sum(pnls)
        print(f"{m:9s} {len(pnls):>4d} {wins/len(pnls):>4.0%} {sum(pnls):>+9.2f} {cum:>+9.2f}")


def strategy_breakdown(r: FastResult):
    strats: dict[str, list] = {}
    exits: dict[str, list] = {}
    for t in r.trades:
        strats.setdefault(t.dominant, []).append(t.pnl_usdt)
        exits.setdefault(t.exit_reason, []).append(t.pnl_usdt)
    print("\n-- Strateji --")
    for s, p in sorted(strats.items(), key=lambda x: sum(x[1]), reverse=True):
        w = sum(1 for x in p if x > 0)
        print(f"  {s:10s}: {len(p):4d} | WR {w/len(p):>4.0%} | ${sum(p):>+8.2f}")
    print("-- Çıkış --")
    for e, p in sorted(exits.items()):
        print(f"  {e:10s}: {len(p):4d} | ${sum(p):>+8.2f}")


def main():
    df_1m = load_all()
    print(f"Veri: {df_1m.index[0]:%Y-%m-%d} → {df_1m.index[-1]:%Y-%m-%d} ({len(df_1m):,} 1m mum)")

    df_5m = resample(df_1m, "5min")
    df_15m = resample(df_1m, "15min")
    df_1h = resample(df_1m, "1h")
    print(f"5m: {len(df_5m):,} | 15m: {len(df_15m):,} | 1h: {len(df_1h):,}")

    cfg = make_config()
    bt = FastBacktester(cfg)

    t0 = time.time()
    r_all = bt.run(df_5m, df_15m, df_1h, 10000.0)
    print(f"\nÇalışma süresi: {time.time()-t0:.1f}s")

    report("TÜM 12 AY", r_all)
    monthly(r_all)
    strategy_breakdown(r_all)


if __name__ == "__main__":
    main()
