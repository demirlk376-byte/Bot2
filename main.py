from __future__ import annotations

import asyncio
import logging
import os
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
from strategies.donchian import DonchianStrategy, DonchianSignal
from strategies.fvg import FvgStrategy, FvgSignal
from strategies.ifvg import IfvgStrategy, IfvgSignal
from strategies.mean_reversion import MeanReversionStrategy
from strategies.orb import OrbStrategy, OrbSignal, ORB_HOUR
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
funding_monitors: dict[str, FundingMonitor] = {}  # symbol -> monitor
orderflow_monitors: dict[str, OrderFlowMonitor] = {}  # symbol -> collector
whale_monitor: WhaleFlowMonitor = None
symbol_ctxs: dict[str, "SymbolContext"] = {}
# Long-lived background loops, kept referenced so they can be cancelled on
# shutdown and so a crash is logged (a bare create_task() drops the reference
# and swallows the exception silently).
_bg_tasks: list[asyncio.Task] = []
_respawn_tasks: set[asyncio.Task] = set()
# Set once the notifiers are wired in main(); lets these module-level
# supervisors push a phone alert when a critical background loop dies.
_alert_hook = None


async def _emit_alert(message: str, level: str = "ERROR") -> None:
    if _alert_hook is not None:
        try:
            await _alert_hook(message, level)
        except Exception as e:
            logger.debug("alert hook failed: %s", e)


def _spawn_supervised(factory, name: str, *, restart: bool = False) -> asyncio.Task:
    """Start a background loop, keep a reference, and log loudly if it ever exits.

    `factory` may be a coroutine OR a zero-arg coroutine FUNCTION. Pass a
    FUNCTION with restart=True for loops critical to unattended safety
    (reconciliation, daily_reset, heartbeat): a crash is then ALERTED to the
    owner's phone AND the loop is auto-respawned after a short backoff, instead
    of being silently lost for the rest of the run (a dead reconciliation loop
    would let ghost positions and a stale daily-loss baseline go undetected)."""
    coro = factory() if callable(factory) else factory
    task = asyncio.create_task(coro, name=name)

    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.critical("Background task '%s' CRASHED: %r", name, exc)
        else:
            logger.error("Background task '%s' exited unexpectedly", name)
        if restart and callable(factory):
            rt = asyncio.create_task(_respawn_supervised(factory, name, exc))
            _respawn_tasks.add(rt)
            rt.add_done_callback(_respawn_tasks.discard)

    task.add_done_callback(_done)
    _bg_tasks.append(task)
    return task


async def _respawn_supervised(factory, name: str, exc) -> None:
    """Alert the owner and restart a critical background loop after a short
    backoff so a tight crash-loop can't hammer the exchange."""
    try:
        await _emit_alert(
            f"⚠️ Arka plan görevi '{name}' çöktü ({exc!r}) — 5 sn sonra "
            f"yeniden başlatılıyor.",
            "ERROR",
        )
        await asyncio.sleep(5)
        logger.warning("Respawning background task '%s'", name)
        _spawn_supervised(factory, name, restart=True)
    except Exception as e:
        logger.critical("Failed to respawn background task '%s': %s", name, e)


@dataclass
class OrbArmed:
    """A primed ORB stop-entry watch for one symbol on one calendar day. The
    ticker loop checks `price` against the boundaries each tick and fires a market
    order the instant either is crossed (matching the validated stop-touch model)."""
    trade_date: date
    orb_high: float
    orb_low: float
    orb_range: float
    atr: float


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
    donchian_strategy: DonchianStrategy = None
    # Live ORB stop-entry: armed once per day after the 14:00 UTC range candle,
    # consumed by the tick-watcher. None = not armed.
    orb_armed: "OrbArmed | None" = None
    _orb_firing: bool = False   # re-entrancy guard while a fire is in flight
    # Open-timestamp of the last 4h bar the Donchian sleeve analyzed — prevents
    # re-analyzing (and re-firing a market order on) the same/stale 4h bar.
    donchian_last_4h: object = None


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
    if ctx.donchian_strategy is not None: sleeves.append("Donch")
    if ctx.whale_strategy is not None:
        whale_mode = getattr(cfg.strategy, "whale_mode", "monitor")
        sleeves.append("Whale" + ("" if whale_mode == "trade" else "(mon)"))
    return sleeves


