from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, date, timezone

from config import load_config
from database import Database, DailyStats
from data import DataManager, Candle
from exchange import PaperExchange, LiveExchange
from execution import ExecutionEngine
from funding import FundingMonitor
from orderflow import OrderFlowMonitor
from indicators import atr, adx as _adx_indicator
from monitor import Dashboard
from portfolio import Portfolio
from risk import RiskManager
from strategies.asia_bo import AsiaBoStrategy, AsiaBoSignal
from strategies.mean_reversion import MeanReversionStrategy
from strategies.orb import OrbStrategy, OrbSignal
from strategies.sr_breakout import SrBreakoutStrategy, SrBreakoutSignal
from strategies.signal_combiner import SignalCombiner, CombinedSignal
from telegram_bot import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Global component references (set in main())
exchange = None
executor: ExecutionEngine = None
portfolio: Portfolio = None
dashboard: Dashboard = None
telegram: TelegramNotifier = None
combiner: SignalCombiner = None
db: Database = None
config = None
funding_monitor: FundingMonitor = None
orderflow_monitor: OrderFlowMonitor = None
symbol_ctxs: dict[str, "SymbolContext"] = {}


@dataclass
class SymbolContext:
    """Per-coin trading context. Each coin has its own data feed and strategy
    instance, but all share the exchange, portfolio, executor and balance."""
    symbol: str
    data_mgr: DataManager
    strategy: MeanReversionStrategy
    orb_strategy: OrbStrategy = None
    asia_bo_strategy: AsiaBoStrategy = None
    sr_breakout_strategy: SrBreakoutStrategy = None


