from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, date

from config import load_config
from database import Database, DailyStats
from data import DataManager, Candle
from exchange import PaperExchange, LiveExchange
from execution import ExecutionEngine
from indicators import atr
from monitor import Dashboard
from portfolio import Portfolio
from risk import RiskManager
from strategies.mean_reversion import MeanReversionStrategy
from strategies.signal_combiner import SignalCombiner, CombinedSignal
from telegram_bot import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Global component references (set in main())
data_mgr: DataManager = None
exchange = None
executor: ExecutionEngine = None
portfolio: Portfolio = None
dashboard: Dashboard = None
telegram: TelegramNotifier = None
strategies = {}
combiner: SignalCombiner = None
db: Database = None
config = None


async def on_candle_close(candle: Candle) -> None:
    """Fired on every closed primary-timeframe (1h) candle.

    Implements the empirically validated edge: fade Bollinger-band extremes
    on the 1h timeframe (see strategies/mean_reversion.py and the research
    scripts research_*.py / production_backtest.py for validation).
    """
    try:
        import pandas as pd

        df = await data_mgr.get_candles(config.strategy.primary_tf, 120)
        if len(df) < config.strategy.bb_period + 5:
            return

        current_price = await data_mgr.get_current_price()
        portfolio.update_unrealized_pnl(current_price)
        dashboard.update_price(current_price)

        # Paper SL/TP fills first (uses the just-closed candle's range)
        if config.exchange.paper_mode and isinstance(exchange, PaperExchange):
            await exchange.check_sl_tp(candle.high, candle.low)

        # Force-close positions held beyond max_hold_candles
        await _enforce_max_hold(current_price)

        atr_val = atr(df["high"], df["low"], df["close"],
                      config.strategy.atr_period).iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return

        # Primary (and only) signal: Bollinger mean reversion
        mr_sig = strategies["mean_rev"].analyze(df)

        combined = CombinedSignal(
            direction=mr_sig.direction,
            confidence=mr_sig.strength,
            trend_score=0.0,
            mean_rev_score=mr_sig.direction * mr_sig.strength,
            breakout_score=0.0,
            dominant_strategy="mean_rev",
            reasons=[mr_sig.reason],
            entry_price=current_price,
        )
        dashboard.update_signal(combined)
        dashboard.log_message(
            f"Signal: dir={combined.direction} conf={combined.confidence:.2f} "
            f"({mr_sig.reason})"
        )

        if combined.direction != 0 and portfolio.get_open_position_count() == 0:
            result = await executor.execute_signal(combined, atr_val)
            if result.success and result.position:
                logger.info(
                    "Trade opened: %s entry=%.2f sl=%.2f tp=%.2f",
                    result.position.side.upper(),
                    result.position.entry_price,
                    result.position.sl_price,
                    result.position.tp_price,
                )
                if telegram:
                    await telegram.send_trade_opened(result.trade_setup, combined)
            elif result.error:
                logger.debug("Signal skipped: %s", result.error)

        balance = await exchange.get_balance()
        dashboard.update_balance(balance)

    except Exception as e:
        logger.error("on_candle_close error: %s", e, exc_info=True)


async def _enforce_max_hold(current_price: float) -> None:
    """Close any position held longer than max_hold_candles primary candles."""
    from data import TIMEFRAME_SECONDS
    max_candles = config.risk.max_hold_candles
    tf_seconds = TIMEFRAME_SECONDS.get(config.strategy.primary_tf, 3600)
    max_age = max_candles * tf_seconds
    now = datetime.utcnow()
    for pos in list(portfolio.get_open_positions()):
        age = (now - pos.entry_time).total_seconds()
        if age >= max_age:
            logger.info("Max-hold reached for %s, closing", pos.id)
            if isinstance(exchange, PaperExchange):
                await exchange.close_position(pos.symbol, pos.side, pos.quantity, "max_hold")
            else:
                await executor.close_position(pos, "max_hold", current_price)