def make_on_candle_close(ctx: "SymbolContext"):
    """Build a candle-close handler bound to one coin's context."""

    async def on_candle_close(candle: Candle) -> None:
        try:
            import pandas as pd
            import numpy as np

            df = await ctx.data_mgr.get_candles(config.strategy.primary_tf, 120)
            if len(df) < config.strategy.bb_period + 5:
                return

            current_price = await ctx.data_mgr.get_current_price()
            # Per-coin price: a shared single price would be wrong across coins.
            # Push THIS coin's fresh price into the (shared) exchange before any
            # fill so a paper order can never fill at another coin's last price
            # via the _current_price fallback (audit v3 #9).
            if hasattr(exchange, "update_price"):
                await exchange.update_price(current_price, ctx.symbol)
            portfolio.update_unrealized_pnl_for(ctx.symbol, current_price)
            dashboard.update_price(current_price, ctx.symbol)

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
            # Use a neutral 20.0 fallback for NaN AND inf: a perfectly flat range
            # (TR=0) makes the DI ratio non-finite, which would otherwise mis-route
            # the regime (e.g. treat a dead market as "trending").
            adx_val = float(adx_raw) if np.isfinite(adx_raw) else 20.0
            regime = _get_regime(adx_val)
            dashboard.update_regime(regime, adx_val)
            web_dashboard.update_regime(regime, adx_val, ctx.symbol)

            # Trailing stop: update SL positions BEFORE the SL/TP check would fire
            # on this candle's high/low, but AFTER PaperExchange.check_sl_tp already
            # ran above — so the moved SL only affects the NEXT candle's SL check.
            await _update_trailing_stops(ctx.symbol, current_price, atr_val)

            # Stale-feed guard: exits/trailing above always run (they protect open
            # positions), but do NOT open NEW entries on a stale feed. Normally the
            # triggering candle is fresh (~0 staleness); this catches a replayed or
            # clock-skewed candle after an outage so we never enter on old data.
            tf_secs = TIMEFRAME_SECONDS.get(config.strategy.primary_tf, 3600)
            if (ctx.data_mgr.staleness_seconds() > tf_secs * 2
                    or ctx.data_mgr.price_age_seconds() > tf_secs * 2):
                logger.warning(
                    "[%s] Feed stale (%.0fs) — skipping new entries this candle",
                    ctx.symbol, ctx.data_mgr.staleness_seconds())
                return

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

            try:
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
                # Per-symbol monitor: each coin's OWN funding gates/annotates its
                # signal — BTC funding must never speak for SOL.
                _fund_mon = funding_monitors.get(ctx.symbol)
                if (
                    bb_combined.direction != 0
                    and _fund_mon is not None
                    and _fund_mon.enabled
                ):
                    snap = await _fund_mon.fetch()
                    assess = _fund_mon.evaluate(bb_combined.direction, snap)
                    logger.info("Funding read: %s -> bias=%.2f", assess.reason, assess.bias)
                    dashboard.log_message(f"Funding: {assess.reason}")
                    _log_funding_csv(ctx.symbol, bb_combined, mr_sig, snap, assess)
                    if _fund_mon.mode == "filter" and assess.should_skip:
                        dashboard.log_message(
                            f"BB signal SKIPPED by funding filter ({assess.reason})"
                        )
                        logger.info("BB skipped: funding contrary+extreme (%s)", assess.reason)
                        bb_combined.direction = 0
                    elif _fund_mon.mode == "boost":
                        bb_combined.confidence = min(bb_combined.confidence * assess.bias, 1.0)

                _of_mon = orderflow_monitors.get(ctx.symbol)
                if (
                    bb_combined.direction != 0
                    and _of_mon is not None
                    and _of_mon.enabled
                ):
                    try:
                        of_snap = await _of_mon.snapshot()
                        of_assess = _of_mon.evaluate(bb_combined.direction, of_snap)
                        logger.info("OrderFlow: %s", of_assess.reason)
                        dashboard.log_message(f"OrderFlow: {of_assess.reason}")
                        _log_orderflow_csv(ctx.symbol, bb_combined, mr_sig, of_snap, of_assess)
                    except Exception as e:
                        logger.debug("OrderFlow snapshot failed: %s", e)

                if bb_combined.direction != 0 and not bb_allowed:
                    logger.warning(
                        "[%s] BB skipped: regime=%s is_weekend=%s", ctx.symbol, regime, is_weekend
                    )
                    web_dashboard.add_signal(ctx.symbol, "BB", bb_combined.direction,
                                             mr_sig.reason, f"block:rejim={regime}")
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
                        web_dashboard.add_signal(ctx.symbol, "BB", bb_combined.direction,
                                                 mr_sig.reason, "exec")
                        if telegram:
                            await telegram.send_trade_opened(result.trade_setup, bb_combined)
                        if ntfy:
                            await ntfy.send_trade_opened(result.trade_setup, bb_combined)
                    elif result.error:
                        logger.warning("[%s] BB skipped: %s", ctx.symbol, result.error)
                        web_dashboard.add_signal(ctx.symbol, "BB", bb_combined.direction,
                                                 mr_sig.reason, f"block:{result.error}")
                else:
                    # direction=0: strategy didn't generate a signal
                    web_dashboard.add_signal(ctx.symbol, "BB", 0, mr_sig.reason)
            except Exception as _se:
                logger.error("[%s] BB sleeve error: %s", ctx.symbol, _se)

            try:
                # ── ORB — independent slot, NY open range breakout ────────────────
                # Two entry modes (default: limit-retrace, ORB_STOP_ENTRY=false):
                #   stop-entry: tick-watcher fires a MARKET order the instant price
                #     touches the range boundary. Won its first 30-day window
                #     (PF 1.65 vs 1.41) but REVERSED the next period (PF 0.87 vs
                #     1.42) — regime-sensitive, so it is opt-in, not default.
                #     Entries fire in make_on_orb_tick(), not here.
                #   limit-retrace (default): candle-close entry — the more robust
                #     two-period performer.
                if ctx.orb_strategy is not None and config.strategy.orb_stop_entry:
                    await _maybe_arm_orb(ctx, df, atr_val)
                    armed = ctx.orb_armed is not None
                    web_dashboard.add_signal(
                        ctx.symbol, "ORB", 0,
                        "stop-entry armed (tick-watch)" if armed else "ORB range not set",
                    )
                elif ctx.orb_strategy is not None and bo_allowed:
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
                            web_dashboard.add_signal(ctx.symbol, "ORB", orb_sig.direction,
                                                     orb_sig.reason, "exec")
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, orb_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, orb_combined)
                        elif result.error:
                            logger.warning("[%s] ORB skipped: %s", ctx.symbol, result.error)
                            web_dashboard.add_signal(ctx.symbol, "ORB", orb_sig.direction,
                                                     orb_sig.reason, f"block:{result.error}")
                    else:
                        web_dashboard.add_signal(ctx.symbol, "ORB", 0, orb_sig.reason)
                elif ctx.orb_strategy is not None:
                    web_dashboard.add_signal(ctx.symbol, "ORB", 0, f"block:rejim={regime}")
            except Exception as _se:
                logger.error("[%s] ORB sleeve error: %s", ctx.symbol, _se)

            try:
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
                            web_dashboard.add_signal(ctx.symbol, "Asia", asia_sig.direction,
                                                     asia_sig.reason, "exec")
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, asia_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, asia_combined)
                        elif result.error:
                            logger.warning("[%s] Asia BO skipped: %s", ctx.symbol, result.error)
                            web_dashboard.add_signal(ctx.symbol, "Asia", asia_sig.direction,
                                                     asia_sig.reason, f"block:{result.error}")
                    else:
                        web_dashboard.add_signal(ctx.symbol, "Asia", 0, asia_sig.reason)
                elif ctx.asia_bo_strategy is not None:
                    web_dashboard.add_signal(ctx.symbol, "Asia", 0, f"block:rejim={regime}")
            except Exception as _se:
                logger.error("[%s] Asia sleeve error: %s", ctx.symbol, _se)

            try:
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
                            # Conformance (audit 2026-07-16): research_sr fills AT
                            # THE BREAKOUT CLOSE (entry=cur, taker both legs) and
                            # anchors SL/TP to that close via ATR — NOT to the
                            # pivot level. A market fill therefore keeps R/R; the
                            # former limit+no-fallback path skipped every breakout
                            # that didn't retrace (adverse selection on a momentum
                            # sleeve). Same treatment as Donchian/Squeeze.
                            force_market=True,
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
                            web_dashboard.add_signal(ctx.symbol, "S/R", sr_sig.direction,
                                                     sr_sig.reason, "exec")
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, sr_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, sr_combined)
                        elif result.error:
                            logger.warning("[%s] S/R skipped: %s", ctx.symbol, result.error)
                            web_dashboard.add_signal(ctx.symbol, "S/R", sr_sig.direction,
                                                     sr_sig.reason, f"block:{result.error}")
            except Exception as _se:
                logger.error("[%s] S/R sleeve error: %s", ctx.symbol, _se)

            try:
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
                            web_dashboard.add_signal(ctx.symbol, "FVG", fvg_sig.direction,
                                                     fvg_sig.reason, "exec")
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, fvg_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, fvg_combined)
                        elif result.error:
                            logger.warning("[%s] FVG skipped: %s", ctx.symbol, result.error)
                            web_dashboard.add_signal(ctx.symbol, "FVG", fvg_sig.direction,
                                                     fvg_sig.reason, f"block:{result.error}")
                    else:
                        web_dashboard.add_signal(ctx.symbol, "FVG", 0, fvg_sig.reason)
            except Exception as _se:
                logger.error("[%s] FVG sleeve error: %s", ctx.symbol, _se)

            try:
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
                            web_dashboard.add_signal(ctx.symbol, "IFVG", ifvg_sig.direction,
                                                     ifvg_sig.reason, "exec")
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, ifvg_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, ifvg_combined)
                        elif result.error:
                            logger.warning("[%s] IFVG skipped: %s", ctx.symbol, result.error)
                            web_dashboard.add_signal(ctx.symbol, "IFVG", ifvg_sig.direction,
                                                     ifvg_sig.reason, f"block:{result.error}")
            except Exception as _se:
                logger.error("[%s] IFVG sleeve error: %s", ctx.symbol, _se)

            try:
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
                            # Conformance (audit 2026-07-16): the validated model
                            # (research_squeeze) fills AT THE RELEASE CLOSE with
                            # taker fees on both legs — a guaranteed fill. SL/TP are
                            # ATR-anchored to that close (not to a structure level),
                            # so a market fill keeps R/R intact. The former
                            # limit+no-fallback path adversely selected: runaway
                            # (strongest) releases never retraced and were skipped,
                            # fading ones filled. Same treatment as Donchian.
                            force_market=True,
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
                            web_dashboard.add_signal(ctx.symbol, "Squeeze", sq_sig.direction,
                                                     sq_sig.reason, "exec")
                            if telegram:
                                await telegram.send_trade_opened(result.trade_setup, sq_combined)
                            if ntfy:
                                await ntfy.send_trade_opened(result.trade_setup, sq_combined)
                        elif result.error:
                            logger.warning("[%s] Squeeze skipped: %s", ctx.symbol, result.error)
                            web_dashboard.add_signal(ctx.symbol, "Squeeze", sq_sig.direction,
                                                     sq_sig.reason, f"block:{result.error}")
                    else:
                        logger.debug("[%s] squeeze: %s", ctx.symbol, sq_sig.reason)
                        web_dashboard.add_signal(ctx.symbol, "Squeeze", 0, sq_sig.reason)
                elif ctx.squeeze_strategy is not None:
                    web_dashboard.add_signal(ctx.symbol, "Squeeze", 0, f"block:rejim={regime}")
            except Exception as _se:
                logger.error("[%s] Squeeze sleeve error: %s", ctx.symbol, _se)

            try:
                # ── Donchian — 4h channel swing breakout (HTF, 1-5 day holds) ─────
                # Runs on the 4h buffer, only when a 4h candle just closed (the
                # just-closed 1h candle is the last hour of a 4h period: UTC hour%4==3).
                # NOT regime-gated — its own EMA200 trend filter is the regime filter
                # (matches the validated backtest). force_market: taker fill ~close,
                # exactly the close-confirmed entry that was validated.
                if ctx.donchian_strategy is not None and (df.index[-1].hour % 4 == 3):
                    df_4h = await ctx.data_mgr.get_candles(config.strategy.confirm_tf, 260)
                    # FRESHNESS (audit fix): the 4h buffer is filled by an
                    # INDEPENDENT 30s REST poll task with its own phase — at the
                    # boundary there is roughly a coin-flip chance it has not yet
                    # fetched the just-closed 4h bar. Analyzing the stale buffer
                    # silently drops fresh breakouts (and can re-fire a 4h-old
                    # one). The just-closed 1h bar opens at hour%4==3, so the
                    # just-closed 4h bar's open is exactly 3h earlier. If the
                    # buffer is behind, force one synchronous poll; if it is
                    # STILL behind (fetch failed), skip — never analyze stale.
                    expected_4h_open = df.index[-1] - pd.Timedelta(hours=3)
                    if df_4h is None or not len(df_4h) or df_4h.index[-1] != expected_4h_open:
                        try:
                            await ctx.data_mgr._poll_once(config.strategy.confirm_tf)
                        except Exception as e:
                            logger.warning("[%s] donchian 4h force-poll failed: %s",
                                           ctx.symbol, e)
                        df_4h = await ctx.data_mgr.get_candles(config.strategy.confirm_tf, 260)
                    dch_min = max(config.strategy.donchian_channel + 2,
                                  config.strategy.donchian_ema_trend)
                    if (df_4h is None or not len(df_4h)
                            or df_4h.index[-1] != expected_4h_open):
                        logger.warning(
                            "[%s] donchian skipped: 4h buffer stale (have %s, want %s)",
                            ctx.symbol,
                            None if df_4h is None or not len(df_4h) else df_4h.index[-1],
                            expected_4h_open)
                    elif df_4h.index[-1] == ctx.donchian_last_4h:
                        logger.debug("[%s] donchian: 4h bar %s already analyzed",
                                     ctx.symbol, ctx.donchian_last_4h)
                    elif len(df_4h) >= dch_min:
                        ctx.donchian_last_4h = df_4h.index[-1]
                        atr_4h = atr(df_4h["high"], df_4h["low"], df_4h["close"],
                                     config.strategy.atr_period).iloc[-1]
                        if not (pd.isna(atr_4h) or atr_4h <= 0):
                            dch_sig = ctx.donchian_strategy.analyze(df_4h, float(atr_4h))
                            if dch_sig.direction != 0 and not _donchian_mtf_ok(
                                    df_4h, dch_sig.direction):
                                logger.info("[%s] Donchian MTF: günlük trend ters "
                                            "(dir=%d), atlandı", ctx.symbol, dch_sig.direction)
                                web_dashboard.add_signal(ctx.symbol, "Donch", 0,
                                                         "MTF: günlük trend ters")
                            elif dch_sig.direction != 0:
                                dch_combined = CombinedSignal(
                                    direction=dch_sig.direction,
                                    confidence=dch_sig.strength,
                                    trend_score=0.0,
                                    mean_rev_score=0.0,
                                    breakout_score=dch_sig.direction * dch_sig.strength,
                                    dominant_strategy="donchian",
                                    reasons=[dch_sig.reason],
                                    entry_price=dch_sig.entry_price,
                                    sl_price=dch_sig.sl_price,
                                    tp_price=dch_sig.tp_price,
                                    symbol=ctx.symbol,
                                    position_slot=f"{ctx.symbol}:donchian",
                                    # DENEY BAYRAĞI (varsayılan KAPALI, .env ile açılır).
                                    # Kapalıyken force_market=True → bugünkü davranış
                                    # BİT BİT AYNI. Açıkken maker limit + 45sn PİYASA
                                    # YEDEĞİ: hiçbir işlem kaçmaz, sadece ödenen fiyat
                                    # değişir. anchor_is_level=False olmasa yedeksiz yola
                                    # düşerdi — 2026-07-16'da geri alınan felaket buydu.
                                    force_market=not config.exchange.donchian_maker_entry,
                                    anchor_is_level=False,
                                )
                                result = await executor.execute_signal(dch_combined, float(atr_4h))
                                if result.success and result.position:
                                    logger.info(
                                        "DONCHIAN trade opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                                        result.position.side.upper(), ctx.symbol,
                                        result.position.entry_price,
                                        result.position.sl_price,
                                        result.position.tp_price,
                                    )
                                    web_dashboard.add_signal(ctx.symbol, "Donch", dch_sig.direction,
                                                             dch_sig.reason, "exec")
                                    if telegram:
                                        await telegram.send_trade_opened(result.trade_setup, dch_combined)
                                    if ntfy:
                                        await ntfy.send_trade_opened(result.trade_setup, dch_combined)
                                elif result.error:
                                    logger.warning("[%s] Donchian skipped: %s", ctx.symbol, result.error)
                                    web_dashboard.add_signal(ctx.symbol, "Donch", dch_sig.direction,
                                                             dch_sig.reason, f"block:{result.error}")
                            else:
                                web_dashboard.add_signal(ctx.symbol, "Donch", 0, dch_sig.reason)
            except Exception as _se:
                logger.error("[%s] Donchian sleeve error: %s", ctx.symbol, _se)

            try:
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
                                logger.warning("[%s] WHALE skipped: %s", ctx.symbol, result.error)
                    elif z is not None:
                        logger.debug("[%s] whale z=%.2f (no fire)", ctx.symbol, z)
            except Exception as _se:
                logger.error("[%s] Whale sleeve error: %s", ctx.symbol, _se)

            balance = await exchange.get_balance()
            dashboard.update_balance(balance)

        except Exception as e:
            logger.error("[%s] on_candle_close error: %s", ctx.symbol, e, exc_info=True)

    return on_candle_close


