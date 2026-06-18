from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, date, timezone

from config import load_config
from database import Database, DailyStats
from data import DataManager, Candle, TIMEFRAME_SECONDS
from exchange import PaperExchange, LiveExchange
from execution import ExecutionEngine
from funding import FundingMonitor
from orderflow import OrderFlowMonitor
from whale_flow import WhaleFlowMonitor
from strategies.squeeze import SqueezeStrategy, SqueezeSignal
from strategies.whale import WhaleStrategy
from indicators import atr, adx as _adx_indicator
from monitor import Dashboard
from portfolio import Portfolio
from risk import RiskManager
from strategies.asia_bo import AsiaBoStrategy, AsiaBoSignal
from strategies.fvg import FvgStrategy, FvgSignal
from strategies.ifvg import IfvgStrategy, IfvgSignal
from strategies.mean_reversion import MeanReversionStrategy
from strategies.orb import OrbStrategy, OrbSignal
from strategies.sr_breakout import SrBreakoutStrategy, SrBreakoutSignal
from strategies.signal_combiner import SignalCombiner, CombinedSignal
from ntfy_notifier import NtfyNotifier
from telegram_bot import TelegramNotifier
from web_dashboard import WebDashboard

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
ntfy: NtfyNotifier = None
web_dashboard: WebDashboard = None
combiner: SignalCombiner = None
db: Database = None
config = None
funding_monitor: FundingMonitor = None
orderflow_monitor: OrderFlowMonitor = None
whale_monitor: WhaleFlowMonitor = None
symbol_ctxs: dict[str, "SymbolContext"] = {}
# Long-lived background loops, kept referenced so they can be cancelled on
# shutdown and so a crash is logged (a bare create_task() drops the reference
# and swallows the exception silently).
_bg_tasks: list[asyncio.Task] = []


def _spawn_supervised(coro, name: str) -> asyncio.Task:
    """Start a background loop, keep a reference, and log loudly if it ever
    exits — a silent death of daily_reset/heartbeat/reconciliation would let the
    bot keep trading with a stale daily-loss baseline or an undetected ghost."""
    task = asyncio.create_task(coro, name=name)

    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.critical("Background task '%s' CRASHED: %r", name, exc)
        else:
            logger.error("Background task '%s' exited unexpectedly", name)

    task.add_done_callback(_done)
    _bg_tasks.append(task)
    return task


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
    fvg_strategy: FvgStrategy = None
    ifvg_strategy: IfvgStrategy = None
    squeeze_strategy: "SqueezeStrategy" = None
    whale_strategy: "WhaleStrategy" = None


