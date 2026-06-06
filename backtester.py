from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from config import AppConfig
from indicators import atr, adx, find_sr_levels
from risk import RiskManager
from strategies.trend import TrendStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.signal_combiner import SignalCombiner

logger = logging.getLogger(__name__)

WARMUP_CANDLES = 60  # Skip first N candles for indicator warmup


@dataclass
class BacktestTrade:
    direction: int
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    quantity: float
    entry_idx: int
    exit_idx: int
    pnl_usdt: float
    exit_reason: str
    dominant_strategy: str


@dataclass
class BacktestResult:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl_usdt: float
    total_pnl_pct: float
    max_drawdown: float
    profit_factor: float
    avg_trade_pnl: float
    equity_curve: list[float]
    trade_log: list[BacktestTrade]


class Backtester:
    FEE_RATE = 0.0001
    SLIPPAGE = 0.0005

    def __init__(self, config: AppConfig):
        self._config = config
        self._risk = RiskManager(config.risk)
        self._trend = TrendStrategy(config.strategy)
        self._mr = MeanReversionStrategy(config.strategy)
        self._breakout = BreakoutStrategy(config.strategy)
        self._combiner = SignalCombiner(config.strategy)

    async def load_data(self, exchange, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, since=None, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["timestamp"], unit="ms")
        df.drop(columns=["timestamp"], inplace=True)
        return df

    # Minimum ATR as % of price — don't trade in dead/choppy low-vol markets
    MIN_ATR_PCT = 0.0012  # 0.12% of price

    # Trailing stop: require substantial move before activating (5m BTC noise level ~0.5–1x ATR)
    TRAIL_BREAKEVEN_ATR = 1.5  # move to breakeven only after 1.5x ATR profit
    TRAIL_LOCK_ATR = 2.5       # lock in profit only after 2.5x ATR (past TP midpoint)
    TRAIL_LOCK_BUFFER = 0.4    # lock SL at entry + 0.4 * ATR

    def run(
        self,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        df_1h: Optional[pd.DataFrame] = None,
        initial_balance: float = 10000.0,
    ) -> BacktestResult:
        balance = initial_balance
        equity_curve = [balance]
        trades: list[BacktestTrade] = []
        open_trade: Optional[dict] = None

        n = len(df_5m)
        logger.info("Backtesting %d candles (5m)...", n)

        for i in range(WARMUP_CANDLES, n):
            sub_5m = df_5m.iloc[:i + 1]
            current = sub_5m.iloc[-1]

            # Check open trade SL/TP + update trailing stop
            if open_trade is not None:
                direction = open_trade["direction"]
                entry = open_trade["entry_price"]
                qty = open_trade["quantity"]
                entry_idx = open_trade["entry_idx"]
                dominant = open_trade["dominant"]
                atr_entry = open_trade["atr_at_entry"]

                # Update trailing stop (breakeven and lock-in)
                current_sl = open_trade["trailing_sl"]
                current_tp = open_trade["tp"]
                if direction == 1:
                    favorable = current["high"] - entry
                    if favorable >= atr_entry * self.TRAIL_LOCK_ATR:
                        new_sl = entry + atr_entry * self.TRAIL_LOCK_BUFFER
                        open_trade["trailing_sl"] = max(current_sl, new_sl)
                    elif favorable >= atr_entry * self.TRAIL_BREAKEVEN_ATR:
                        open_trade["trailing_sl"] = max(current_sl, entry)
                else:
                    favorable = entry - current["low"]
                    if favorable >= atr_entry * self.TRAIL_LOCK_ATR:
                        new_sl = entry - atr_entry * self.TRAIL_LOCK_BUFFER
                        open_trade["trailing_sl"] = min(current_sl, new_sl)
                    elif favorable >= atr_entry * self.TRAIL_BREAKEVEN_ATR:
                        open_trade["trailing_sl"] = min(current_sl, entry)

                sl = open_trade["trailing_sl"]
                exit_price = None
                exit_reason = None

                if direction == 1:
                    if current["low"] <= sl:
                        exit_price = sl
                        exit_reason = "sl_hit" if sl < entry else "breakeven_stop"
                    elif current["high"] >= current_tp:
                        exit_price = current_tp
                        exit_reason = "tp_hit"
                else:
                    if current["high"] >= sl:
                        exit_price = sl
                        exit_reason = "sl_hit" if sl > entry else "breakeven_stop"
                    elif current["low"] <= current_tp:
                        exit_price = current_tp
                        exit_reason = "tp_hit"

                if exit_price is not None:
                    raw_pnl = direction * (exit_price - entry) * qty
                    fees = (entry + exit_price) * qty * self.FEE_RATE
                    net_pnl = raw_pnl - fees
                    balance += net_pnl
                    equity_curve.append(balance)
                    trades.append(BacktestTrade(
                        direction=direction,
                        entry_price=entry,
                        exit_price=exit_price,
                        sl_price=open_trade["sl"],
                        tp_price=current_tp,
                        quantity=qty,
                        entry_idx=entry_idx,
                        exit_idx=i,
                        pnl_usdt=net_pnl,
                        exit_reason=exit_reason,
                        dominant_strategy=dominant,
                    ))
                    open_trade = None
                    continue

            # No open trade: check for new signal
            if open_trade is not None:
                continue

            # Need enough 15m candles
            tf_ratio = 3  # 15m / 5m
            j = min(i // tf_ratio, len(df_15m) - 1)
            sub_15m = df_15m.iloc[: j + 1]
            if len(sub_15m) < 30:
                continue

            try:
                atr_val = atr(sub_5m["high"], sub_5m["low"], sub_5m["close"]).iloc[-1]
                adx_val = adx(sub_5m["high"], sub_5m["low"], sub_5m["close"]).iloc[-1]
                sr_levels = find_sr_levels(sub_5m)

                trend_sig = self._trend.analyze(sub_5m, sub_15m)
                mr_sig = self._mr.analyze(sub_5m, sub_15m, sr_levels)
                break_sig = self._breakout.analyze(sub_5m, sub_15m, sr_levels)
            except Exception as e:
                logger.debug("Indicator error at %d: %s", i, e)
                continue

            if pd.isna(atr_val) or pd.isna(adx_val) or atr_val <= 0:
                continue

            # ATR minimum filter: skip dead/choppy markets with negligible volatility
            if atr_val / current["close"] < self.MIN_ATR_PCT:
                continue

            # 1h higher-timeframe bias: use EMA-20 vs EMA-50 cross.
            # This reacts faster than price vs EMA-50, catching trend reversals earlier.
            htf_bias = 0
            if df_1h is not None:
                k = min(i // 12, len(df_1h) - 1)  # 12 5m candles = 1h
                sub_1h = df_1h.iloc[:k + 1]
                if len(sub_1h) >= 50:
                    from indicators import ema as _ema
                    ema_1h_20 = _ema(sub_1h["close"], 20).iloc[-1]
                    ema_1h_50 = _ema(sub_1h["close"], 50).iloc[-1]
                    htf_bias = 1 if ema_1h_20 > ema_1h_50 else -1

            entry_price = current["close"] * (1 + self.SLIPPAGE)
            combined = self._combiner.combine(
                trend_sig, mr_sig, break_sig, entry_price, adx_val, htf_bias=htf_bias
            )

            if combined.direction == 0:
                continue

            # Hard ADX gate: trend and breakout strategies require a trending market.
            # ADX < 20 means the market is ranging — these strategies produce false signals.
            if adx_val < 20 and combined.dominant_strategy in ("trend", "breakout"):
                continue

            # Hard 1h directional gate for trend/breakout: never fight the macro trend.
            # Mean reversion is exempt because counter-trend bounces are its core logic.
            if htf_bias != 0 and combined.dominant_strategy in ("trend", "breakout"):
                if combined.direction != htf_bias:
                    continue

            setup = self._risk.build_trade_setup(
                direction=combined.direction,
                entry_price=entry_price,
                atr=atr_val,
                balance=balance,
                leverage=self._config.exchange.leverage,
                symbol=self._config.exchange.symbol,
            )
            if setup is None:
                continue

            fees_entry = entry_price * setup.quantity * self.FEE_RATE
            balance -= fees_entry

            open_trade = {
                "direction": combined.direction,
                "entry_price": entry_price,
                "sl": setup.sl_price,
                "trailing_sl": setup.sl_price,  # will move as trade becomes profitable
                "tp": setup.tp_price,
                "quantity": setup.quantity,
                "entry_idx": i,
                "dominant": combined.dominant_strategy,
                "atr_at_entry": atr_val,
            }

        # Force close any remaining position at last price
        if open_trade is not None:
            last_price = df_5m.iloc[-1]["close"]
            direction = open_trade["direction"]
            entry = open_trade["entry_price"]
            qty = open_trade["quantity"]
            raw_pnl = direction * (last_price - entry) * qty
            fees = (entry + last_price) * qty * self.FEE_RATE
            net_pnl = raw_pnl - fees
            balance += net_pnl
            equity_curve.append(balance)
            trades.append(BacktestTrade(
                direction=direction,
                entry_price=entry,
                exit_price=last_price,
                sl_price=open_trade["sl"],
                tp_price=open_trade["tp"],
                quantity=qty,
                entry_idx=open_trade["entry_idx"],
                exit_idx=len(df_5m) - 1,
                pnl_usdt=net_pnl,
                exit_reason="end_of_data",
                dominant_strategy=open_trade["dominant"],
            ))

        return self._compute_result(trades, initial_balance, equity_curve)

    def _compute_result(
        self,
        trades: list[BacktestTrade],
        initial_balance: float,
        equity_curve: list[float],
    ) -> BacktestResult:
        if not trades:
            return BacktestResult(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, equity_curve, [])

        pnls = [t.pnl_usdt for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        losses = len(pnls) - wins
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Max drawdown
        peak = initial_balance
        max_dd = 0.0
        running = initial_balance
        for t in trades:
            running += t.pnl_usdt
            if running > peak:
                peak = running
            dd = (peak - running) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        total_pnl = sum(pnls)

        return BacktestResult(
            total_trades=len(trades),
            winning_trades=wins,
            losing_trades=losses,
            win_rate=wins / len(trades),
            total_pnl_usdt=total_pnl,
            total_pnl_pct=total_pnl / initial_balance,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            avg_trade_pnl=total_pnl / len(trades),
            equity_curve=equity_curve,
            trade_log=trades,
        )

    def print_report(self, result: BacktestResult) -> None:
        print("\n" + "=" * 50)
        print("BACKTEST REPORT")
        print("=" * 50)
        print(f"Total Trades:    {result.total_trades}")
        print(f"Win Rate:        {result.win_rate:.1%}")
        print(f"Profit Factor:   {result.profit_factor:.2f}")
        print(f"Total PnL:       ${result.total_pnl_usdt:+.2f} ({result.total_pnl_pct:+.1%})")
        print(f"Avg Trade PnL:   ${result.avg_trade_pnl:+.2f}")
        print(f"Max Drawdown:    {result.max_drawdown:.1%}")
        print("=" * 50)