async def _maybe_arm_orb(ctx: "SymbolContext", df, atr_val: float) -> None:
    """Prime the ORB stop-entry watch once per day, after today's 14:00 UTC range
    candle is in the buffer (i.e. from 15:00 UTC). Idempotent: re-arming the same
    day is a no-op, and a day already traded stays disarmed. Runs every candle
    close so a mid-day restart re-arms on the next close (restart-safe)."""
    import pandas as pd
    if ctx.orb_strategy is None:
        return
    today = datetime.now(timezone.utc).date()
    # Already traded this sleeve today → never re-arm (one trade/day, matches
    # the backtest and the strategy's own _traded_dates guard).
    if today in ctx.orb_strategy._traded_dates:
        ctx.orb_armed = None
        return
    # Already armed for today → keep the existing range (don't recompute/clobber).
    if ctx.orb_armed is not None and ctx.orb_armed.trade_date == today:
        return
    # Locate today's 14:00 UTC range candle. Index is tz-naive UTC (ms epoch),
    # matching OrbStrategy.analyze()'s own hour/date masking.
    idx = pd.to_datetime(df.index)
    mask = (idx.date == today) & (idx.hour == ORB_HOUR)
    rng = df[mask]
    if rng.empty:
        return  # before 15:00 UTC, or range candle not yet in buffer
    orb_high = float(rng["high"].max())
    orb_low = float(rng["low"].min())
    orb_range = orb_high - orb_low
    if orb_range <= 0:
        return
    ctx.orb_armed = OrbArmed(
        trade_date=today, orb_high=orb_high, orb_low=orb_low,
        orb_range=orb_range, atr=float(atr_val),
    )
    logger.info(
        "[%s] ORB armed (stop-entry): range %.4f–%.4f (size %.4f)",
        ctx.symbol, orb_low, orb_high, orb_range,
    )


