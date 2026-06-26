from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Awaitable

from config import AppConfig
from database import Database, TradeRecord
from exchange import PaperExchange, LiveExchange, OrderResult
from portfolio import Portfolio, Position
from risk import RiskManager, TradeSetup
from strategies.signal_combiner import CombinedSignal

logger = logging.getLogger(__name__)

# BTC, ETH, SOL are highly correlated — a single macro news event can stop
# out all three simultaneously. Capping same-direction exposure across this
# group prevents 3× correlated loss from one market move.
_CORRELATED_GROUPS: tuple[frozenset, ...] = (
    frozenset({"BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"}),
)


class _null_ctx:
    """Async context manager that does nothing — used as a no-op when the
    exchange object doesn't have a _stop_order_lock (e.g. PaperExchange)."""
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass


@dataclass
class ExecutionResult:
    success: bool
    position: Optional[Position] = None
    trade_setup: Optional[TradeSetup] = None
    error: Optional[str] = None


class ExecutionEngine:
    def __init__(
        self,
        exchange,
        risk: RiskManager,
        portfolio: Portfolio,
        database: Database,
        config: AppConfig,
    ):
        self._exchange = exchange
        self._risk = risk
        self._portfolio = portfolio
        self._db = database
        self._config = config
        self._trading_halted = asyncio.Event()
        self._daily_starting_balance: float = 0.0
        self._on_close_callbacks: list[Callable] = []
        self._alert_cb: Optional[Callable] = None
        self._executing: set[str] = set()  # symbols with in-flight execute_signal
        self._consecutive_losses: dict[str, int] = {}   # (strategy:symbol) → streak
        # Per-(strategy:symbol) cooldown end times. A loss streak on one sleeve
        # pauses only THAT sleeve, not every coin — the edges are validated
        # independently, so an ETH-BB streak shouldn't suppress BTC-ORB.
        self._cooldown_until: dict[str, datetime] = {}
        # Strong refs to fire-and-forget alert tasks so they aren't GC'd mid-send
        # and their exceptions are retrieved (not silently dropped).
        self._bg_tasks: set = set()
        # Global lock that serializes the guard-check + slot-reservation phase of
        # every execute_signal() call. Without this, N simultaneous candle-close
        # events for N correlated coins all pass the correlation-cap and
        # MAX_POSITIONS checks before any one of them adds to the portfolio, then
        # all place orders — opening N instead of max M. The lock is held ONLY for
        # the in-memory checks + reservation (no I/O), so it doesn't serialize the
        # order-placement itself (concurrent fills across different slots are fine).
        self._entry_gate = asyncio.Lock()
        # In-flight slot tracking: maps slot_key → symbol / direction for
        # concurrent guard checks under _entry_gate (portfolio only shows confirmed
        # open positions, not in-flight reservations).
        self._inflight_symbol: dict[str, str] = {}
        self._inflight_direction: dict[str, int] = {}
        # Per-symbol lock serializing every operation that mutates a symbol's
        # exchange position/stops (entry place+set_sl_tp+register, trailing
        # resync, close, reconciliation). MEXC nets same-symbol sleeves into one
        # position, so without this a resync on one coroutine could cancel a stop
        # another coroutine just placed — leaving a live position unprotected.
        self._symbol_locks: dict[str, asyncio.Lock] = {}
        if isinstance(exchange, PaperExchange):
            exchange.register_close_callback(self._on_paper_position_closed)

    def _symbol_lock(self, symbol: str) -> asyncio.Lock:
        lock = self._symbol_locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._symbol_locks[symbol] = lock
        return lock

    def register_close_callback(self, cb: Callable) -> None:
        self._on_close_callbacks.append(cb)

    def register_alert_callback(self, cb: Callable) -> None:
        """An async callback(message:str, level:str) for important events the
        user should see immediately (e.g. daily loss halt)."""
        self._alert_cb = cb

    async def _alert(self, message: str, level: str = "WARNING") -> None:
        if self._alert_cb is None:
            return
        try:
            await self._alert_cb(message, level)
        except Exception as e:
            logger.debug("Alert callback failed: %s", e)

    async def _persist_balance(self) -> None:
        """Persist the paper balance so it survives a restart (live balance lives
        on the exchange and needs no persistence)."""
        if not self._config.exchange.paper_mode:
            return
        try:
            bal = await self._exchange.get_balance()
            await self._db.set_meta("paper_balance", str(bal))
        except Exception as e:
            logger.debug("Could not persist paper balance: %s", e)

    def halt_trading(self, reason: str) -> None:
        logger.warning("Trading HALTED: %s", reason)
        self._trading_halted.set()

    def is_halted(self) -> bool:
        return self._trading_halted.is_set()

    def set_daily_starting_balance(self, balance: float) -> None:
        self._daily_starting_balance = balance

    def get_daily_starting_balance(self) -> float:
        return self._daily_starting_balance

    def _locked_margin(self) -> float:
        """Sum of margin locked in open positions. get_balance() returns FREE
        balance (margin already deducted), so the daily-loss check must add this
        back to recover true account equity — otherwise locking margin across
        several parallel positions looks like a loss and false-triggers the halt."""
        lev = max(self._config.exchange.leverage, 1)
        return sum(
            p.quantity * p.entry_price / lev
            for p in self._portfolio.get_open_positions()
        )

    async def current_equity(self) -> float | None:
        """True account equity. Prefer the exchange's own equity figure (most
        accurate — folds in fees/funding the bot doesn't track); fall back to a
        reconstruction (free balance + locked margin + unrealized PnL) for paper
        mode.

        LIVE: returns None when equity is UNREADABLE (transient exchange/balance
        failure). Callers MUST treat None as 'unknown — do not act', NOT as a
        loss: get_balance()/get_equity() degrade a failed read to 0.0, and the
        old reconstruction (free=0 + locked + uPnL) understated equity by the
        whole free-cash component — on a small account that false-tripped the
        daily-loss kill switch and emergency_close_all. We never halt or
        force-close off a read that may simply have failed."""
        if hasattr(self._exchange, "get_equity"):
            try:
                eq = await self._exchange.get_equity()
            except Exception as e:
                logger.debug("get_equity failed — equity unreadable: %s", e)
                return None
            # get_equity already falls back to ccxt's `total` internally; a
            # non-positive result here means the balance endpoint was unreadable
            # (or the account is genuinely empty). Either way, do NOT reconstruct
            # a misleading low figure — signal 'unknown'.
            return eq if eq > 0 else None
        # Paper mode: the simulated balance is always readable.
        free = await self._exchange.get_balance()
        return free + self._locked_margin() + self._portfolio.get_total_unrealized_pnl()

    async def capture_daily_start(self) -> None:
        """Snapshot today's starting EQUITY (not free balance) so the daily-loss
        limit measures realized+unrealized drawdown, not locked margin.

        If equity is unreadable (None), KEEP the prior baseline rather than
        overwriting it with a bogus 0 — a 0 baseline disables the daily-loss
        switch for the whole day (check returns 'allowed' when start<=0)."""
        eq = await self.current_equity()
        if eq is not None and eq > 0:
            self._daily_starting_balance = eq
        else:
            logger.warning(
                "capture_daily_start: equity unreadable — keeping prior baseline "
                "%.2f (daily-loss switch unchanged)",
                self._daily_starting_balance or 0.0,
            )

    def reset_daily(self) -> None:
        self._trading_halted.clear()

    def resume_trading(self) -> None:
        """Manually clear a halt (e.g. via Telegram /resume)."""
        self._trading_halted.clear()
        logger.info("Trading RESUMED (manual)")

    def _record_trade_outcome(
        self, net_pnl: float, strategy: str = "all", symbol: str = ""
    ) -> None:
        """Track consecutive losses per (strategy, symbol); trigger a global
        cooldown when any one sleeve hits the limit. Per-strategy counters prevent
        a small ORB win from masking a BB loss streak; adding the symbol to the key
        keeps each coin's streak independent (an ETH-BB loss must not be conflated
        with BTC-BB, since the edges are validated per coin). The cooldown itself
        stays global — a conservative account-wide risk-off after any sleeve fails."""
        limit = getattr(self._config.risk, "consecutive_loss_limit", 2)
        cooldown_min = getattr(self._config.risk, "cooldown_minutes", 240)
        key = f"{strategy}:{symbol}" if symbol else strategy
        label = f"{strategy} {symbol}".strip()
        if net_pnl < 0:
            self._consecutive_losses[key] = self._consecutive_losses.get(key, 0) + 1
            streak = self._consecutive_losses[key]
            if streak >= limit:
                until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_min)
                self._cooldown_until[key] = until
                logger.warning(
                    "[%s] Consecutive losses: %d — cooldown until %s",
                    label, streak, until.strftime("%H:%M UTC"),
                )
                task = asyncio.create_task(self._alert(
                    f"[{label.upper()}] Üst üste {streak} kayıp — "
                    f"{cooldown_min} dk cooldown başladı",
                    "WARNING",
                ))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
        else:
            self._consecutive_losses[key] = 0

    async def execute_signal(
        self, signal: CombinedSignal, atr: float
    ) -> ExecutionResult:
        if signal.direction == 0:
            return ExecutionResult(False, error="No signal")

        # Multi-coin: the signal carries its own symbol; fall back to the
        # configured primary symbol for single-coin operation.
        symbol = signal.symbol or self._config.exchange.symbol

        # All guard checks AND the slot reservation are atomic under _entry_gate.
        # Without this, N simultaneous candle-close events for N correlated coins
        # (BTC/ETH/SOL all closing the same 1h candle) each see an empty portfolio,
        # all pass the correlation-cap and MAX_POSITIONS checks, then all place
        # orders — opening N instead of the configured maximum. The lock is held
        # ONLY for the in-memory checks + reservation (no I/O), so order placements
        # still run concurrently across different slots.
        async with self._entry_gate:
            if self.is_halted():
                return ExecutionResult(False, error="Trading halted (daily loss limit)")

            # Per-(strategy:symbol) cooldown — only this sleeve is paused after its
            # own loss streak; other coins/strategies keep trading.
            cd_key = f"{signal.dominant_strategy}:{symbol}"
            cd_until = self._cooldown_until.get(cd_key)
            if cd_until is not None:
                if datetime.now(timezone.utc) < cd_until:
                    remaining = (cd_until - datetime.now(timezone.utc)).total_seconds() / 60
                    return ExecutionResult(False, error=f"Cooldown active ({remaining:.0f}m remaining)")
                else:
                    del self._cooldown_until[cd_key]

            # MAX_POSITIONS: count confirmed open (portfolio) + in-flight entries.
            # A slot reserved by a concurrent coroutine is already counted, so a
            # burst of N simultaneous signals can't all sneak past the cap before
            # any one of them completes and registers in the portfolio.
            max_pos = getattr(self._config.risk, "max_positions", 4)
            total_open = self._portfolio.get_open_position_count() + len(self._executing)
            if total_open >= max_pos:
                return ExecutionResult(False, error=f"Max positions ({max_pos}) reached")

            # Correlation cap: prevent piling into the same direction across coins
            # that historically move together (BTC/ETH/SOL). Count BOTH confirmed
            # portfolio positions AND in-flight reservations for the same direction
            # so three simultaneous ORB signals can't all pass when the cap is 2.
            max_corr = getattr(self._config.risk, "max_correlated_direction", 2)
            if max_corr > 0 and signal.direction != 0:
                for grp in _CORRELATED_GROUPS:
                    if symbol in grp:
                        same_dir = sum(
                            1 for p in self._portfolio.get_open_positions()
                            if p.symbol in grp and p.direction == signal.direction
                        )
                        same_dir += sum(
                            1 for slot, d in self._inflight_direction.items()
                            if d == signal.direction
                            and self._inflight_symbol.get(slot) in grp
                        )
                        if same_dir >= max_corr:
                            side = "long" if signal.direction == 1 else "short"
                            return ExecutionResult(
                                False,
                                error=f"Correlation cap: {same_dir}/{max_corr} {side} already open in correlated group",
                            )
                        break

            # Slot key: each strategy sleeve has its own slot so BB, ORB, and Asia BO
            # can run in parallel without blocking one another. S/R breakout shares the
            # BB slot (both are 48h swing trades — only one at a time makes sense).
            slot_key = signal.position_slot or symbol

            if self._portfolio.get_position_for_slot(slot_key) is not None:
                return ExecutionResult(False, error=f"Slot '{slot_key}' already occupied")
            if slot_key in self._executing:
                return ExecutionResult(False, error=f"Execution in progress for slot '{slot_key}'")

            # Reserve the slot BEFORE releasing the gate. Subsequent coroutines that
            # acquire the gate will see this reservation in the counts above and be
            # blocked if limits are reached — even before a portfolio entry exists.
            self._executing.add(slot_key)
            self._inflight_symbol[slot_key] = symbol
            self._inflight_direction[slot_key] = signal.direction

        # Gate released — order placement runs concurrently across different slots.
        try:
            return await self._execute_signal_inner(signal, atr, symbol, slot_key)
        finally:
            self._executing.discard(slot_key)
            self._inflight_symbol.pop(slot_key, None)
            self._inflight_direction.pop(slot_key, None)

    async def _execute_signal_inner(
        self, signal: CombinedSignal, atr: float, symbol: str, slot_key: str = ""
    ) -> "ExecutionResult":
        balance = await self._exchange.get_balance()

        # Daily-loss limit is measured on EQUITY (free + locked margin + unrealized),
        # not free balance — otherwise locking margin for parallel positions reads
        # as a loss. open_unrealized_pnl is passed 0 here because current_equity()
        # already folds unrealized PnL into the equity figure. Use current_equity()
        # so live trading reads the exchange's authoritative equity (with paper /
        # read-failure fallback to the reconstruction).
        equity = await self.current_equity()
        if equity is None:
            # Equity unreadable (transient exchange hiccup). Skip THIS entry
            # rather than evaluating the daily-loss limit on a bogus figure —
            # never halt / emergency-close off a failed balance read.
            return ExecutionResult(False, error="Equity unreadable — entry skipped")
        if not self._risk.check_daily_loss_limit(
            self._daily_starting_balance,
            equity,
            0.0,
        ):
            self.halt_trading("Daily loss limit reached")
            await self.emergency_close_all("daily_loss_limit")
            loss_pct = (
                (self._daily_starting_balance - equity) / self._daily_starting_balance
                if self._daily_starting_balance > 0 else 0.0
            )
            await self._alert(
                f"GÜNLÜK ZARAR LİMİTİ (-{loss_pct*100:.1f}%). Bugünlük trade durduruldu.",
                "ERROR",
            )
            return ExecutionResult(False, error="Daily loss limit")

        # Confidence sizing (opt-in): map confidence 0.6→1.0 to a 0.7→1.0 size
        # multiplier so weak signals risk less; strong signals get full risk.
        size_mult = 1.0
        if getattr(self._config.risk, "confidence_sizing", False):
            c = max(0.0, min(signal.confidence, 1.0))
            size_mult = max(0.5, min(1.0, 0.4 + 0.6 * c))

        # Strategies that pre-compute precise SL/TP levels (ORB, Asia BO, S/R
        # breakout) pass them in the signal. Use those directly; fall back to the
        # ATR-based calc for the 1h BB swing strategy. Intraday day-trades (ORB,
        # Asia BO) use the smaller day_risk_pct; S/R breakout is a swing trade and
        # uses full risk (override=0 → config max_risk_per_trade).
        if getattr(signal, "sl_price", 0.0) > 0 and getattr(signal, "tp_price", 0.0) > 0:
            # Each intraday sleeve has its own validated risk %. ORB carries more
            # weight than Asia BO; S/R breakout (swing) uses full config risk.
            if signal.dominant_strategy == "orb":
                risk_override = getattr(self._config.risk, "orb_risk_pct",
                                        getattr(self._config.risk, "day_risk_pct", 0.0))
                # Weekend ORB has PF 3.22 vs weekday — scale up when research says to.
                weekend_mult = getattr(self._config.risk, "orb_weekend_mult", 1.0)
                if weekend_mult > 1.0 and datetime.now(timezone.utc).weekday() >= 5:
                    risk_override = min(risk_override * weekend_mult, 0.08)
            elif signal.dominant_strategy == "asia_bo":
                risk_override = getattr(self._config.risk, "asia_risk_pct",
                                        getattr(self._config.risk, "day_risk_pct", 0.0))
            elif signal.dominant_strategy == "fvg":
                risk_override = getattr(self._config.risk, "fvg_risk_pct",
                                        getattr(self._config.risk, "day_risk_pct", 0.0))
            elif signal.dominant_strategy == "ifvg":
                risk_override = getattr(self._config.risk, "ifvg_risk_pct",
                                        getattr(self._config.risk, "day_risk_pct", 0.0))
            else:
                risk_override = 0.0
            setup = self._risk.build_trade_setup_from_levels(
                direction=signal.direction,
                entry_price=signal.entry_price,
                sl_price=signal.sl_price,
                tp_price=signal.tp_price,
                balance=balance,
                leverage=self._config.exchange.leverage,
                symbol=symbol,
                risk_pct_override=risk_override,
            )
        else:
            setup = self._risk.build_trade_setup(
                direction=signal.direction,
                entry_price=signal.entry_price,
                atr=atr,
                balance=balance,
                leverage=self._config.exchange.leverage,
                symbol=symbol,
                size_mult=size_mult,
            )
        if setup is None:
            logger.warning("[%s] trade setup failed (ATR/balance/size too small?)", symbol)
            return ExecutionResult(False, error="Could not build trade setup")

        ok, reason = self._risk.validate_new_trade(
            setup, self._portfolio.get_open_position_count()
        )
        if not ok:
            logger.warning("[%s] validate_new_trade failed: %s", symbol, reason)
            return ExecutionResult(False, error=reason)

        # Pre-flight margin check: get_balance() already returns FREE balance
        # (locked margin deducted), so compare directly with a 5% buffer for
        # fees/slippage. Without this, MEXC silently rejects oversized orders.
        if setup.margin_required > balance * 0.95:
            msg = (
                f"Yetersiz bakiye: {setup.margin_required:.2f}$ gerekli, "
                f"{balance:.2f}$ serbest — trade atlandı"
            )
            logger.warning(msg)
            await self._alert(msg, "WARNING")
            return ExecutionResult(False, error="Insufficient free margin")

        side = "buy" if signal.direction == 1 else "sell"
        # Both paper and live attach SL/TP to the ENTRY order. MEXC's separate
        # plan-order endpoint (PlanorderPlace) is under maintenance and silently
        # returns an empty order (no id) — that was force-closing every live
        # position 2-3s after entry. ccxt forwards stopLossPrice/takeProfitPrice
        # on the entry order to the WORKING OrderCreate endpoint, which attaches
        # them to the position. PaperExchange reads the same params in check_sl_tp.
        params = {
            "stopLossPrice": setup.sl_price,
            "takeProfitPrice": setup.tp_price,
        }

        # Maker entry: place a post-only limit at the signal price to pay 0% fee
        # instead of 0.01% taker. Over a year this is worth several % of return
        # (see research_maximize.py). Falls back to market if unfilled.
        use_maker = (
            getattr(self._config.exchange, "maker_entry", False)
            and hasattr(self._exchange, "place_limit_order")
            # ORB stop-entry fires AT the level — take it immediately with a market
            # order; a maker limit would wait for a retrace and miss the breakout.
            and not getattr(signal, "force_market", False)
        )
        # Structure-based strategies (ORB, Asia BO, FVG, IFVG, S/R breakout) anchor
        # SL/TP to the breakout level, NOT the fill price. A market fallback would
        # fill far from the level and collapse R/R to <1 (e.g. R/R=0.33 for BNB).
        # For these: no fallback — if limit doesn't fill at the level, skip the trade.
        # ATR-based strategies (trend/MR/breakout) compute SL/TP from entry_price so
        # a market fallback keeps R/R intact → fallback_market=True for those.
        is_structure_based = getattr(signal, "sl_price", 0.0) > 0
        # Acquire per-symbol lock before touching the exchange so no concurrent
        # resync can cancel a stop we just placed before the position is in the
        # portfolio (at which point resync correctly re-places it).
        async with self._symbol_lock(symbol):
            try:
                if use_maker:
                    # Structure-based trades need more time: the 1h candle already
                    # closed past the level, so the limit fills only on a retrace.
                    # 10 minutes gives a reasonable retrace window without holding
                    # through a full candle on a bad fill. ATR-based trades keep the
                    # default 45s (limit is near current price, fills quickly or not).
                    limit_timeout = 600.0 if is_structure_based else 45.0
                    order: Optional[OrderResult] = await self._exchange.place_limit_order(
                        setup.symbol, side, setup.quantity, setup.entry_price, params,
                        timeout=limit_timeout,
                        fallback_market=not is_structure_based,
                    )
                    if order is None:
                        return ExecutionResult(False, error="Maker limit unfilled")
                else:
                    order = await self._exchange.place_market_order(
                        setup.symbol, side, setup.quantity, params
                    )
            except Exception as e:
                logger.error("Order placement failed: %s", e)
                return ExecutionResult(False, error=str(e))

            # Live mode: SL/TP rode on the entry order (params above). VERIFY it
            # actually rests on MEXC before trusting the position is protected; a
            # live position must never sit without a stop. If confirmed missing,
            # close immediately for safety. If the verification READ fails (not the
            # stop itself), keep the position — the attach path is proven reliable —
            # but alert loudly to check manually.
            if not self._config.exchange.paper_mode and hasattr(self._exchange, "has_sltp_orders"):
                pos_side = "long" if signal.direction == 1 else "short"
                protected = None
                for _ in range(3):
                    await asyncio.sleep(1)
                    protected = await self._exchange.has_sltp_orders(setup.symbol)
                    if protected:
                        break
                if protected is True:
                    logger.info(
                        "Live SL/TP attached & verified: sl=%.4f tp=%.4f",
                        setup.sl_price, setup.tp_price,
                    )
                elif protected is False:
                    logger.error(
                        "SL/TP NOT attached for %s — closing position for safety",
                        setup.symbol)
                    try:
                        await self._exchange.close_position(
                            setup.symbol, pos_side, order.quantity, "no_stop_safety"
                        )
                    except Exception as ce:
                        logger.critical("EMERGENCY: could not close unprotected position: %s", ce)
                    return ExecutionResult(False, error="SL/TP not attached; position closed")
                else:
                    logger.error(
                        "Could not verify SL/TP for %s (read failed) — position kept; "
                        "CHECK MANUALLY", setup.symbol)
                    await self._alert(
                        f"⚠️ {setup.symbol} SL/TP doğrulanamadı — MEXC'ten kontrol et",
                        "ERROR")

            scores = {
                "trend": signal.trend_score,
                "mean_rev": signal.mean_rev_score,
                "breakout": signal.breakout_score,
                "confidence": signal.confidence,
                "strategy": signal.dominant_strategy,
                # ATR at entry — used by trailing stop to keep distance consistent
                # regardless of how ATR changes during the life of the trade.
                "atr": atr,
                # Slot key for position uniqueness in multi-strategy parallel mode.
                "slot": slot_key or symbol,
                # Track actual entry fee rate so _close_position_internal can compute
                # fees accurately (maker = 0%, taker = 0.01%).
                "entry_fee_rate": 0.0 if use_maker else 0.0001,
            }
            # Day-trading strategies use a shorter max-hold window. Store it in the
            # scores dict so _enforce_max_hold can read it per-position.
            if signal.dominant_strategy in ("orb", "asia_bo"):
                scores["max_hold"] = getattr(self._config.risk, "day_max_hold_candles", 6)
            # FVG / IFVG were validated with a 24-candle max-hold (1-day on 1h).
            elif signal.dominant_strategy in ("fvg", "ifvg"):
                scores["max_hold"] = 24

            position = self._portfolio.create_position(
                symbol=setup.symbol,
                direction=signal.direction,
                entry_price=order.filled_price,
                sl_price=setup.sl_price,
                tp_price=setup.tp_price,
                # Use the order's actual filled base size (post contract-step
                # truncation), not the pre-rounding setup size, so the portfolio
                # matches the real exchange position exactly.
                quantity=order.quantity,
                strategy_scores=scores,
                is_paper=self._config.exchange.paper_mode,
                position_id=order.order_id,  # unify portfolio/paper/DB id
            )

        trade_rec = TradeRecord(
            id=position.id,
            symbol=setup.symbol,
            side=position.side,
            entry_price=order.filled_price,
            quantity=order.quantity,
            sl_price=setup.sl_price,
            tp_price=setup.tp_price,
            entry_time=position.entry_time.isoformat(),
            strategy_scores=scores,
            is_paper=self._config.exchange.paper_mode,
        )
        await self._db.log_trade_open(trade_rec)
        await self._persist_balance()

        logger.info(
            "Trade opened: %s %s entry=%.2f sl=%.2f tp=%.2f qty=%.4f risk=%.2f%%",
            position.side.upper(), setup.symbol,
            order.filled_price, setup.sl_price, setup.tp_price,
            setup.quantity, setup.risk_pct * 100,
        )

        setup_copy = TradeSetup(**{k: v for k, v in setup.__dict__.items()})
        setup_copy.entry_price = order.filled_price
        return ExecutionResult(success=True, position=position, trade_setup=setup_copy)

    async def resync_symbol_stops(self, symbol: str) -> bool:
        """Live only: cancel ALL plan (SL/TP) orders for a symbol, then re-place
        the SL/TP for every still-open position on it.

        MEXC nets all same-symbol positions into one, so when several sleeves
        trade the same coin they share one exchange position. To safely move or
        remove ONE sleeve's stop we cancel every plan order for the symbol and
        re-place the stops for the sleeves that remain — so each sibling keeps
        its protection. Uses only the proven cancel-all + place endpoints
        (per-order-id cancel is flagged buggy in ccxt's MEXC driver).

        Returns True if all remaining sleeves' stops were re-placed."""
        async with self._symbol_lock(symbol):
            return await self._resync_symbol_stops_locked(symbol)

    async def _resync_symbol_stops_locked(self, symbol: str) -> bool:
        """resync body — caller must already hold self._symbol_lock(symbol)
        (asyncio.Lock is not re-entrant, so close_position/entry call this
        directly while holding the lock instead of resync_symbol_stops)."""
        if self._config.exchange.paper_mode:
            return True
        if not hasattr(self._exchange, "cancel_stop_orders"):
            return True

        # Fetch the ACTUAL MEXC position size before placing any stop.
        # After a partial external close the portfolio qty may exceed the real
        # exchange qty, causing a reduce-only plan order to be silently rejected
        # (MEXC returns 200 with all-None fields when the requested size > position).
        exch_qty: float | None = None
        if hasattr(self._exchange, "get_position"):
            try:
                exch_pos = await self._exchange.get_position(symbol)
                if exch_pos and exch_pos.contracts:
                    exch_qty = float(exch_pos.contracts)
                else:
                    exch_qty = 0.0
            except Exception as e:
                logger.debug("resync: could not fetch MEXC position for %s: %s", symbol, e)

        # Nothing on the exchange — clear any stale plan orders and return.
        if exch_qty is not None and exch_qty <= 0:
            await self._exchange.cancel_stop_orders(symbol)
            logger.info(
                "resync %s: MEXC position is 0 — skipping stop placement "
                "(position already closed on exchange)", symbol,
            )
            return True

        # Hold the exchange-level stop-order mutex for the entire cancel→place
        # sequence so concurrent resyncs on OTHER symbols (e.g. two max_hold
        # closes firing at the same second) don't interleave and burst MEXC's
        # plan-order rate limit (code 510). set_sl_tp also acquires this mutex,
        # so we call the internal _set_sl_tp_locked directly to avoid deadlock.
        stop_lock = getattr(self._exchange, "_stop_order_lock", None)
        async with (stop_lock if stop_lock is not None else _null_ctx()):
            await self._exchange.cancel_stop_orders(symbol)
            ok = True

            # The entry-attached SL/TP (set on the entry order, position-level) is
            # sticky — it survives cancel_stop_orders and is MEXC's reliable exit
            # mechanism. If it is still present, placing plan (trigger) orders on
            # top would DOUBLE-protect the position (one set in the TP/SL tab, one
            # in the Trigger tab). So when attached protection exists we stop here:
            # the cancel above already cleared any stale plan orders, leaving a
            # single clean layer. Only fall through to plan-order placement when
            # the position has NO attached protection at all (emergency fallback).
            check_fn = getattr(self._exchange, "has_attached_protection", None)
            if check_fn is not None:
                try:
                    if await check_fn(symbol):
                        logger.info(
                            "resync %s: already protected by entry-attached SL/TP — "
                            "skipping plan-order placement (no duplicate Trigger orders)",
                            symbol,
                        )
                        return True
                except Exception as e:
                    logger.debug(
                        "resync %s: protection check failed (%s) — placing plan stops",
                        symbol, e,
                    )

            # When the portfolio total exceeds the real MEXC position (partial
            # external close not yet reconciled), cap each sleeve's stop to its
            # proportional share of the actual exchange qty. This prevents the
            # reduce-only plan order from being silently rejected by MEXC.
            portfolio_positions = [
                p for p in self._portfolio.get_open_positions()
                if p.symbol == symbol and p.sl_price > 0
            ]
            total_portfolio_qty = sum(p.quantity for p in portfolio_positions)

            for pos in portfolio_positions:
                if exch_qty is not None and total_portfolio_qty > 0 and exch_qty < total_portfolio_qty:
                    # Prorate this sleeve's share of the real position
                    stop_qty = pos.quantity * (exch_qty / total_portfolio_qty)
                    stop_qty = round(stop_qty, 6)
                    if stop_qty <= 0:
                        continue
                    logger.warning(
                        "resync %s: capping stop from %.6f → %.6f "
                        "(MEXC position %.6f < portfolio %.6f — partial external close)",
                        symbol, pos.quantity, stop_qty, exch_qty, total_portfolio_qty,
                    )
                else:
                    stop_qty = pos.quantity
                try:
                    set_fn = getattr(self._exchange, "_set_sl_tp_locked",
                                     self._exchange.set_sl_tp)
                    await set_fn(
                        symbol, pos.side, pos.sl_price, pos.tp_price, stop_qty
                    )
                except Exception as e:
                    ok = False
                    logger.critical(
                        "Re-placing stops for %s %s FAILED — may be unprotected: %s",
                        pos.side, symbol, e,
                    )
                    await self._alert(
                        f"⚠️ {symbol} stop yenilenemedi — pozisyon korumasız olabilir!",
                        "ERROR",
                    )

        # Re-protection failed via the plan-order fallback (MEXC's PlanorderPlace
        # endpoint is unreliable). The entry path force-closes a confirmed-naked
        # position rather than leaving it open with only an alert; mirror that
        # here so the resync/restart path is fail-SAFE (flat) instead of
        # fail-OPEN (naked). Only close on a CONFIRMED-naked read (has_sltp_orders
        # returns False, not None) so we never close a position that is actually
        # protected or whose protection state is merely unknown.
        if not ok:
            check = getattr(self._exchange, "has_sltp_orders", None)
            confirmed_naked = False
            if check is not None:
                try:
                    confirmed_naked = (await check(symbol)) is False
                except Exception as e:
                    logger.debug("resync %s: protection re-check failed: %s", symbol, e)
            if confirmed_naked:
                # _close_position_internal is idempotent (id-keyed), so a position
                # already closed by a concurrent path is skipped safely inside it.
                for pos in list(portfolio_positions):
                    try:
                        exit_px = pos.entry_price
                        if hasattr(self._exchange, "close_position"):
                            order = await self._exchange.close_position(
                                pos.symbol, pos.side, pos.quantity, "no_stop_safety"
                            )
                            if order and getattr(order, "filled_price", 0):
                                exit_px = order.filled_price
                        await self._close_position_internal(pos, exit_px, "no_stop_safety")
                        logger.critical(
                            "resync %s: re-protection FAILED and position confirmed "
                            "naked — force-closed %s sleeve for safety",
                            symbol, pos.side,
                        )
                        await self._alert(
                            f"🛡️ {symbol} korumasız kaldı ({pos.side}) — "
                            f"güvenlik için kapatıldı.",
                            "ERROR",
                        )
                    except Exception as e:
                        logger.critical(
                            "resync %s: SAFETY CLOSE FAILED — MANUAL ACTION NEEDED: %s",
                            symbol, e,
                        )
        return ok

    async def close_position(
        self, pos: Position, reason: str, current_price: float
    ) -> bool:
        """Public close for live mode: places a reduce-only market order, then
        records the fill. Paper mode is handled by PaperExchange.close_position."""
        symbol = pos.symbol
        try:
            # Hold the per-symbol lock across close + resync so a concurrent
            # entry/trailing/reconciliation on the same netted symbol can't
            # interleave (e.g. cancel a stop we are about to re-place).
            async with self._symbol_lock(symbol):
                if hasattr(self._exchange, "close_position"):
                    order = await self._exchange.close_position(
                        pos.symbol, pos.side, pos.quantity, reason
                    )
                    exit_price = order.filled_price if order else current_price
                else:
                    exit_price = current_price
                await self._close_position_internal(pos, exit_price, reason)
                # Live: clear this sleeve's leftover SL/TP and re-assert any
                # sibling sleeve's stops still open on the same (netted) symbol.
                if not self._config.exchange.paper_mode:
                    await self._resync_symbol_stops_locked(symbol)
            return True
        except Exception as e:
            logger.error("close_position failed for %s: %s", pos.id, e)
            return False

    async def emergency_close_all(self, reason: str) -> None:
        for pos in list(self._portfolio.get_open_positions()):
            try:
                # For live mode: cancel SL/TP orders first, then send a market
                # close — this is the only path that actually closes on the exchange.
                if not self._config.exchange.paper_mode and hasattr(self._exchange, "_exchange"):
                    inner = self._exchange._exchange
                    try:
                        await inner.cancel_all_orders(pos.symbol)
                    except Exception as ce:
                        logger.error("Could not cancel orders for %s: %s", pos.symbol, ce)
                    # Also cancel MEXC plan orders (SL/TP are placed as plan orders).
                    if hasattr(inner, "contractPrivatePostPlanorderCancelAll"):
                        try:
                            mexc_sym = pos.symbol.split(":")[0].replace("/", "_")
                            await inner.contractPrivatePostPlanorderCancelAll(
                                {"symbol": mexc_sym}
                            )
                        except Exception as ce:
                            logger.debug("Could not cancel plan orders for %s: %s", pos.symbol, ce)
                # Use the public close_position which sends the exchange order.
                current_price = await self._exchange.get_current_price(pos.symbol)
                closed = await self.close_position(pos, reason, current_price)
                if not closed:
                    logger.critical(
                        "EMERGENCY CLOSE FAILED for %s %s — position may remain open on exchange!",
                        pos.symbol, pos.id,
                    )
            except Exception as e:
                logger.error("Emergency close failed for %s: %s", pos.id, e)

    async def _close_position_internal(
        self, pos: Position, exit_price: float, reason: str
    ) -> None:
        # Idempotency guard: several independent tasks can race to close the same
        # position (max-hold force-close, the 2-min reconciliation loop, a Telegram
        # /close, emergency_close_all). Without this guard the trade would be
        # logged to the DB twice and the win/loss streak double-counted (which can
        # wrongly trip the consecutive-loss cooldown). First caller wins.
        if self._portfolio.get_position_by_id(pos.id) is None:
            logger.debug("Position %s already closed — skipping duplicate close", pos.id)
            return
        # A $0 exit fill (missing close price) would book a huge bogus PnL — fall
        # back to the entry so the trade records ~0 PnL instead of a phantom loss.
        if exit_price <= 0:
            logger.warning(
                "Close of %s has no exit price — falling back to entry %.6f",
                pos.id, pos.entry_price,
            )
            exit_price = pos.entry_price
        direction = pos.direction
        raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
        entry_fee_rate = pos.strategy_scores.get("entry_fee_rate", 0.0001)
        fees = (
            pos.entry_price * pos.quantity * entry_fee_rate
            + exit_price * pos.quantity * 0.0001
        )
        net_pnl = raw_pnl - fees
        # pnl_pct is return on the MARGIN actually deployed (notional / leverage),
        # not on full notional — that is what the trader put up. On 10x leverage a
        # 1% notional move is a 10% return on capital; reporting it on notional
        # understated every trade's percentage by the leverage factor.
        lev = max(self._config.exchange.leverage, 1)
        denom = pos.entry_price * pos.quantity / lev
        pnl_pct = net_pnl / denom if denom > 0 else 0.0

        strategy = pos.strategy_scores.get("strategy", "all")
        self._record_trade_outcome(net_pnl, strategy, pos.symbol)
        self._portfolio.remove_position(pos.id)
        await self._db.log_trade_close(
            trade_id=pos.id,
            exit_price=exit_price,
            exit_time=datetime.now(timezone.utc).isoformat(),
            pnl_usdt=net_pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            fees_usdt=fees,
        )
        # Fire close callbacks (dashboard + Telegram/ntfy) so LIVE bot-initiated
        # closes (max-hold, manual /close, emergency, reconciliation) notify
        # exactly once — mirroring the paper path. Paper closes go through
        # _on_paper_position_closed instead and never reach here (the idempotency
        # guard above returns first), so there is no double-notification.
        for cb in self._on_close_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(pos, exit_price, net_pnl, reason)
                else:
                    cb(pos, exit_price, net_pnl, reason)
            except Exception as e:
                logger.error("Close callback error: %s", e)
        return net_pnl

    async def _on_paper_position_closed(
        self, paper_pos, exit_price: float, net_pnl: float, fees: float, reason: str
    ) -> None:
        pos = self._portfolio.get_position_by_id(paper_pos.id)
        if pos is None:
            return
        # Return on deployed margin (notional / leverage), not on full notional —
        # mirrors _close_position_internal so paper and live report consistently.
        lev = max(self._config.exchange.leverage, 1)
        denom = pos.entry_price * pos.quantity / lev
        pnl_pct = net_pnl / denom if denom > 0 else 0.0
        strategy = pos.strategy_scores.get("strategy", "all")
        self._record_trade_outcome(net_pnl, strategy, pos.symbol)
        self._portfolio.remove_position(pos.id)
        await self._db.log_trade_close(
            trade_id=pos.id,
            exit_price=exit_price,
            exit_time=datetime.now(timezone.utc).isoformat(),
            pnl_usdt=net_pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            fees_usdt=fees,
        )
        await self._persist_balance()
        logger.info(
            "Position closed: %s %s exit=%.2f pnl=%.2f reason=%s",
            pos.side.upper(), pos.symbol, exit_price, net_pnl, reason,
        )
        for cb in self._on_close_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(pos, exit_price, net_pnl, reason)
                else:
                    cb(pos, exit_price, net_pnl, reason)
            except Exception as e:
                logger.error("Close callback error: %s", e)