def make_on_candle_close(ctx: "SymbolContext"):
    """Build a candle-close handler bound to one coin's context."""

    async def on_candle_close(candle: Candle) -> None:
        try:
            import pandas as pd

            df = await ctx.data_mgr.get_candles(config.strategy.primary_tf, 120)
            if len(df) < config.strategy.bb_period + 5:
                return

            current_price = await ctx.data_mgr.get_current_price()
            # Per-coin price: a shared single price would be wrong across coins.
            portfolio.update_unrealized_pnl_for(ctx.symbol, current_price)
            dashboard.update_price(current_price)

            # Paper SL/TP fills first — only this coin's positions, using the
            # just-closed candle's range.
            if config.exchange.paper_mode and isinstance(exchange, PaperExchange):
                await exchange.check_sl_tp(candle.high, candle.low, ctx.symbol)

            # Force-close this coin's positions held beyond max_hold_candles
            await _enforce_max_hold(ctx.symbol, current_price)

            atr_val = atr(df["high"], df["low"], df["close"],
                          config.strategy.atr_period).iloc[-1]
            if pd.isna(atr_val) or atr_val <= 0:
                return

            # ADX for regime detection — determines which strategy sleeves are active.
            adx_raw = _adx_indicator(df["high"], df["low"], df["close"],
                                     config.strategy.adx_period).iloc[-1]
            adx_val = float(adx_raw) if not pd.isna(adx_raw) else 20.0
            regime = _get_regime(adx_val)
            dashboard.update_regime(regime, adx_val)

            # Trailing stop: update SL positions BEFORE the SL/TP check would fire
            # on this candle's high/low, but AFTER PaperExchange.check_sl_tp already
            # ran above — so the moved SL only affects the NEXT candle's SL check.
            await _update_trailing_stops(ctx.symbol, current_price, atr_val)

            # ── Parallel strategy execution with regime filter ────────────────
            # BB mean-reversion is NOT filtered by ADX (vol filter is sufficient).
            # ORB / Asia BO / S/R ARE suppressed in ranging (ADX<20): false-breakout
            # rate spikes in choppy markets.
            #
            # Each strategy has its own position slot so they run independently:
            #   BB   → slot = symbol          (swing, 48h max-hold)
            #   ORB  → slot = symbol:orb      (intraday, 6h max-hold)
            #   Asia → slot = symbol:asia_bo  (intraday, 6h max-hold)
            #   S/R  → slot = symbol          (swing, shares BB slot — only one
            #                                  swing at a time; fires when BB empty)
            # max_positions=3 allows BB + ORB + Asia simultaneously.
            regime_filter = config.risk.regime_filter_enabled
            bo_allowed = not (regime_filter and regime == "ranging")

            # ── BB mean-reversion ─────────────────────────────────────────────
            mr_sig = ctx.strategy.analyze(df)
            bb_combined = CombinedSignal(
                direction=mr_sig.direction,
                confidence=mr_sig.strength,
                trend_score=0.0,
                mean_rev_score=mr_sig.direction * mr_sig.strength,
                breakout_score=0.0,
                dominant_strategy="mean_rev",
                reasons=[mr_sig.reason],
                entry_price=current_price,
                symbol=ctx.symbol,
                position_slot=ctx.symbol,
            )
            dashboard.update_signal(bb_combined)
            dashboard.log_message(
                f"[{ctx.symbol}] BB: dir={bb_combined.direction} "
                f"conf={bb_combined.confidence:.2f} ({mr_sig.reason})"
            )

            # Funding rate / order-flow checks apply to the BB signal only
            # (they're not meaningful for intraday range-breakout strategies).
            if (
                bb_combined.direction != 0
                and funding_monitor is not None
                and funding_monitor.enabled
            ):
                snap = await funding_monitor.fetch()
                assess = funding_monitor.evaluate(bb_combined.direction, snap)
                logger.info("Funding read: %s -> bias=%.2f", assess.reason, assess.bias)
                dashboard.log_message(f"Funding: {assess.reason}")
                if funding_monitor.mode == "filter" and assess.should_skip:
                    dashboard.log_message(
                        f"BB signal SKIPPED by funding filter ({assess.reason})"
                    )
                    logger.info("BB skipped: funding contrary+extreme (%s)", assess.reason)
                    bb_combined.direction = 0
                elif funding_monitor.mode == "boost":
                    bb_combined.confidence = min(bb_combined.confidence * assess.bias, 1.0)

            if (
                bb_combined.direction != 0
                and orderflow_monitor is not None
                and orderflow_monitor.enabled
                and ctx.symbol == config.exchange.symbol
            ):
                try:
                    of_snap = await orderflow_monitor.snapshot()
                    of_assess = orderflow_monitor.evaluate(bb_combined.direction, of_snap)
                    logger.info("OrderFlow: %s", of_assess.reason)
                    dashboard.log_message(f"OrderFlow: {of_assess.reason}")
                    _log_orderflow_csv(ctx.symbol, bb_combined, mr_sig, of_snap, of_assess)
                except Exception as e:
                    logger.debug("OrderFlow snapshot failed: %s", e)

            if bb_combined.direction != 0:
                result = await executor.execute_signal(bb_combined, atr_val)
                if result.success and result.position:
                    logger.info(
                        "BB trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                        result.position.side.upper(), ctx.symbol,
                        result.position.entry_price,
                        result.position.sl_price,
                        result.position.tp_price,
                    )
                    if telegram:
                        await telegram.send_trade_opened(result.trade_setup, bb_combined)
                elif result.error:
                    logger.debug("[%s] BB skipped: %s", ctx.symbol, result.error)

            # ── ORB — independent slot, limit entry at NY open range boundary ─
            # Backtest validated: PF 2.53/2.83 with limit entry vs PF 0.74 with
            # close entry. Fill assumption: when 15:00 UTC bar closes above
            # orb_high, we fill at orb_high (price already touched it intrabar).
            if ctx.orb_strategy is not None and bo_allowed:
                orb_sig = ctx.orb_strategy.analyze(df)
                if orb_sig.direction != 0:
                    trigger = orb_sig.orb_high if orb_sig.direction == 1 else orb_sig.orb_low
                    orb_combined = CombinedSignal(
                        direction=orb_sig.direction,
                        confidence=orb_sig.strength,
                        trend_score=0.0,
                        mean_rev_score=0.0,
                        breakout_score=orb_sig.direction * orb_sig.strength,
                        dominant_strategy="orb",
                        reasons=[orb_sig.reason],
                        entry_price=trigger,
                        sl_price=orb_sig.sl_price,
                        tp_price=orb_sig.tp_price,
                        symbol=ctx.symbol,
                        position_slot=f"{ctx.symbol}:orb",
                    )
                    result = await executor.execute_signal(orb_combined, atr_val)
                    if result.success and result.position:
                        logger.info(
                            "ORB trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                            result.position.side.upper(), ctx.symbol,
                            result.position.entry_price,
                            result.position.sl_price,
                            result.position.tp_price,
                        )
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, orb_combined)
                    elif result.error:
                        logger.debug("[%s] ORB skipped: %s", ctx.symbol, result.error)

            # ── Asia BO — independent slot, limit entry at London open range ──
            # Fill at asia_high/asia_low when 08:00 UTC bar first closes above/below.
            if ctx.asia_bo_strategy is not None and bo_allowed:
                asia_sig = ctx.asia_bo_strategy.analyze(df, atr_val)
                if asia_sig.direction != 0:
                    trigger = asia_sig.asia_high if asia_sig.direction == 1 else asia_sig.asia_low
                    asia_combined = CombinedSignal(
                        direction=asia_sig.direction,
                        confidence=asia_sig.strength,
                        trend_score=0.0,
                        mean_rev_score=0.0,
                        breakout_score=asia_sig.direction * asia_sig.strength,
                        dominant_strategy="asia_bo",
                        reasons=[asia_sig.reason],
                        entry_price=trigger,
                        sl_price=asia_sig.sl_price,
                        tp_price=asia_sig.tp_price,
                        symbol=ctx.symbol,
                        position_slot=f"{ctx.symbol}:asia_bo",
                    )
                    result = await executor.execute_signal(asia_combined, atr_val)
                    if result.success and result.position:
                        logger.info(
                            "Asia BO trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                            result.position.side.upper(), ctx.symbol,
                            result.position.entry_price,
                            result.position.sl_price,
                            result.position.tp_price,
                        )
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, asia_combined)
                    elif result.error:
                        logger.debug("[%s] Asia BO skipped: %s", ctx.symbol, result.error)

            # ── S/R breakout — shares BB slot (swing, 48h hold) ──────────────
            # Only fires when the BB slot is empty. Uses max_positions cap as the
            # ultimate gate: when BB + ORB + Asia are all open, S/R is blocked.
            if ctx.sr_breakout_strategy is not None and bo_allowed:
                sr_sig = ctx.sr_breakout_strategy.analyze(df, atr_val)
                if sr_sig.direction != 0:
                    sr_combined = CombinedSignal(
                        direction=sr_sig.direction,
                        confidence=sr_sig.strength,
                        trend_score=0.0,
                        mean_rev_score=0.0,
                        breakout_score=sr_sig.direction * sr_sig.strength,
                        dominant_strategy="sr_breakout",
                        reasons=[sr_sig.reason],
                        entry_price=current_price,
                        sl_price=sr_sig.sl_price,
                        tp_price=sr_sig.tp_price,
                        symbol=ctx.symbol,
                        position_slot=ctx.symbol,
                    )
                    result = await executor.execute_signal(sr_combined, atr_val)
                    if result.success and result.position:
                        logger.info(
                            "S/R trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                            result.position.side.upper(), ctx.symbol,
                            result.position.entry_price,
                            result.position.sl_price,
                            result.position.tp_price,
                        )
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, sr_combined)
                    elif result.error:
                        logger.debug("[%s] S/R skipped: %s", ctx.symbol, result.error)

            balance = await exchange.get_balance()
            dashboard.update_balance(balance)

        except Exception as e:
            logger.error("[%s] on_candle_close error: %s", ctx.symbol, e, exc_info=True)

    return on_candle_close