def make_on_orb_tick(ctx: "SymbolContext"):
    """Build a tick handler that fires an ORB stop-entry the instant price crosses
    the armed range boundary. Reuses executor.execute_signal so every safety check
    (daily-loss halt, cooldown, slot guard, margin, live SL/TP verify) still applies.
    Entry is a MARKET order at ~level (force_market) → R/R stays ~2.0."""

    async def on_orb_tick(symbol: str, price: float) -> None:
        armed = ctx.orb_armed
        if armed is None or ctx._orb_firing:
            return
        today = datetime.now(timezone.utc).date()
        if armed.trade_date != today:
            ctx.orb_armed = None
            return

        if price >= armed.orb_high:
            direction, level = 1, armed.orb_high
            sl_price = armed.orb_low
            tp_price = armed.orb_high + 2.0 * armed.orb_range
        elif price <= armed.orb_low:
            direction, level = -1, armed.orb_low
            sl_price = armed.orb_high
            tp_price = armed.orb_low - 2.0 * armed.orb_range
        else:
            return  # still inside the range

        # Disarm + lock BEFORE awaiting so a burst of ticks can't double-fire.
        ctx._orb_firing = True
        ctx.orb_armed = None
        # Burn the day immediately (matches OrbStrategy.analyze, which records the
        # date on signal generation regardless of execution outcome).
        ctx.orb_strategy._traded_dates.add(today)
        try:
            reason = (
                f"ORB stop-entry: {price:.4f} crossed "
                f"{'high' if direction == 1 else 'low'} {level:.4f} "
                f"(range {armed.orb_low:.4f}–{armed.orb_high:.4f})"
            )
            orb_combined = CombinedSignal(
                direction=direction,
                confidence=0.80,
                trend_score=0.0,
                mean_rev_score=0.0,
                breakout_score=direction * 0.80,
                dominant_strategy="orb",
                reasons=[reason],
                entry_price=level,        # SL/TP anchored to the level
                sl_price=sl_price,
                tp_price=tp_price,
                symbol=ctx.symbol,
                position_slot=f"{ctx.symbol}:orb",
                force_market=True,        # take the breakout now, at ~level
            )
            result = await executor.execute_signal(orb_combined, armed.atr)
            if result.success and result.position:
                logger.info(
                    "ORB stop-entry opened: %s %s entry=%.4f sl=%.4f tp=%.4f",
                    result.position.side.upper(), ctx.symbol,
                    result.position.entry_price,
                    result.position.sl_price, result.position.tp_price,
                )
                web_dashboard.add_signal(ctx.symbol, "ORB", direction, reason, "exec")
                if telegram:
                    await telegram.send_trade_opened(result.trade_setup, orb_combined)
                if ntfy:
                    await ntfy.send_trade_opened(result.trade_setup, orb_combined)
            elif result.error:
                logger.warning("[%s] ORB stop-entry skipped: %s", ctx.symbol, result.error)
                web_dashboard.add_signal(ctx.symbol, "ORB", direction, reason,
                                         f"block:{result.error}")
        except Exception as e:
            logger.error("[%s] ORB tick fire error: %s", ctx.symbol, e, exc_info=True)
        finally:
            ctx._orb_firing = False

    return on_orb_tick


_FUNDING_CSV = "funding_log.csv"