def active_sleeves_for(ctx: "SymbolContext", cfg) -> list[str]:
    """The strategy sleeves that will actually trade this coin. ORB/Asia/S/R/FVG/
    IFVG are gated by whether their instance was created (None = off); BB is gated
    at runtime by the bb_symbols allowlist, so reflect that here too — otherwise
    the layout would falsely show BB on BNB/XRP where the edge did not transfer."""
    sleeves: list[str] = []
    bb_allow = getattr(cfg.strategy, "bb_symbols", None)
    if bb_allow is None or ctx.symbol in bb_allow:
        sleeves.append("BB")
    if ctx.orb_strategy is not None: sleeves.append("ORB")
    if ctx.asia_bo_strategy is not None: sleeves.append("Asia")
    if ctx.sr_breakout_strategy is not None: sleeves.append("S/R")
    if ctx.fvg_strategy is not None: sleeves.append("FVG")
    if ctx.ifvg_strategy is not None: sleeves.append("IFVG")
    if ctx.squeeze_strategy is not None: sleeves.append("Squeeze")
    if ctx.whale_strategy is not None:
        whale_mode = getattr(cfg.strategy, "whale_mode", "monitor")
        sleeves.append("Whale" + ("" if whale_mode == "trade" else "(mon)"))
    return sleeves


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
            # Each strategy has its own position slot so they run independently:
            #   BB   → slot = symbol          (swing, 48h max-hold)
            #   ORB  → slot = symbol:orb      (intraday, 6h max-hold)
            #   Asia → slot = symbol:asia_bo  (intraday, 6h max-hold)
            #   S/R  → slot = symbol          (swing, shares BB slot — only one
            #                                  swing at a time; fires when BB empty)
            # max_positions=3 allows BB + ORB + Asia simultaneously.
            #
            # Regime routing:
            #   Trending (ADX>28) → suppress BB (fading a strong trend loses).
            #   Ranging  (ADX<20) → suppress ORB/S/R (false-breakout rate spikes).
            # Weekday gate: if BB_WEEKDAY_ENABLED=false, skip BB Mon–Fri (research
            # shows weekday BB PF ~0.97; the ADX gate covers the worst subset but an
            # explicit weekday disable is available as a stronger filter).
            regime_filter = config.risk.regime_filter_enabled
            bo_allowed = not (regime_filter and regime == "ranging")
            is_weekend = datetime.now(timezone.utc).weekday() >= 5
            bb_allowed = not (regime_filter and regime == "trending")
            if not getattr(config.risk, "bb_weekday_enabled", True) and not is_weekend:
                bb_allowed = False
            # Per-coin BB allowlist: BNB (PF 0.89) and XRP (test 1.03, WR drop)
            # failed cross-coin validation — gate them out.
            bb_coin_allowed = config.strategy.bb_symbols
            if bb_coin_allowed is not None and ctx.symbol not in bb_coin_allowed:
                bb_allowed = False

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

            if bb_combined.direction != 0 and not bb_allowed:
                logger.debug(
                    "[%s] BB skipped: regime=%s is_weekend=%s", ctx.symbol, regime, is_weekend
                )
            elif bb_combined.direction != 0:
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
                    if ntfy:
                        await ntfy.send_trade_opened(result.trade_setup, bb_combined)
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
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, orb_combined)
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
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, asia_combined)
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
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, sr_combined)
                    elif result.error:
                        logger.debug("[%s] S/R skipped: %s", ctx.symbol, result.error)

            # ── FVG (Fair Value Gap) — independent slot, limit retest entry ───
            # Price-action sleeve (PF 1.37, positive every year). NOT gated by the
            # breakout regime filter — it's a gap-fill retest, not a breakout. Needs
            # a longer buffer (EMA200 trend filter) so it fetches 250 candles.
            df_long = None
            if ctx.fvg_strategy is not None or ctx.ifvg_strategy is not None:
                df_long = await ctx.data_mgr.get_candles(config.strategy.primary_tf, 250)
            if ctx.fvg_strategy is not None:
                df_fvg = df_long
                fvg_sig = ctx.fvg_strategy.analyze(df_fvg, atr_val)
                if fvg_sig.direction != 0:
                    fvg_combined = CombinedSignal(
                        direction=fvg_sig.direction,
                        confidence=fvg_sig.strength,
                        trend_score=0.0,
                        mean_rev_score=0.0,
                        breakout_score=fvg_sig.direction * fvg_sig.strength,
                        dominant_strategy="fvg",
                        reasons=[fvg_sig.reason],
                        entry_price=fvg_sig.entry_price,
                        sl_price=fvg_sig.sl_price,
                        tp_price=fvg_sig.tp_price,
                        symbol=ctx.symbol,
                        position_slot=f"{ctx.symbol}:fvg",
                    )
                    result = await executor.execute_signal(fvg_combined, atr_val)
                    if result.success and result.position:
                        logger.info(
                            "FVG trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                            result.position.side.upper(), ctx.symbol,
                            result.position.entry_price,
                            result.position.sl_price,
                            result.position.tp_price,
                        )
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, fvg_combined)
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, fvg_combined)
                    elif result.error:
                        logger.debug("[%s] FVG skipped: %s", ctx.symbol, result.error)

            # ── IFVG (Inverse FVG) — independent slot, broken-gap reversal retest ─
            # Same 250-candle buffer (EMA200 trend). Not gated by breakout regime.
            if ctx.ifvg_strategy is not None:
                df_ifvg = df_long if df_long is not None else \
                    await ctx.data_mgr.get_candles(config.strategy.primary_tf, 250)
                ifvg_sig = ctx.ifvg_strategy.analyze(df_ifvg, atr_val)
                if ifvg_sig.direction != 0:
                    ifvg_combined = CombinedSignal(
                        direction=ifvg_sig.direction,
                        confidence=ifvg_sig.strength,
                        trend_score=0.0,
                        mean_rev_score=0.0,
                        breakout_score=ifvg_sig.direction * ifvg_sig.strength,
                        dominant_strategy="ifvg",
                        reasons=[ifvg_sig.reason],
                        entry_price=ifvg_sig.entry_price,
                        sl_price=ifvg_sig.sl_price,
                        tp_price=ifvg_sig.tp_price,
                        symbol=ctx.symbol,
                        position_slot=f"{ctx.symbol}:ifvg",
                    )
                    result = await executor.execute_signal(ifvg_combined, atr_val)
                    if result.success and result.position:
                        logger.info(
                            "IFVG trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                            result.position.side.upper(), ctx.symbol,
                            result.position.entry_price,
                            result.position.sl_price,
                            result.position.tp_price,
                        )
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, ifvg_combined)
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, ifvg_combined)
                    elif result.error:
                        logger.debug("[%s] IFVG skipped: %s", ctx.symbol, result.error)

            # ── Squeeze — BB+KC volatility coil → momentum breakout ─────────
            # Independent slot (symbol:squeeze), uses bo_allowed gate (trending
            # markets are fine for momentum — ranging markets suppress breakouts).
            if ctx.squeeze_strategy is not None and bo_allowed:
                sq_sig = ctx.squeeze_strategy.analyze(df, atr_val)
                if sq_sig.direction != 0:
                    sq_combined = CombinedSignal(
                        direction=sq_sig.direction,
                        confidence=sq_sig.strength,
                        trend_score=0.0,
                        mean_rev_score=0.0,
                        breakout_score=sq_sig.direction * sq_sig.strength,
                        dominant_strategy="squeeze",
                        reasons=[sq_sig.reason],
                        entry_price=sq_sig.entry_price,
                        sl_price=sq_sig.sl_price,
                        tp_price=sq_sig.tp_price,
                        symbol=ctx.symbol,
                        position_slot=f"{ctx.symbol}:squeeze",
                    )
                    result = await executor.execute_signal(sq_combined, atr_val)
                    if result.success and result.position:
                        logger.info(
                            "SQUEEZE trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f"
                            " (coil=%db)",
                            result.position.side.upper(), ctx.symbol,
                            result.position.entry_price,
                            result.position.sl_price,
                            result.position.tp_price,
                            sq_sig.squeeze_bars,
                        )
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, sq_combined)
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, sq_combined)
                    elif result.error:
                        logger.debug("[%s] Squeeze skipped: %s", ctx.symbol, result.error)
                else:
                    logger.debug("[%s] squeeze: %s", ctx.symbol, sq_sig.reason)

            # ── Whale-flow sleeve — avg-trade-size z-spike, follow the candle ──
            # Monitor-first: avg_size needs live trade count (not in MEXC klines),
            # supplied by whale_monitor from watchTrades. Needs ~1 week warmup.
            # In "monitor" mode we LOG would-be signals without trading; in
            # "trade" mode it executes like the other sleeves. BTC-only.
            if ctx.whale_strategy is not None and whale_monitor is not None \
                    and whale_monitor.enabled:
                z = whale_monitor.bar_zscore(candle.timestamp)
                whale_sig = ctx.whale_strategy.analyze(
                    candle.open, candle.close, z, atr_val
                )
                if whale_sig.direction != 0:
                    whale_mode = getattr(config.strategy, "whale_mode", "monitor")
                    if whale_mode != "trade":
                        logger.info(
                            "[%s] WHALE signal (MONITOR, no trade): %s z=%.2f "
                            "entry=%.4f sl=%.4f tp=%.4f",
                            ctx.symbol, "LONG" if whale_sig.direction == 1 else "SHORT",
                            whale_sig.z, whale_sig.entry_price,
                            whale_sig.sl_price, whale_sig.tp_price,
                        )
                        _log_whale_csv(ctx.symbol, whale_sig, current_price)
                    else:
                        whale_combined = CombinedSignal(
                            direction=whale_sig.direction,
                            confidence=whale_sig.strength,
                            trend_score=0.0, mean_rev_score=0.0,
                            breakout_score=whale_sig.direction * whale_sig.strength,
                            dominant_strategy="whale",
                            reasons=[whale_sig.reason],
                            entry_price=whale_sig.entry_price,
                            sl_price=whale_sig.sl_price,
                            tp_price=whale_sig.tp_price,
                            symbol=ctx.symbol,
                            position_slot=f"{ctx.symbol}:whale",
                        )
                        result = await executor.execute_signal(whale_combined, atr_val)
                        if result.success and result.position:
                            logger.info(
                                "WHALE trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                                result.position.side.upper(), ctx.symbol,
                                result.position.entry_price,
                                result.position.sl_price, result.position.tp_price,
                            )
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, whale_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, whale_combined)
                        elif result.error:
                            logger.debug("[%s] WHALE skipped: %s", ctx.symbol, result.error)
                elif z is not None:
                    logger.debug("[%s] whale z=%.2f (no fire)", ctx.symbol, z)

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