_ORDERFLOW_CSV = "orderflow_log.csv"


def _log_orderflow_csv(symbol, combined, mr_sig, snap, assess) -> None:
    """Append one order-flow observation per signal to a CSV. Survives restarts
    (unlike journald) so the forward dataset can be analysed later with pandas."""
    import csv
    import os
    from pathlib import Path
    header = [
        "ts", "symbol", "direction", "bb_pos", "confidence",
        "delta", "delta_pct", "buy_ratio", "depth_imbalance",
        "trade_count", "flow_aligned", "flow_contrary",
    ]
    row = [
        datetime.now(timezone.utc).isoformat(), symbol, combined.direction,
        round(mr_sig.bb_pos, 4), round(combined.confidence, 4),
        round(snap.delta, 4), round(snap.delta_pct, 4), round(snap.buy_ratio, 4),
        round(snap.depth_imbalance, 4), snap.trade_count,
        int(assess.aligned), int(assess.contrary),
    ]
    try:
        exists = Path(_ORDERFLOW_CSV).exists()
        with open(_ORDERFLOW_CSV, "a", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(header)
            w.writerow(row)
    except Exception as e:
        logger.debug("orderflow csv write failed: %s", e)


def _get_regime(adx_val: float) -> str:
    """Classify market condition by ADX for strategy routing."""
    trending = getattr(config.risk, "adx_trending_threshold", 28.0)
    ranging = getattr(config.risk, "adx_ranging_threshold", 20.0)
    if adx_val >= trending:
        return "trending"
    if adx_val <= ranging:
        return "ranging"
    return "neutral"


async def _update_trailing_stops(symbol: str, current_price: float, atr_val: float) -> None:
    """Each candle: update trailing SL for directional (breakout) positions.
    Logic:
      1. Breakeven: after be_mult×ATR profit → SL moves to entry (risk-free).
      2. Trailing: ONLY after breakeven, trail at trail_mult×ATR below peak.
    BB mean-reversion trades are excluded — trailing hurts mean-rev because the
    retracement that moves SL to breakeven is part of the normal path to TP."""
    if not getattr(config.risk, "trailing_stop_enabled", True):
        return

    be_mult = config.risk.breakeven_atr_mult
    trail_mult = config.risk.trailing_atr_mult

    for pos in portfolio.get_open_positions():
        if pos.symbol != symbol:
            continue

        # Trailing stop is for directional (breakout/trend) strategies only.
        # BB mean-reversion has a natural retrace path to TP; trailing hurts it.
        strategy_tag = pos.strategy_scores.get("strategy", "mean_rev")
        if strategy_tag == "mean_rev":
            continue

        entry_atr = pos.strategy_scores.get("atr", atr_val)
        old_sl = pos.sl_price
        new_sl = old_sl

        if pos.direction == 1:  # long
            if pos.peak_price == 0.0 or current_price > pos.peak_price:
                pos.peak_price = current_price

            if not pos.breakeven_moved and current_price >= pos.entry_price + be_mult * entry_atr:
                new_sl = max(new_sl, pos.entry_price)
                pos.breakeven_moved = True

            # Trail ONLY after breakeven — prevents immediate SL tightening on new trades
            if pos.breakeven_moved:
                trail_sl = pos.peak_price - trail_mult * entry_atr
                new_sl = max(new_sl, trail_sl)

        else:  # short
            if pos.peak_price == 0.0 or current_price < pos.peak_price:
                pos.peak_price = current_price

            if not pos.breakeven_moved and current_price <= pos.entry_price - be_mult * entry_atr:
                new_sl = min(new_sl, pos.entry_price)
                pos.breakeven_moved = True

            if pos.breakeven_moved:
                trail_sl = pos.peak_price + trail_mult * entry_atr
                new_sl = min(new_sl, trail_sl)

        if new_sl != old_sl:
            pos.sl_price = new_sl
            if isinstance(exchange, PaperExchange) and hasattr(exchange, "update_position_sl"):
                exchange.update_position_sl(pos.id, new_sl)
            action = "BE" if pos.breakeven_moved and new_sl == pos.entry_price else "Trail"
            dashboard.log_message(
                f"[{symbol}] SL {action}: {old_sl:,.2f} → {new_sl:,.2f}"
            )
            logger.info(
                "Trailing SL [%s] %s %.2f → %.2f", pos.id[:8], action, old_sl, new_sl
            )


async def _enforce_max_hold(symbol: str, current_price: float) -> None:
    """Close this symbol's positions held longer than max_hold_candles candles.
    Day-trading positions store their own limit in strategy_scores['max_hold']."""
    from data import TIMEFRAME_SECONDS
    tf_seconds = TIMEFRAME_SECONDS.get(config.strategy.primary_tf, 3600)
    now = datetime.now(timezone.utc)
    for pos in list(portfolio.get_open_positions()):
        if pos.symbol != symbol:
            continue
        # Per-position override (set by day-trading strategies) takes priority.
        max_candles = pos.strategy_scores.get("max_hold", config.risk.max_hold_candles)
        max_age = max_candles * tf_seconds
        age = (now - pos.entry_time).total_seconds()
        if age >= max_age:
            logger.info(
                "Max-hold (%dh) reached for %s (%s), closing",
                max_candles, pos.id, symbol,
            )
            if isinstance(exchange, PaperExchange):
                await exchange.close_position(pos.symbol, pos.side, pos.quantity, "max_hold")
            else:
                await executor.close_position(pos, "max_hold", current_price)


async def daily_reset_loop() -> None:
    from datetime import timedelta
    while True:
        now = datetime.now(timezone.utc)
        # Wait until next midnight UTC. Using timedelta avoids the month-end
        # crash of constructing datetime(day=now.day+1) (e.g. day 31 in a
        # 30-day month raised ValueError and broke the daily reset).
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
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


async def restore_state() -> int:
    """Rebuild open positions after a restart so they are not orphaned.

    Paper: restore the persisted balance, then recreate each open trade's paper
    position + portfolio position (sharing the same id as the DB row).
    Live: the positions still exist on the exchange; rebuild the portfolio from
    the open DB trades so the bot tracks and manages them again.
    """
    restored = 0
    if config.exchange.paper_mode and isinstance(exchange, PaperExchange):
        saved = await db.get_meta("paper_balance")
        if saved is not None:
            try:
                exchange.set_balance(float(saved))
                logger.info("Restored paper balance: %.2f", float(saved))
            except ValueError:
                pass

    open_trades = await db.get_open_trades()
    for t in open_trades:
        direction = 1 if t.side == "long" else -1
        try:
            entry_dt = datetime.fromisoformat(t.entry_time)
        except (ValueError, TypeError):
            entry_dt = datetime.now(timezone.utc)
        if config.exchange.paper_mode and isinstance(exchange, PaperExchange):
            exchange.restore_position(
                t.id, t.symbol, t.side, t.quantity,
                t.entry_price, t.sl_price, t.tp_price,
            )
        portfolio.create_position(
            symbol=t.symbol, direction=direction, entry_price=t.entry_price,
            sl_price=t.sl_price, tp_price=t.tp_price, quantity=t.quantity,
            strategy_scores=t.strategy_scores, is_paper=t.is_paper,
            position_id=t.id, entry_time=entry_dt,
        )
        restored += 1
        logger.info("Restored open position: %s %s @ %.4f",
                    t.side.upper(), t.symbol, t.entry_price)
    if restored:
        logger.info("Restored %d open position(s) after restart", restored)
    return restored


async def heartbeat_loop() -> None:
    """Periodic liveness signal: writes a timestamp file (for an external
    healthcheck) and, every few hours, a Telegram 'alive' message so a silent
    death is noticeable."""
    import time as _time
    from pathlib import Path as _Path
    interval = 300  # touch the liveness file every 5 min
    tg_every = max(int(config.heartbeat_hours * 3600), interval)
    since_tg = 0
    while True:
        try:
            _Path("/tmp/bot_alive").write_text(str(int(_time.time())))
        except Exception:
            pass
        since_tg += interval
        if telegram and since_tg >= tg_every:
            since_tg = 0
            try:
                bal = await exchange.get_balance()
                n_open = portfolio.get_open_position_count()
                upnl = portfolio.get_total_unrealized_pnl()
                await telegram.send_alert(
                    f"Bot çalışıyor · bakiye ${bal:,.2f} · açık {n_open} · "
                    f"gerçekleşmemiş ${upnl:+.2f}", "INFO",
                )
            except Exception as e:
                logger.debug("Heartbeat telegram failed: %s", e)
        await asyncio.sleep(interval)


async def on_position_closed(pos, exit_price: float, net_pnl: float, reason: str) -> None:
    dashboard.add_trade(pos.side, pos.entry_price, exit_price, net_pnl, reason)
    if telegram:
        await telegram.send_trade_closed(
            pos.symbol, pos.side, pos.entry_price, exit_price, net_pnl, reason
        )


async def main() -> None:
    global exchange, executor, portfolio, dashboard
    global telegram, combiner, db, config, funding_monitor, orderflow_monitor, symbol_ctxs

    config = load_config()
    logging.getLogger().setLevel(config.log_level)

    symbols = config.exchange.symbols or [config.exchange.symbol]
    logger.info(
        "Starting Trading Bot (paper_mode=%s) — %d coin(s): %s",
        config.exchange.paper_mode, len(symbols), ", ".join(symbols),
    )

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
        # Set leverage/margin per coin before trading.
        for sym in symbols:
            await live.initialize(sym)
        exchange = live

    portfolio = Portfolio(is_paper=config.exchange.paper_mode)

    # One DataManager + strategy per coin; all share the exchange/portfolio.
    symbol_ctxs = {}
    for sym in symbols:
        dm = DataManager(exchange, config.strategy, sym)
        await dm.initialize()
        init_price = await dm.get_current_price()
        if init_price > 0 and isinstance(exchange, PaperExchange):
            await exchange.update_price(init_price, sym)
        symbol_ctxs[sym] = SymbolContext(
            symbol=sym,
            data_mgr=dm,
            strategy=MeanReversionStrategy(config.strategy),
            orb_strategy=(
                OrbStrategy() if config.strategy.orb_enabled else None
            ),
            asia_bo_strategy=(
                AsiaBoStrategy() if config.strategy.asia_bo_enabled else None
            ),
            sr_breakout_strategy=(
                SrBreakoutStrategy() if config.strategy.sr_breakout_enabled else None
            ),
        )

    risk_mgr = RiskManager(config.risk)
    executor = ExecutionEngine(exchange, risk_mgr, portfolio, db, config)
    executor.register_close_callback(on_position_closed)

    async def _send_alert(message: str, level: str) -> None:
        if telegram:
            await telegram.send_alert(message, level)
    executor.register_alert_callback(_send_alert)

    # Rebuild any open positions from before a restart (balance + positions).
    await restore_state()

    balance = await exchange.get_balance()
    executor.set_daily_starting_balance(balance)

    combiner = SignalCombiner(config.strategy)

    # Funding monitor tracks the primary symbol (read-only dataset building).
    funding_monitor = FundingMonitor(
        exchange,
        config.exchange.symbol,
        enabled=config.strategy.funding_enabled,
        mode=config.strategy.funding_mode,
        extreme_threshold=config.strategy.funding_extreme,
    )
    if funding_monitor.enabled:
        logger.info(
            "Funding monitor ON (mode=%s, extreme=%.4f%%)",
            funding_monitor.mode, config.strategy.funding_extreme * 100,
        )

    # Order-flow collector also tracks only the primary symbol (one watchTrades
    # feed). Default OFF; started below after the data feeds are up.
    orderflow_monitor = OrderFlowMonitor(
        exchange,
        config.exchange.symbol,
        enabled=config.strategy.orderflow_enabled,
        mode=config.strategy.orderflow_mode,
        window_minutes=config.strategy.orderflow_window_min,
    )

    dashboard = Dashboard(portfolio)
    dashboard.update_balance(balance)
    dashboard.start()

    telegram = TelegramNotifier(config.telegram)
    # Give Telegram access to the engine so the user can query and control the
    # bot from their phone (/status, /positions, /pause, /resume, /close).
    telegram.attach_context(
        exchange=exchange,
        portfolio=portfolio,
        executor=executor,
        db=db,
        app_config=config,
        initial_balance=balance,
    )
    await telegram.initialize()

    # Wire each coin's candle-close handler and start its data feed.
    for sym, ctx in symbol_ctxs.items():
        ctx.data_mgr.subscribe_candle_close(
            config.strategy.primary_tf, make_on_candle_close(ctx)
        )

    asyncio.create_task(daily_reset_loop())
    asyncio.create_task(heartbeat_loop())

    logger.info(
        "Bot running. Coins=%d TF=%s Balance=%.2f",
        len(symbol_ctxs), config.strategy.primary_tf, balance,
    )

    for ctx in symbol_ctxs.values():
        await ctx.data_mgr.start_feeds()

    # Start the order-flow feed (no-op if disabled).
    await orderflow_monitor.start()

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
    if orderflow_monitor is not None:
        await orderflow_monitor.stop()
    for ctx in symbol_ctxs.values():
        await ctx.data_mgr.stop()
    if telegram:
        await telegram.shutdown()
    await db.close()
    if dashboard:
        dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())