def _log_funding_csv(symbol, combined, mr_sig, snap, assess) -> None:
    """Append every BB-signal funding/OI read to a CSV — the forward dataset
    that decides (at a pre-registered n) whether the funding filter earns its
    way into live. Mirrors _log_orderflow_csv; snap can be None on API misses."""
    import csv
    from pathlib import Path
    header = ["ts", "symbol", "direction", "bb_pos", "confidence",
              "funding_rate", "open_interest", "aligned", "contrary",
              "extreme", "oi_falling", "bias"]
    row = [
        datetime.now(timezone.utc).isoformat(), symbol, combined.direction,
        round(getattr(mr_sig, "bb_pos", 0.0), 4), round(combined.confidence, 4),
        (snap.funding_rate if snap else ""),
        (snap.open_interest if snap else ""),
        int(assess.aligned), int(assess.contrary),
        int(assess.extreme), int(assess.oi_falling), round(assess.bias, 4),
    ]
    try:
        exists = Path(_FUNDING_CSV).exists()
        with open(_FUNDING_CSV, "a", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(header)
            w.writerow(row)
    except Exception as e:
        logger.debug("funding csv write failed: %s", e)


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


def _donchian_mtf_ok(df_4h, direction: int) -> bool:
    """Donchian MTF filtresi (DONCHIAN_MTF): giriş yönü günlük EMA20 trendiyle
    hizalı mı? Kapalıysa her zaman True (davranış değişmez). df_4h (~260 4h bar ≈
    43 gün) → günlük resample → EMA20. Backtest doğrulanmış: rr2.5 üstünde +$42,
    PF1.49→1.53, her yıl≥ baseline; ters-günlük-trend breakout'ları eler."""
    if not getattr(config.strategy, "donchian_mtf_enabled", False):
        return True
    try:
        d1d = df_4h.resample("1D").agg({"close": "last"}).dropna()
        if len(d1d) < 20:
            return True   # yeterli günlük veri yoksa filtreleme (güvenli taraf)
        dema20 = d1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        daily_up = float(d1d["close"].iloc[-1]) > float(dema20)
        return (direction == 1 and daily_up) or (direction == -1 and not daily_up)
    except Exception:
        return True   # hata olursa filtreleme (mevcut davranış)


async def _update_trailing_stops(symbol: str, current_price: float, atr_val: float) -> None:
    """Each candle: update the SL of positions whose sleeve has a VALIDATED
    stop-move edge. ONE model survives validation:
      • orb / ifvg: BE-ONLY at +1R (R = entry→initial-SL distance). No trailing,
        no partial TP — exactly the model the exit research validated.
    BB mean-reversion and FVG are excluded — the retracement that would move SL
    to breakeven is part of their normal path to TP (BE measurably hurts them).
    sr_breakout is ALSO excluded (2026-07-13 conformance audit): its validated
    +22.4%/PF 1.72 was FIXED SL=3×ATR/TP=3R — the BE@1ATR+2ATR-trail it used to
    get live was never backtested, and a 12-month 1m-intrabar test with the
    production signal class showed trailing guts it: fixed PF 1.80 / +23.4R vs
    trailed PF 1.39 / +7.1R (DD worse too). Fixed stops let the 3R winner run.

    EXIT-MODEL EVIDENCE (scratch_exits test, BTC 1m intrabar, 2025-05..2026-04):
    vs fixed SL/TP — BE@1R: ORB +5.5R / IFVG +3.0R (DD down), FVG -3.1R;
    trailing(1.5R): ORB +4.5R / IFVG +3.1R; TP1/TP2 partial: WORSE on every
    sleeve (raises WR, cuts total — rejected). ~+3-4% uplift, small but real;
    single-regime sample — re-verify on longer data when 2023/24 1m is around.

    LIVE GATING: a mid-life stop move needs MEXC's plan-order endpoint, which
    has a history of silent rejects. Moves are therefore applied on live ONLY
    when STOP_MOVE_ENABLED=true (set it after check_mexc_stopmove.py reports
    the endpoint healthy). The move itself is fail-safe: LiveExchange.
    move_stop_loss places the new stop and confirms it rests BEFORE cancelling
    the old one, and internal state (sl_price / breakeven_moved) is committed
    only after the exchange confirms — a failed move changes nothing and is
    simply retried on the next candle."""
    if not getattr(config.risk, "trailing_stop_enabled", True):
        return

    live_moves_ok = config.exchange.stop_move_enabled

    for pos in portfolio.get_open_positions():
        if pos.symbol != symbol:
            continue

        # Sleeves NOT listed here were validated with fixed SL/TP + max-hold;
        # moving their stops would diverge live behaviour from the backtest.
        # (sr_breakout deliberately absent — see docstring.)
        strategy_tag = pos.strategy_scores.get("strategy", "mean_rev")
        if strategy_tag not in ("orb", "ifvg"):
            continue

        old_sl = pos.sl_price
        new_sl = old_sl
        be_now = False   # committed to pos.breakeven_moved only after a real move

        # orb / ifvg: BE-only at +1R. After BE there is nothing further to do.
        if pos.breakeven_moved:
            continue
        r_dist = abs(pos.entry_price - pos.sl_price)  # pre-BE ⇒ initial R
        if r_dist <= 0:
            continue
        if pos.direction == 1 and current_price >= pos.entry_price + r_dist:
            new_sl = max(new_sl, pos.entry_price)
            be_now = True
        elif pos.direction == -1 and current_price <= pos.entry_price - r_dist:
            new_sl = min(new_sl, pos.entry_price)
            be_now = True

        if new_sl != old_sl:
            if isinstance(exchange, PaperExchange):
                pos.sl_price = new_sl
                if be_now:
                    pos.breakeven_moved = True
                if hasattr(exchange, "update_position_sl"):
                    exchange.update_position_sl(pos.id, new_sl)
                # Persist so a restart re-arms at the MOVED stop (audit v2).
                try:
                    await db.update_trade_sl(pos.id, new_sl)
                except Exception as pe:
                    logger.debug("BE persist failed for %s: %s", pos.id[:8], pe)
            elif not live_moves_ok:
                # Live with stop-move disabled: keep the original exchange-side
                # SL/TP (still protective, matches the fixed-stop backtest) and
                # keep internal state in sync with the REAL exchange stop.
                logger.info(
                    "[%s] Stop move suppressed on live (STOP_MOVE_ENABLED=false) — "
                    "keeping exchange SL %.4f", symbol, old_sl,
                )
                continue
            else:
                pos_side = "long" if pos.direction == 1 else "short"
                try:
                    # Per-symbol lock (audit v2): without it the BE move can
                    # interleave with reconciliation booking an external close
                    # on the same symbol — the fallback path would then place a
                    # stray reduce-only trigger for a position that no longer
                    # exists. The executor's lock serializes all of these.
                    async with executor._symbol_lock(pos.symbol):
                        moved = await exchange.move_stop_loss(
                            pos.symbol, pos_side, new_sl, pos.quantity)
                except Exception as e:
                    logger.warning("[%s] move_stop_loss error: %s", symbol, e)
                    moved = False
                if not moved:
                    # Exchange stop unchanged — leave internal state unchanged
                    # too; the same move is recomputed and retried next candle.
                    continue
                pos.sl_price = new_sl
                if be_now:
                    pos.breakeven_moved = True
                # Persist so a restart's restore+resync re-arms the exchange
                # stop at the BE price instead of the stale entry SL (audit v2).
                try:
                    await db.update_trade_sl(pos.id, new_sl)
                except Exception as pe:
                    logger.debug("BE persist failed for %s: %s", pos.id[:8], pe)
            action = "BE" if be_now and new_sl == pos.entry_price else "Trail"
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
            # Keep yesterday's baseline BEFORE re-capturing — needed below for
            # the books-vs-bank reconciliation of the day that just ended.
            prev_baseline = executor.get_daily_starting_balance()
            # Snapshot starting EQUITY (free + locked margin + unrealized), not
            # free balance — the daily-loss limit measures drawdown, not margin.
            await executor.capture_daily_start()
            executor.reset_daily()
            # Persist the EQUITY baseline (matches the daily-loss limit's measure
            # and what the startup path reads back after a restart).
            # Use the baseline capture_daily_start just validated (it keeps the
            # prior value if equity was unreadable) rather than re-reading equity,
            # which can return None on a transient failure.
            start_equity = executor.get_daily_starting_balance()

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

            # Daily summary must report the DAY THAT JUST ENDED, not all-time
            # cumulative totals (which would look like "today" forever). We run
            # just after midnight UTC, so the ended day is yesterday.
            yesterday = (datetime.now(timezone.utc).date()
                         - timedelta(days=1)).isoformat()
            d_trades, d_wins, d_pnl = await db.get_daily_trade_stats(
                yesterday, is_paper=config.exchange.paper_mode)

            # Books-vs-bank reconciliation (audit safety net): the exchange
            # equity change over the ended day should ≈ the DB's realized PnL.
            # A persistent residual means untracked costs (funding, fee-rate
            # drift, missed partial closes) — any future accounting bug
            # surfaces here within a day instead of silently skewing PF.
            # Deposits/withdrawals and open-position unrealized swings also
            # land in the residual, hence alert (not halt) + generous threshold.
            if prev_baseline > 0 and start_equity > 0:
                drift = (start_equity - prev_baseline) - d_pnl
                threshold = max(1.0, 0.02 * prev_baseline)
                if abs(drift) > threshold:
                    await _emit_alert(
                        f"📒 Defter-banka farkı: dün equity {prev_baseline:.2f}→"
                        f"{start_equity:.2f} (Δ{start_equity - prev_baseline:+.2f}) "
                        f"ama DB PnL {d_pnl:+.2f} → fark {drift:+.2f} USDT. "
                        "Para yatırdıysan/çektiysen normaldir; aksi halde funding/"
                        "fee kayması veya kaçık kapanış olabilir — live_report ile bak.",
                        "WARNING",
                    )

            if telegram:
                await telegram.send_daily_summary(
                    d_trades, d_wins, d_pnl, start_equity,
                )
            if ntfy:
                await ntfy.send_daily_summary(
                    d_trades, d_wins, d_pnl, start_equity,
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

    open_trades = await db.get_open_trades(is_paper=config.exchange.paper_mode)
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
                # Per-symbol: only restore the guard for the coin that actually
                # traded that sleeve today, so BTC's ORB doesn't block ETH's ORB.
                if (ctx.symbol, "orb") in today_slots and ctx.orb_strategy is not None:
                    ctx.orb_strategy._traded_dates.add(today_utc)
                    logger.info("Restored ORB traded-date for %s", ctx.symbol)
                if (ctx.symbol, "asia_bo") in today_slots and ctx.asia_bo_strategy is not None:
                    ctx.asia_bo_strategy._traded_dates.add(today_utc)
                    logger.info("Restored Asia BO traded-date for %s", ctx.symbol)
    except Exception as e:
        logger.warning("Could not restore traded dates from DB: %s", e)

    return restored


async def sermaye_guncelle() -> None:
    """Yatırılan sermayeyi BORSADAN oku ve `sermaye_taban` meta'sını güncelle.

    NEDEN: 'Gerçek kâr' = equity − yatırılan sermaye. Yatırılan sermaye elle
    tutuluyordu; bir kez unutulunca eklenen para doğrudan 'kâr' diye görünüyor
    (2026-08-28: $82.51 sermaye, /status'ta kâr olarak raporlandı — +%72
    görünürken gerçek +%22'ydi). Artık bot kendisi okur, kimse bir şey
    çalıştırmak zorunda kalmaz.

    ⚠ 90 GÜNLÜK PENCERE TUZAĞI: MEXC varlık uç noktaları 90 günden eskiye
    bakmıyor. Her seferinde "son 90 günün transferleri" toplansaydı, botun
    ömrü 90 günü geçince ESKİ SERMAYE SİLİNİR ve kâr şişerdi. O yüzden taban
    BİRİKİMLİ tutulur: yalnız `sermaye_taban_ts`'den SONRAKİ transferler
    eklenir ve zaman damgası ilerletilir.

    ⚠ İLK TOHUM: taban yoksa mevcut (elle doğrulanmış) inception+deposits
    değerinden başlatılır ve damga ŞİMDİ olur — geçmiş transferler tekrar
    eklenmez, yani çift sayma olmaz.
    """
    if config.exchange.paper_mode or not hasattr(exchange, "fetch_transfers_in"):
        return
    try:
        taban = await db.get_meta_float("sermaye_taban", 0.0)
        damga = await db.get_meta_float("sermaye_taban_ts", 0.0)
        if taban <= 0:
            tohum = (await db.get_meta_float("inception_balance", 0.0)
                     + await db.get_meta_float("total_deposits", 0.0))
            if tohum <= 0:
                return                     # tohum yoksa uydurma
            await db.set_meta("sermaye_taban", str(tohum))
            await db.set_meta("sermaye_taban_ts",
                              str(datetime.now(timezone.utc).timestamp() * 1000))
            logger.info("sermaye_taban tohumlandı: %.2f", tohum)
            return
        simdi = datetime.now(timezone.utc).timestamp() * 1000
        yeni = await exchange.fetch_transfers_in(int(damga))
        if yeni is None:
            logger.debug("sermaye_guncelle: transfer okunamadı, taban korundu")
            return                          # OKUNAMADI ≠ SIFIR
        # ⚠ KAÇAK KORUMASI: tek adımda tabanı equity'nin yarısından fazla
        # değiştiren bir "yeni transfer" gerçek olamaz — süzgeç ya da borsa
        # yanıtı bozulmuş demektir. UYGULAMA, BAĞIR. (Sessizce uygulamak
        # sermayeyi uçurur ve kârı kalıcı olarak yanlış gösterir.)
        if abs(yeni) > 1e-9:
            try:
                eq_now = await executor.current_equity()
            except Exception:
                eq_now = None
            if eq_now and abs(yeni) > max(eq_now * 0.5, 50.0):
                logger.error("sermaye_guncelle: ŞÜPHELİ transfer %+.2f "
                             "(equity %.2f) — UYGULANMADI, damga İLERLETİLMEDİ. "
                             "Elle bak: para_ekle.py --tespit", yeni, eq_now)
                if telegram:
                    await telegram.send_alert(
                        f"⚠️ Sermaye güncellemesi DURDURULDU: borsadan ${yeni:+,.2f} "
                        f"okundu ama equity ${eq_now:,.2f}. Bu kadar büyük bir "
                        f"transfer şüpheli — kayıt DEĞİŞTİRİLMEDİ. "
                        f"Kontrol: para_ekle.py --tespit", "WARNING")
                return
            await db.set_meta("sermaye_taban", str(taban + yeni))
            logger.info("Sermaye tabanı güncellendi: %.2f → %.2f (borsadan "
                        "okunan yeni transfer %+.2f)", taban, taban + yeni, yeni)
            if telegram:
                await telegram.send_alert(
                    f"Sermaye kaydı güncellendi: yatırılan ${taban:,.2f} → "
                    f"${taban + yeni:,.2f} (borsadan okunan transfer "
                    f"${yeni:+,.2f}). Kâr rakamı buna göre düzeltildi.", "INFO")
        await db.set_meta("sermaye_taban_ts", str(simdi))
    except Exception as e:
        logger.debug("sermaye_guncelle hatası: %s", e)


async def _yatirilan() -> float:
    """Toplam yatırılan sermaye = ilk bakiye + deposit.py/para_ekle.py ile
    kaydedilen net akış. Kâr = equity − bu. Kaydedilmemiş bir transfer bu sayıyı
    OLDUĞU YERDE bırakır ve farkı sahte "kâr" gibi gösterir — 28 Ağustos'ta
    tam olarak bu oldu. Kayıt için: para_ekle.py <tutar> --once/--sonra"""
    try:
        taban = await db.get_meta_float("sermaye_taban", 0.0)
        if taban > 0:
            return taban
        return (await db.get_meta_float("inception_balance", 0.0)
                + await db.get_meta_float("total_deposits", 0.0))
    except Exception:
        return 0.0


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

        # Sermaye tabanını borsadan tazele (ucuz: 5 dk'da bir tek istek).
        # Böylece para eklenince kâr rakamı KENDİLİĞİNDEN düzelir.
        try:
            await sermaye_guncelle()
        except Exception as _se:
            logger.debug("sermaye_guncelle: %s", _se)

        since_tg += interval
        if (telegram or ntfy) and since_tg >= tg_every:
            since_tg = 0
            try:
                # ⚠ ESKİ HATA: burada get_balance() vardı = SERBEST bakiye
                # (kilitli marj HARİÇ). Pozisyon açıkken heartbeat /status'tan
                # DÜŞÜK bir sayı basıyor ve ikisi de "bakiye" diye etiketleniyordu
                # (28 Ağustos: 03:00 özet $283.29, 03:20 heartbeat $266.42, arada
                # işlem yok). Artık EQUITY — borsanın kendi rakamı, /status ve
                # günlük zarar freniyle AYNI ölçü.
                n_open = portfolio.get_open_position_count()
                upnl = portfolio.get_total_unrealized_pnl()
                eq = await executor.current_equity()
                if eq is None:
                    # Okunamadıysa YANLIŞ sayı basma — "bilmiyorum" de.
                    msg = (f"Bot çalışıyor · ⚠ equity OKUNAMADI (borsa yanıtı yok) · "
                           f"açık {n_open} · gerçekleşmemiş ${upnl:+.2f}")
                else:
                    inv = await _yatirilan()
                    msg = (f"Bot çalışıyor · equity ${eq:,.2f} · yatırılan "
                           f"${inv:,.2f} · kâr ${eq - inv:+,.2f} · açık {n_open} · "
                           f"gerçekleşmemiş ${upnl:+.2f}")
                if telegram:
                    await telegram.send_alert(msg, "INFO")
                if ntfy:
                    await ntfy.send_alert(msg, "INFO")
            except Exception as e:
                logger.debug("Heartbeat notification failed: %s", e)
        await asyncio.sleep(interval)


# Protection watchdog cadence, in reconciliation cycles (2 min each) → ~20 min.
# Slow on purpose: the healthy path costs one read per open position per pass,
# and MEXC rate-limits (code 510) the order endpoints this shares a budget with.
PROTECTION_CHECK_EVERY = 10

# ─────────────────────────────────────────────────────────────────────────────
# HEDGE-FARKINDA MUTABAKAT — VARSAYILAN KAPALI (HEDGE_AWARE_RECON=false)
#
# NEDEN VAR: mutabakat döngüsü bugüne kadar "sembol başına TEK pozisyon" varsayımıyla
# çalışıyordu (MEXC netted mod). O varsayım altında doğruydu ve kodun yorumlarında
# açıkça yazılı: "MEXC nets same-symbol sleeves into one".
# Pairs kolu bu varsayımı İHLAL EDER: aynı coinde ters yönde ikinci bir pozisyon açar.
# O durumda:
#   · get_position() iki bacaktan hangisini döndüreceği MEXC'in dizi sırasına kalır
#   · internal_qty (sleeve TOPLAMI) tek bacakla karşılaştırılır → eksik görünür
#   · döngü GERÇEKTEN AÇIK sleeve'leri "dışarıdan kapandı" sayıp UYDURMA PnL ile
#     deftere kapatır  ← sessiz bozulma, haftalar sonra fark edilir
#
# NEDEN VARSAYILAN KAPALI: bu kod canlı parayla çalışan bir sistemde mutabakat
# mantığına dokunuyor. Bayrak kapalıyken kod yolu BUGÜNKÜYLE BİT BİT AYNI kalır,
# yani `git pull` yapmak canlı davranışı DEĞİŞTİRMEZ. Açmak ayrı ve bilinçli bir karar
# (.env'de HEDGE_AWARE_RECON=true) ve ancak pairs gerçekten devreye alınırken gerekir.
from exchange import HEDGE_AWARE_RECON   # TEK KAYNAK — exchange.py'de tanımlı


async def _verify_protection(symbol: str) -> None:
    """Confirm a still-open position's exchange-side SL/TP is actually resting.

    Protection was verified at entry and is re-asserted on restart, but nothing
    re-checked a position that was protected at entry and lost its stop
    mid-life (a MEXC-side cancellation, or a netting/partial-fill event). Left
    unattended that is the one failure mode that can take out a large slice of
    the account, because the position then runs with no downside limit at all.

    Read-only on the healthy path — has_sltp_orders() only reads, so a
    protected position is never touched. Acts solely on a CONFIRMED-naked
    result (False, not None) seen on TWO consecutive reads: a single failed or
    empty response must never trigger a cancel+re-place on a position that is
    in fact protected. Re-arming reuses the audited resync path, which itself
    force-closes the position if it cannot restore a stop (fail-safe = flat).

    The caller must already hold executor._symbol_lock(symbol).
    """
    check = getattr(exchange, "has_sltp_orders", None)
    if check is None:
        return
    try:
        if await check(symbol) is not False:
            return
        # Re-confirm, mirroring the external-close double-read below.
        await asyncio.sleep(3)
        if await check(symbol) is not False:
            return
    except Exception as e:
        logger.debug("protection watchdog %s: read failed: %s", symbol, e)
        return
    logger.critical(
        "PROTECTION LOST on %s: open position has no resting SL/TP — re-arming",
        symbol,
    )
    await _emit_alert(
        f"⚠️ {symbol} pozisyonunun stop'u kaybolmuş — yeniden kuruluyor", "ERROR"
    )
    await executor._resync_symbol_stops_locked(symbol)


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
    cycle = 0
    while True:
        cycle += 1
        try:
            # Periodic daily-loss enforcement: the entry-path check only runs
            # when a NEW signal fires, so an open position bleeding between
            # signals could pass -35% unhalted. This closes that window at the
            # reconciliation cadence (~2 min).
            try:
                await executor.enforce_daily_loss()
            except Exception as e:
                logger.error("Periodic daily-loss check failed: %s", e)

            # Group internal positions by symbol. MEXC nets all same-symbol
            # positions into ONE, so we compare the exchange's total contracts
            # for a symbol against the SUM of our internal sleeves on it — this
            # detects a single sleeve closing even while siblings stay open.
            by_symbol: dict[str, list] = defaultdict(list)
            for pos in portfolio.get_open_positions():
                # HEDGE-FARKINDA MOD: gruplama anahtarı sembol DEĞİL (sembol, yön).
                # Bayrak kapalıyken anahtar eskisi gibi düz sembol → davranış BİT BİT AYNI.
                # Açıkken her yön KENDİ borsa bacağıyla karşılaştırılır; aksi halde
                # sleeve TOPLAMI tek bacakla kıyaslanır ve açık sleeve'ler "kapandı"
                # sayılıp uydurma PnL yazılır (bu değişikliğin varlık sebebi).
                key = (pos.symbol, pos.side) if HEDGE_AWARE_RECON else pos.symbol
                by_symbol[key].append(pos)

            for _key, positions in by_symbol.items():
                symbol = _key[0] if HEDGE_AWARE_RECON else _key
                want_side = _key[1] if HEDGE_AWARE_RECON else None
                try:
                    # Hold the per-symbol lock across the whole detect→close→resync
                    # sequence so a concurrent entry/close/trailing on this netted
                    # symbol can't interleave (read stale exchange state, or have
                    # its just-placed stop cancelled before we re-place siblings').
                    async with executor._symbol_lock(symbol):
                        # want_side None (bayrak kapalı) → get_position eski imzayla
                        # çağrılır ve İLK kaydı döner: bugünkü davranış AYNEN.
                        # want_side dolu → yalnız o bacak okunur, karşılaştırma
                        # yön-bazında yapılır.
                        mexc_pos = await exchange.get_position(symbol, want_side) \
                            if want_side else await exchange.get_position(symbol)
                        exch_qty = float(mexc_pos.contracts) if mexc_pos else 0.0
                        internal_qty = sum(p.quantity for p in positions)
                        tol = max(internal_qty * 0.01, 1e-9)
                        if exch_qty + tol >= internal_qty:
                            # All sleeves still open on the exchange. Nothing to
                            # reconcile — but on a slow cadence confirm the
                            # position is still actually PROTECTED (see
                            # _verify_protection: entry and restart were the only
                            # checks, so a stop lost mid-life went unnoticed).
                            if cycle % PROTECTION_CHECK_EVERY == 0:
                                await _verify_protection(symbol)
                            continue

                        # Re-confirm before acting: a single transient read of 0/low
                        # contracts (network glitch / partial response) must NOT
                        # trigger a phantom close that books fabricated PnL. Require
                        # TWO consecutive reads to both show the shortfall.
                        await asyncio.sleep(2)
                        # TEYİT OKUMASI DA AYNI BACAĞA BAKMALI. İlk okuma yön-bazlı
                        # yapılıp teyit okuması sembol-bazlı yapılırsa iki farklı
                        # bacak karşılaştırılır ve teyit mekanizması — sahte kapanışı
                        # önlemek için VAR OLAN mekanizma — kendisi sahte sonuç üretir.
                        confirm = await exchange.get_position(symbol, want_side) \
                            if want_side else await exchange.get_position(symbol)
                        confirm_qty = float(confirm.contracts) if confirm else 0.0
                        if confirm_qty + tol >= internal_qty:
                            logger.info(
                                "Reconciliation: %s shortfall not confirmed on re-read "
                                "(%.6f vs %.6f internal) — skipping",
                                symbol, confirm_qty, internal_qty)
                            continue
                        exch_qty = min(exch_qty, confirm_qty)  # act on the confirmed qty

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
                            # Only close a WHOLE sleeve when the confirmed external
                            # shortfall actually covers it. A partial shortfall that
                            # doesn't line up with any whole sleeve (e.g. a manual
                            # partial close on the netted position) must NOT book a
                            # full fabricated close — that would record bogus PnL and
                            # leave the still-live remainder mis-sized. Skip this
                            # sleeve; a smaller sibling may match instead.
                            if pos.quantity > to_close + tol:
                                # Sleeve is larger than the shortfall — a partial
                                # external close reduced part of this sleeve on MEXC.
                                # Shrink the sleeve's tracked quantity to match MEXC
                                # reality (exch_qty) so future resync stop placements
                                # use the correct size and aren't silently rejected.
                                logger.warning(
                                    "Reconciliation: %s sleeve %.6f exceeds remaining "
                                    "shortfall %.6f — partial external close; "
                                    "adjusting sleeve qty to %.6f",
                                    symbol, pos.quantity, to_close, exch_qty)
                                pos.quantity = exch_qty
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

                            # ⚠ ESKİ HATA: çıkış SEVİYE fiyatından (sl_price/tp_price)
                            # defterlere yazılıyordu — GERÇEK dolumdan değil. Stop-market
                            # emri seviyenin ötesinde dolar, yani her SL çıkışı olduğundan
                            # İYİ kaydediliyordu. Çıkış ücreti de 1bp sabitti; ölçülen
                            # gerçek ~2.5bp (DURUM 2d). İkisi birlikte defteri borsadan
                            # uzaklaştırıyor ve GÜNLÜK ZARAR FRENİ bu defteri okuyor.
                            # Artık borsanın gerçek dolumu sorulur; okunamazsa ESKİ
                            # davranışa düşülür ve kayıt 'tahmin' diye İŞARETLENİR
                            # (sessizce doğru sanılmasın).
                            gercek = None
                            if hasattr(exchange, "fetch_close_fill"):
                                try:
                                    kapanis_side = "sell" if direction == 1 else "buy"
                                    since_ms = int(pos.entry_time.timestamp() * 1000)
                                    gercek = await exchange.fetch_close_fill(
                                        symbol, kapanis_side, pos.quantity, since_ms)
                                except Exception as _fe:
                                    logger.debug("fetch_close_fill hatası: %s", _fe)
                                    gercek = None
                            if gercek is not None:
                                gercek_px, gercek_ucret, _nf = gercek
                                logger.info(
                                    "Reconciliation: %s GERÇEK dolum $%.6f (seviye "
                                    "$%.6f, fark %+.1fbp) · gerçek ücret $%.4f",
                                    symbol, gercek_px, exit_price,
                                    (gercek_px - exit_price) / exit_price * 1e4
                                    if exit_price > 0 else 0.0, gercek_ucret)
                                exit_price = gercek_px
                                fees = pos.entry_price * pos.quantity * entry_fee + gercek_ucret
                            else:
                                pos.strategy_scores["exit_price_estimated"] = True
                                fees = (pos.entry_price * pos.quantity * entry_fee
                                        + exit_price * pos.quantity * 0.0001)
                            raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
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
    global funding_monitors, orderflow_monitors, whale_monitor, symbol_ctxs

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
        try:
            # Set leverage/margin per coin before trading.
            for sym in symbols:
                await live.initialize(sym)
        except Exception as exc:
            # Exchange init failed (e.g. code 402 expired key, code 10072 wrong
            # permissions). Start a minimal error-dashboard so the user can see
            # what went wrong and click Restart — no SSH required.
            err = str(exc)[:500]
            logger.critical("Exchange init failed — showing error dashboard: %s", err)
            await WebDashboard.start_error_page(config.web, err)
            raise  # propagate so systemd restarts after fix
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
                )
                if config.strategy.ifvg_enabled
                and (
                    config.strategy.ifvg_symbols is None
                    or sym in config.strategy.ifvg_symbols
                )
                else None
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
                )
                if config.strategy.squeeze_enabled
                and (
                    config.strategy.squeeze_symbols is None
                    or sym in config.strategy.squeeze_symbols
                )
                else None
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
            donchian_strategy=(
                DonchianStrategy(
                    channel=config.strategy.donchian_channel,
                    rr=config.strategy.donchian_rr,
                    sl_atr=config.strategy.donchian_sl_atr,
                    ema_trend=config.strategy.donchian_ema_trend,
                    buffer_atr=config.strategy.donchian_buffer_atr,
                )
                if config.strategy.donchian_enabled
                and (
                    config.strategy.donchian_symbols is None
                    or sym in config.strategy.donchian_symbols
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
    # Let the module-level background-task supervisors push phone alerts too.
    global _alert_hook
    _alert_hook = _send_alert

    # Rebuild any open positions from before a restart (balance + positions).
    await restore_state()

    # Live: re-assert SL/TP for every restored position whose MEXC position is
    # still open. Plan orders expire after executeCycle (24h) and may also have
    # been cancelled while the bot was down — without this a restored position
    # could sit unprotected. Skip symbols MEXC no longer shows (the
    # reconciliation loop will close those ghosts shortly after startup).
    if not config.exchange.paper_mode:
        # Process sequentially with a gap so rapid cancel+SL+TP bursts from
        # multiple symbols don't hit MEXC's rate limit (code 510).
        for sym in {p.symbol for p in portfolio.get_open_positions()}:
            try:
                if await exchange.get_position(sym) is not None:
                    await executor.resync_symbol_stops(sym)
                    logger.info("Re-asserted SL/TP for restored position(s) on %s", sym)
                    await asyncio.sleep(1.5)   # breathe between symbols
            except Exception as e:
                logger.error("Could not re-assert stops for %s on restart: %s", sym, e)

        # Startup sweep over ALL configured symbols (exchange = source of truth).
        # restore_state() rebuilds the portfolio from the DB only, so a position
        # that exists on MEXC but has no DB row (a crash in the fill→DB-write
        # window, or a manually-opened position) would otherwise run UNMANAGED
        # forever — no max-hold, no trailing, no bot close, no alert. Detect both:
        #   • exchange position with NO tracked sleeve  → ORPHAN POSITION → alert
        #   • flat symbol with stale resting entry/plan orders → cancel them
        tracked = {p.symbol for p in portfolio.get_open_positions()}
        for sym in symbol_ctxs:
            try:
                ex_pos = await exchange.get_position(sym)
            except Exception as e:
                logger.error("startup sweep: get_position(%s) failed: %s", sym, e)
                continue
            if ex_pos is not None and sym not in tracked:
                logger.critical(
                    "ORPHAN POSITION on %s: %s %.6f @ %.4f — exists on MEXC but is "
                    "NOT tracked by the bot. It will NOT be managed (no SL/TP "
                    "re-assert, no max-hold). Manual intervention required.",
                    sym, ex_pos.side, ex_pos.contracts, ex_pos.entry_price,
                )
                await _send_alert(
                    f"🚨 SAHİPSİZ POZİSYON {sym}: {ex_pos.side} "
                    f"{ex_pos.contracts:.4f} @ {ex_pos.entry_price:.4f} — MEXC'te "
                    f"var ama bot takip ETMİYOR. Manuel kontrol et!",
                    "ERROR",
                )
                await asyncio.sleep(1.0)
            elif ex_pos is None and sym not in tracked:
                # No position on this symbol — clear any stale resting entry /
                # plan orders left over from a crash (cancel_stop_orders also
                # calls cancel_all_orders). Position-attached SL/TP is sticky and
                # is unaffected; there is no position here to protect anyway.
                try:
                    await exchange.cancel_stop_orders(sym)
                    await asyncio.sleep(0.5)   # breathe — avoid MEXC rate limit
                except Exception as e:
                    logger.debug("startup order sweep %s: %s", sym, e)

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
        init_eq = executor.get_daily_starting_balance()
        await db.upsert_daily_stats(DailyStats(
            date=today_iso,
            starting_balance=init_eq,
            ending_balance=init_eq,
            total_trades=0, winning_trades=0, total_pnl_usdt=0.0,
            max_drawdown=0.0, is_paper=config.exchange.paper_mode,
        ))

    # Persist the inception balance on first run; use it consistently across
    # restarts so /status always shows return-since-day-one, not since-last-restart.
    # Guard: if the stored value is < $1 it was written during a bad startup
    # (expired key, empty account, etc.) and would produce a nonsense return %.
    # Overwrite it with today's real balance so the dashboard shows 0% from now.
    inception_raw = await db.get_meta("inception_balance")
    stored_inception = float(inception_raw) if inception_raw is not None else 0.0
    if stored_inception < 1.0:
        await db.set_meta("inception_balance", str(balance))
        inception_balance = balance
        logger.info("inception_balance reset to %.2f (was %.4f — bogus startup value)", balance, stored_inception)
    else:
        inception_balance = stored_inception

    combiner = SignalCombiner(config.strategy)

    # Funding monitor tracks the primary symbol (read-only dataset building).
    # One funding monitor per traded symbol (fetch is cached + on-demand, so
    # this adds no standing load). Monitor-first: reads are LOGGED next to each
    # BB signal (funding_log.csv) to build the forward dataset; filter/boost
    # modes only ever act on the signal coin's OWN funding.
    for _sym in config.exchange.symbols:
        funding_monitors[_sym] = FundingMonitor(
            exchange,
            _sym,
            enabled=config.strategy.funding_enabled,
            mode=config.strategy.funding_mode,
            extreme_threshold=config.strategy.funding_extreme,
        )
    funding_monitor = funding_monitors[config.exchange.symbol]
    if funding_monitor.enabled:
        logger.info(
            "Funding monitor ON (mode=%s, extreme=%.4f%%)",
            funding_monitor.mode, config.strategy.funding_extreme * 100,
        )

    # Order-flow collectors: one per traded symbol (each keeps its own
    # watchTrades feed — a handful of public streams, negligible load). Default
    # OFF; started below after the data feeds are up. Monitor-only: the flow
    # snapshot is LOGGED next to each BB signal (orderflow_log.csv) so the
    # forward dataset grows across all coins; it never affects trading.
    for _sym in config.exchange.symbols:
        orderflow_monitors[_sym] = OrderFlowMonitor(
            exchange,
            _sym,
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
        daily_max_loss=config.risk.daily_max_loss,
    )
    await web_dashboard.start()

    # Wire each coin's candle-close handler and start its data feed.
    for sym, ctx in symbol_ctxs.items():
        ctx.data_mgr.subscribe_candle_close(
            config.strategy.primary_tf, make_on_candle_close(ctx)
        )
        # ORB stop-entry: a tick-watcher that fires a market order the instant
        # price crosses the opening-range boundary (validated vs limit-retrace).
        if ctx.orb_strategy is not None and config.strategy.orb_stop_entry:
            ctx.data_mgr.subscribe_price_tick(make_on_orb_tick(ctx))

    _spawn_supervised(daily_reset_loop, "daily_reset_loop", restart=True)
    _spawn_supervised(heartbeat_loop, "heartbeat_loop", restart=True)
    _spawn_supervised(position_reconciliation_loop, "position_reconciliation_loop", restart=True)

    logger.info(
        "Bot running. Coins=%d TF=%s Balance=%.2f",
        len(symbol_ctxs), config.strategy.primary_tf, balance,
    )

    for ctx in symbol_ctxs.values():
        await ctx.data_mgr.start_feeds()

    # Start the order-flow feeds (no-ops if disabled).
    for _om in orderflow_monitors.values():
        await _om.start()
    # Start the whale-flow aggregator (no-op if disabled).
    await whale_monitor.start()

    # Startup ping: tells us the bot (re)started. During an unattended month a
    # silent watchdog/systemd respawn would otherwise go unnoticed — repeated
    # startup pings are the signal that something is crash-looping.
    try:
        mode = "PAPER" if config.exchange.paper_mode else "LIVE"
        n_open = portfolio.get_open_position_count()
        start_msg = (
            f"🚀 Bot başladı [{mode}] · {len(symbol_ctxs)} coin · "
            f"bakiye ${balance:,.2f} · açık pozisyon {n_open}"
        )
        if telegram:
            await telegram.send_alert(start_msg, "INFO")
        if ntfy:
            await ntfy.send_alert(start_msg, "INFO")
    except Exception as e:
        logger.debug("Startup notification failed: %s", e)

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
    for _om in orderflow_monitors.values():
        await _om.stop()
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