async def daily_reset_loop() -> None:
    while True:
        now = datetime.utcnow()
        # Wait until midnight UTC
        tomorrow = datetime(now.year, now.month, now.day + 1 if now.day < 31 else 1,
                            0, 0, 0)
        seconds_until_midnight = (tomorrow - now).total_seconds()
        await asyncio.sleep(max(seconds_until_midnight, 60))

        today = date.today().isoformat()
        balance = await exchange.get_balance()
        executor.set_daily_starting_balance(balance)
        executor.reset_daily()

        logger.info("Daily reset. New starting balance: %.2f", balance)

        perf = await db.get_performance_summary()
        await db.upsert_daily_stats(DailyStats(
            date=today,
            starting_balance=balance,
            ending_balance=balance,
            total_trades=perf.total_trades,
            winning_trades=perf.winning_trades,
            total_pnl_usdt=perf.total_pnl_usdt,
            max_drawdown=perf.max_drawdown,
            is_paper=config.exchange.paper_mode,
        ))

        if telegram:
            await telegram.send_daily_summary(
                perf.total_trades, perf.winning_trades, perf.total_pnl_usdt, balance
            )


async def on_position_closed(pos, exit_price: float, net_pnl: float, reason: str) -> None:
    dashboard.add_trade(pos.side, pos.entry_price, exit_price, net_pnl, reason)
    if telegram:
        await telegram.send_trade_closed(
            pos.symbol, pos.side, pos.entry_price, exit_price, net_pnl, reason
        )


async def main() -> None:
    global data_mgr, exchange, executor, portfolio, dashboard
    global telegram, strategies, combiner, db, config

    config = load_config()
    logging.getLogger().setLevel(config.log_level)

    logger.info("Starting BTC Trading Bot (paper_mode=%s)", config.exchange.paper_mode)

    db = Database(config.db_path)
    await db.initialize()

    if config.exchange.paper_mode:
        exchange = PaperExchange(
            initial_balance=config.paper_initial_balance,
            leverage=config.exchange.leverage,
        )
        # For paper mode we still need a REST exchange for market data
        try:
            import ccxt.pro as ccxtpro
            rest_ex = ccxtpro.mexc({
                "options": {"defaultType": "swap", "defaultSubType": "linear"},
                "enableRateLimit": True,
            })
            await rest_ex.load_markets()
            exchange.set_rest_exchange(rest_ex)
        except Exception as e:
            logger.warning("Could not connect to MEXC for market data: %s", e)
            logger.warning("Running in offline mode with no live price data")
    else:
        live = LiveExchange(
            api_key=config.exchange.api_key,
            api_secret=config.exchange.api_secret,
            leverage=config.exchange.leverage,
            margin_mode=config.exchange.margin_mode,
        )
        await live.initialize(config.exchange.symbol)
        exchange = live

    data_mgr = DataManager(exchange, config.strategy, config.exchange.symbol)
    await data_mgr.initialize()

    initial_price = await data_mgr.get_current_price()
    if initial_price > 0 and isinstance(exchange, PaperExchange):
        await exchange.update_price(initial_price)

    portfolio = Portfolio(is_paper=config.exchange.paper_mode)

    risk_mgr = RiskManager(config.risk)
    executor = ExecutionEngine(exchange, risk_mgr, portfolio, db, config)
    executor.register_close_callback(on_position_closed)

    balance = await exchange.get_balance()
    executor.set_daily_starting_balance(balance)

    # Mean reversion is the single validated edge (see research_*.py).
    strategies = {
        "mean_rev": MeanReversionStrategy(config.strategy),
    }
    combiner = SignalCombiner(config.strategy)

    dashboard = Dashboard(portfolio)
    dashboard.update_balance(balance)
    dashboard.start()

    telegram = TelegramNotifier(config.telegram)
    await telegram.initialize()

    data_mgr.subscribe_candle_close(config.strategy.primary_tf, on_candle_close)

    asyncio.create_task(daily_reset_loop())

    logger.info(
        "Bot running. Symbol=%s TF=%s Balance=%.2f",
        config.exchange.symbol, config.strategy.primary_tf, balance,
    )

    await data_mgr.start_feeds()

    # Run until interrupted
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(__import__("signal").SIGINT, _handle_signal)
        loop.add_signal_handler(__import__("signal").SIGTERM, _handle_signal)
    except (NotImplementedError, OSError):
        pass

    await stop_event.wait()

    logger.info("Shutting down...")
    await data_mgr.stop()
    await db.close()
    if dashboard:
        dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())