_WHALE_CSV = "whale_log.csv"


def _log_whale_csv(symbol, sig, current_price) -> None:
    """Append every would-be whale signal to a CSV so the monitor-mode forward
    test survives restarts and can be analysed against realised outcomes."""
    import csv
    from pathlib import Path
    header = ["ts", "symbol", "direction", "z", "entry", "sl", "tp",
              "price_at_signal", "strength"]
    row = [
        datetime.now(timezone.utc).isoformat(), symbol, sig.direction,
        round(sig.z, 4), round(sig.entry_price, 6), round(sig.sl_price, 6),
        round(sig.tp_price, 6), round(current_price, 6), round(sig.strength, 4),
    ]
    try:
        exists = Path(_WHALE_CSV).exists()
        with open(_WHALE_CSV, "a", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(header)
            w.writerow(row)
    except Exception as e:
        logger.debug("whale csv write failed: %s", e)


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

        # Trailing applies ONLY to the S/R breakout swing strategy. BB mean-rev
        # has a natural retrace path to TP (trailing hurts it). ORB, Asia BO, FVG,
        # IFVG and Squeeze were all VALIDATED with FIXED SL/TP (and a max-hold) —
        # NOT with trailing. Applying trailing to them would make live behaviour
        # diverge from the backtest, so they keep their fixed exchange-side exits.
        strategy_tag = pos.strategy_scores.get("strategy", "mean_rev")
        if strategy_tag != "sr_breakout":
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
            if isinstance(exchange, PaperExchange):
                pos.sl_price = new_sl
                if hasattr(exchange, "update_position_sl"):
                    exchange.update_position_sl(pos.id, new_sl)
            else:
                # Live: update the internal SL, then re-sync ALL of this symbol's
                # stops on MEXC (cancel-all + re-place every open sleeve). This
                # moves our stop while keeping any sibling sleeve on the same
                # netted symbol protected. resync alerts if a re-place fails.
                pos.sl_price = new_sl
                ok = await executor.resync_symbol_stops(pos.symbol)
                if not ok:
                    logger.error(
                        "[%s] Trailing moved internal SL to %.4f but exchange "
                        "re-sync failed — exchange stop may not match", symbol, new_sl,
                    )
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

        # Wrap the whole body: an unhandled error here used to kill the loop
        # permanently (so the daily-loss baseline would never re-arm again).
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            # Snapshot starting EQUITY (free + locked margin + unrealized), not
            # free balance — the daily-loss limit measures drawdown, not margin.
            await executor.capture_daily_start()
            executor.reset_daily()
            # Persist the EQUITY baseline (matches the daily-loss limit's measure
            # and what the startup path reads back after a restart).
            start_equity = await executor.current_equity()

            logger.info("Daily reset. New starting equity: %.2f", start_equity)

            perf = await db.get_performance_summary(is_paper=config.exchange.paper_mode)
            await db.upsert_daily_stats(DailyStats(
                date=today,
                starting_balance=start_equity,
                ending_balance=start_equity,
                total_trades=perf.total_trades,
                winning_trades=perf.winning_trades,
                total_pnl_usdt=perf.total_pnl_usdt,
                max_drawdown=perf.max_drawdown,
                is_paper=config.exchange.paper_mode,
            ))

            # NOTE: `balance` was an undefined name here before — it raised
            # NameError and silently killed this loop on the first reset. Use the
            # equity we just computed.
            if telegram:
                await telegram.send_daily_summary(
                    perf.total_trades, perf.winning_trades,
                    perf.total_pnl_usdt, start_equity,
                )
            if ntfy:
                await ntfy.send_daily_summary(
                    perf.total_trades, perf.winning_trades,
                    perf.total_pnl_usdt, start_equity,
                )
        except Exception as e:
            logger.error("Daily reset failed: %s", e)


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

    # Repopulate per-strategy one-per-day guards from the DB so ORB and Asia BO
    # don't re-fire on today's signal after a restart, even if their trade already
    # closed before the restart (slot guard only covers still-open positions).
    try:
        today_slots = await db.get_today_traded_slots(is_paper=config.exchange.paper_mode)
        if today_slots:
            today_utc = datetime.now(timezone.utc).date()
            for ctx in symbol_ctxs.values():
                if "orb" in today_slots and ctx.orb_strategy is not None:
                    ctx.orb_strategy._traded_dates.add(today_utc)
                    logger.info("Restored ORB traded-date for %s", ctx.symbol)
                if "asia_bo" in today_slots and ctx.asia_bo_strategy is not None:
                    ctx.asia_bo_strategy._traded_dates.add(today_utc)
                    logger.info("Restored Asia BO traded-date for %s", ctx.symbol)
    except Exception as e:
        logger.warning("Could not restore traded dates from DB: %s", e)

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

        # Stalled-feed detection: if any coin's primary-tf candle feed has not
        # advanced for well over one interval, the REST poll loop has silently
        # died — warn so we notice before trading on stale data.
        try:
            for sym, ctx in symbol_ctxs.items():
                stale = ctx.data_mgr.staleness_seconds()
                # Two missed intervals (plus poll slack) before alarming.
                tf_secs = TIMEFRAME_SECONDS.get(config.strategy.primary_tf, 60)
                if stale > max(tf_secs * 2, 180):
                    msg = (
                        f"⚠️ {sym} veri akışı {stale/60:.0f} dk durağan — "
                        f"besleme kopmuş olabilir"
                    )
                    logger.warning(msg)
                    if telegram:
                        await telegram.send_alert(msg, "WARNING")
                    if ntfy:
                        await ntfy.send_alert(msg, "WARNING")
        except Exception as e:
            logger.debug("Staleness check failed: %s", e)

        since_tg += interval
        if (telegram or ntfy) and since_tg >= tg_every:
            since_tg = 0
            try:
                bal = await exchange.get_balance()
                n_open = portfolio.get_open_position_count()
                upnl = portfolio.get_total_unrealized_pnl()
                msg = (
                    f"Bot çalışıyor · bakiye ${bal:,.2f} · açık {n_open} · "
                    f"gerçekleşmemiş ${upnl:+.2f}"
                )
                if telegram:
                    await telegram.send_alert(msg, "INFO")
                if ntfy:
                    await ntfy.send_alert(msg, "INFO")
            except Exception as e:
                logger.debug("Heartbeat notification failed: %s", e)
        await asyncio.sleep(interval)


async def position_reconciliation_loop() -> None:
    """Live-mode only: every 2 min, detect positions that were externally closed
    on MEXC (by SL/TP trigger orders) and sync the internal state.

    Without this, a trigger-order close leaves a ghost position in the bot's
    portfolio: equity is inflated by the locked margin, the daily-loss check
    sees a phantom unrealised loss, and the bot may try to open a duplicate
    trade into a coin that already has an active position on the exchange.
    """
    if config.exchange.paper_mode:
        return
    from collections import defaultdict
    # Small startup delay so the exchange client is fully warmed up.
    await asyncio.sleep(30)
    while True:
        try:
            # Group internal positions by symbol. MEXC nets all same-symbol
            # positions into ONE, so we compare the exchange's total contracts
            # for a symbol against the SUM of our internal sleeves on it — this
            # detects a single sleeve closing even while siblings stay open.
            by_symbol: dict[str, list] = defaultdict(list)
            for pos in portfolio.get_open_positions():
                by_symbol[pos.symbol].append(pos)

            for symbol, positions in by_symbol.items():
                try:
                    # Hold the per-symbol lock across the whole detect→close→resync
                    # sequence so a concurrent entry/close/trailing on this netted
                    # symbol can't interleave (read stale exchange state, or have
                    # its just-placed stop cancelled before we re-place siblings').
                    async with executor._symbol_lock(symbol):
                        mexc_pos = await exchange.get_position(symbol)
                        exch_qty = float(mexc_pos.contracts) if mexc_pos else 0.0
                        internal_qty = sum(p.quantity for p in positions)
                        tol = max(internal_qty * 0.01, 1e-9)
                        if exch_qty + tol >= internal_qty:
                            continue  # all sleeves still open on the exchange

                        # Some quantity closed externally. Close internal sleeves —
                        # the one whose SL/TP sits nearest the current price first —
                        # until our internal total matches the exchange again.
                        try:
                            current_price = await exchange.get_current_price(symbol)
                        except Exception:
                            current_price = positions[0].entry_price

                        def _proximity(p):
                            ds = []
                            if p.sl_price > 0:
                                ds.append(abs(current_price - p.sl_price))
                            if p.tp_price > 0:
                                ds.append(abs(current_price - p.tp_price))
                            return min(ds) if ds else float("inf")
                        positions.sort(key=_proximity)

                        to_close = internal_qty - exch_qty
                        for pos in positions:
                            if to_close <= tol:
                                break
                            if pos.side == "short":
                                sl_hit = pos.sl_price > 0 and current_price >= pos.sl_price * 0.99
                                tp_hit = pos.tp_price > 0 and current_price <= pos.tp_price * 1.01
                            else:
                                sl_hit = pos.sl_price > 0 and current_price <= pos.sl_price * 1.01
                                tp_hit = pos.tp_price > 0 and current_price >= pos.tp_price * 0.99
                            if sl_hit:
                                exit_price, reason = pos.sl_price, "sl_hit"
                            elif tp_hit:
                                exit_price, reason = pos.tp_price, "tp_hit"
                            else:
                                exit_price, reason = current_price, "external_close"

                            direction = pos.direction
                            entry_fee = pos.strategy_scores.get("entry_fee_rate", 0.0001)
                            raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
                            fees = (pos.entry_price * pos.quantity * entry_fee
                                    + exit_price * pos.quantity * 0.0001)
                            net_pnl = raw_pnl - fees

                            logger.warning(
                                "Reconciliation: %s %s externally closed on MEXC "
                                "(reason=%s exit=%.6f pnl=%.2f) — syncing state",
                                pos.side.upper(), symbol, reason, exit_price, net_pnl,
                            )
                            # _close_position_internal records the close, computes the
                            # authoritative net_pnl AND fires the notify callbacks, so
                            # we must NOT call on_position_closed again here (would
                            # double-notify and double-count the loss streak).
                            await executor._close_position_internal(pos, exit_price, reason)
                            to_close -= pos.quantity

                        # Clear the closed sleeve's leftover plan orders and re-assert
                        # any remaining sibling sleeves' stops on this netted symbol.
                        # We already hold the symbol lock, so call the locked variant
                        # directly (asyncio.Lock is not re-entrant).
                        await executor._resync_symbol_stops_locked(symbol)

                except Exception as e:
                    logger.error("Reconciliation check failed for %s: %s", symbol, e)
        except Exception as e:
            logger.error("Position reconciliation loop error: %s", e)
        await asyncio.sleep(120)  # recheck every 2 minutes


async def on_position_closed(pos, exit_price: float, net_pnl: float, reason: str) -> None:
    dashboard.add_trade(pos.side, pos.entry_price, exit_price, net_pnl, reason)
    # Return on deployed margin (net PnL ÷ margin = notional / leverage), matching
    # the percentage recorded in the DB — not raw price-move %.
    lev = max(config.exchange.leverage, 1)
    margin = pos.entry_price * pos.quantity / lev
    pnl_pct = (net_pnl / margin * 100) if margin > 0 else 0.0
    args = (pos.symbol, pos.side, pos.entry_price, exit_price, net_pnl, reason)
    if telegram:
        await telegram.send_trade_closed(*args, pnl_pct=pnl_pct)
    if ntfy:
        await ntfy.send_trade_closed(*args, pnl_pct=pnl_pct)


async def main() -> None:
    global exchange, executor, portfolio, dashboard
    global telegram, ntfy, web_dashboard, combiner, db, config
    global funding_monitor, orderflow_monitor, whale_monitor, symbol_ctxs

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
            fvg_strategy=(
                FvgStrategy(
                    min_gap_atr=config.strategy.fvg_min_gap_atr,
                    rr=config.strategy.fvg_rr,
                ) if config.strategy.fvg_enabled else None
            ),
            ifvg_strategy=(
                IfvgStrategy(
                    min_gap_atr=config.strategy.ifvg_min_gap_atr,
                    rr=config.strategy.ifvg_rr,
                ) if config.strategy.ifvg_enabled else None
            ),
            sr_breakout_strategy=(
                SrBreakoutStrategy()
                if config.strategy.sr_breakout_enabled
                and (
                    config.strategy.sr_breakout_symbols is None
                    or sym in config.strategy.sr_breakout_symbols
                )
                else None
            ),
            squeeze_strategy=(
                SqueezeStrategy(
                    kc_mult=config.strategy.squeeze_kc_mult,
                    min_squeeze_bars=config.strategy.squeeze_min_bars,
                    sl_atr=config.strategy.squeeze_sl_atr,
                    rr=config.strategy.squeeze_rr,
                    mtf_filter=config.strategy.squeeze_mtf,
                ) if config.strategy.squeeze_enabled else None
            ),
            whale_strategy=(
                WhaleStrategy(
                    z_threshold=config.strategy.whale_z_threshold,
                    sl_atr=config.strategy.whale_sl_atr,
                    rr=config.strategy.whale_rr,
                    min_body_atr=config.strategy.whale_min_body_atr,
                )
                if config.strategy.whale_enabled
                and (
                    config.strategy.whale_symbols is None
                    or sym in config.strategy.whale_symbols
                )
                else None
            ),
        )

    # Log the per-coin sleeve layout so the gate is visible at boot.
    for sym, ctx in symbol_ctxs.items():
        logger.info("[%s] active sleeves: %s", sym,
                    ", ".join(active_sleeves_for(ctx, config)))

    risk_mgr = RiskManager(config.risk)
    executor = ExecutionEngine(exchange, risk_mgr, portfolio, db, config)
    executor.register_close_callback(on_position_closed)

    async def _send_alert(message: str, level: str) -> None:
        if telegram:
            await telegram.send_alert(message, level)
        if ntfy:
            await ntfy.send_alert(message, level)
    executor.register_alert_callback(_send_alert)

    # Rebuild any open positions from before a restart (balance + positions).
    await restore_state()

    # Live: re-assert SL/TP for every restored position whose MEXC position is
    # still open. Plan orders expire after executeCycle (24h) and may also have
    # been cancelled while the bot was down — without this a restored position
    # could sit unprotected. Skip symbols MEXC no longer shows (the
    # reconciliation loop will close those ghosts shortly after startup).
    if not config.exchange.paper_mode:
        for sym in {p.symbol for p in portfolio.get_open_positions()}:
            try:
                if await exchange.get_position(sym) is not None:
                    await executor.resync_symbol_stops(sym)
                    logger.info("Re-asserted SL/TP for restored position(s) on %s", sym)
            except Exception as e:
                logger.error("Could not re-assert stops for %s on restart: %s", sym, e)

    balance = await exchange.get_balance()
    # Daily-loss baseline: if we already recorded today's starting equity, reuse
    # it so a mid-day restart (or a crash-loop) does NOT re-arm a fresh full
    # daily loss from a lower equity. Only snapshot fresh equity the first time
    # the bot starts on a given UTC day.
    today_iso = datetime.now(timezone.utc).date().isoformat()
    persisted_start = await db.get_daily_starting_balance(today_iso)
    if persisted_start is not None and persisted_start > 0:
        executor.set_daily_starting_balance(persisted_start)
        logger.info("Restored today's daily-loss baseline: %.2f", persisted_start)
    else:
        # Starting equity includes any restored positions' margin + unrealized PnL.
        await executor.capture_daily_start()
        await db.upsert_daily_stats(DailyStats(
            date=today_iso,
            starting_balance=await executor.current_equity(),
            ending_balance=await executor.current_equity(),
            total_trades=0, winning_trades=0, total_pnl_usdt=0.0,
            max_drawdown=0.0, is_paper=config.exchange.paper_mode,
        ))

    # Persist the inception balance on first run; use it consistently across
    # restarts so /status always shows return-since-day-one, not since-last-restart.
    inception_raw = await db.get_meta("inception_balance")
    if inception_raw is None:
        await db.set_meta("inception_balance", str(balance))
        inception_balance = balance
    else:
        inception_balance = float(inception_raw)

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

    # Whale-flow aggregator: one watchTrades feed on the primary (BTC) symbol,
    # buckets trades hourly to derive avg trade size live. Default OFF; monitor
    # mode logs would-be signals only. ~1 week warmup before the first z-score.
    whale_monitor = WhaleFlowMonitor(
        exchange,
        config.exchange.symbol,
        enabled=config.strategy.whale_enabled,
        zwin=config.strategy.whale_zwin,
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
        initial_balance=inception_balance,
    )
    await telegram.initialize()

    ntfy = NtfyNotifier(config.ntfy)
    await ntfy.initialize()

    # Bize-özel canlı web dashboard (botla aynı event loop, trading'e dokunmaz).
    sleeve_layout = {
        sym.split("/")[0]: active_sleeves_for(ctx, config)
        for sym, ctx in symbol_ctxs.items()
    }
    web_dashboard = WebDashboard(
        config.web,
        exchange=exchange,
        portfolio=portfolio,
        db=db,
        initial_balance=inception_balance,
        sleeve_layout=sleeve_layout,
        paper_mode=config.exchange.paper_mode,
        leverage=config.exchange.leverage,
    )
    await web_dashboard.start()

    # Wire each coin's candle-close handler and start its data feed.
    for sym, ctx in symbol_ctxs.items():
        ctx.data_mgr.subscribe_candle_close(
            config.strategy.primary_tf, make_on_candle_close(ctx)
        )

    _spawn_supervised(daily_reset_loop(), "daily_reset_loop")
    _spawn_supervised(heartbeat_loop(), "heartbeat_loop")
    _spawn_supervised(position_reconciliation_loop(), "position_reconciliation_loop")

    logger.info(
        "Bot running. Coins=%d TF=%s Balance=%.2f",
        len(symbol_ctxs), config.strategy.primary_tf, balance,
    )

    for ctx in symbol_ctxs.values():
        await ctx.data_mgr.start_feeds()

    # Start the order-flow feed (no-op if disabled).
    await orderflow_monitor.start()
    # Start the whale-flow aggregator (no-op if disabled).
    await whale_monitor.start()

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
    # Cancel the supervised background loops first so none of them fires a trade
    # or touches the exchange while we are tearing things down.
    for t in _bg_tasks:
        t.cancel()
    for t in _bg_tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    if orderflow_monitor is not None:
        await orderflow_monitor.stop()
    if whale_monitor is not None:
        await whale_monitor.stop()
    for ctx in symbol_ctxs.values():
        await ctx.data_mgr.stop()
    if telegram:
        await telegram.shutdown()
    if ntfy:
        await ntfy.shutdown()
    if web_dashboard:
        await web_dashboard.stop()
    await db.close()
    # Close the ccxt exchange session (LiveExchange holds an aiohttp client that
    # otherwise logs "Unclosed client session" and leaks the connection).
    if exchange is not None and hasattr(exchange, "close"):
        try:
            await exchange.close()
        except Exception as e:
            logger.debug("Exchange close failed: %s", e)
    if dashboard:
        dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())
