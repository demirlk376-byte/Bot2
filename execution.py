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
        self._consecutive_losses: int = 0
        self._cooldown_until: Optional[datetime] = None

        if isinstance(exchange, PaperExchange):
            exchange.register_close_callback(self._on_paper_position_closed)

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

    def reset_daily(self) -> None:
        self._trading_halted.clear()

    def resume_trading(self) -> None:
        """Manually clear a halt (e.g. via Telegram /resume)."""
        self._trading_halted.clear()
        logger.info("Trading RESUMED (manual)")

    def _record_trade_outcome(self, net_pnl: float) -> None:
        """Track consecutive losses; start a cooldown when the limit is hit."""
        limit = getattr(self._config.risk, "consecutive_loss_limit", 2)
        cooldown_min = getattr(self._config.risk, "cooldown_minutes", 240)
        if net_pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= limit:
                self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_min)
                logger.warning(
                    "Consecutive losses: %d — cooldown until %s",
                    self._consecutive_losses, self._cooldown_until.strftime("%H:%M UTC"),
                )
                asyncio.create_task(self._alert(
                    f"Üst üste {self._consecutive_losses} kayıp — "
                    f"{cooldown_min} dk cooldown başladı",
                    "WARNING",
                ))
        else:
            self._consecutive_losses = 0

    async def execute_signal(
        self, signal: CombinedSignal, atr: float
    ) -> ExecutionResult:
        if self.is_halted():
            return ExecutionResult(False, error="Trading halted (daily loss limit)")

        if self._cooldown_until is not None:
            if datetime.now(timezone.utc) < self._cooldown_until:
                remaining = (self._cooldown_until - datetime.now(timezone.utc)).total_seconds() / 60
                return ExecutionResult(False, error=f"Cooldown active ({remaining:.0f}m remaining)")
            else:
                self._cooldown_until = None

        if signal.direction == 0:
            return ExecutionResult(False, error="No signal")

        # Multi-coin: the signal carries its own symbol; fall back to the
        # configured primary symbol for single-coin operation.
        symbol = signal.symbol or self._config.exchange.symbol

        # Slot key: each strategy sleeve has its own slot so BB, ORB, and Asia BO
        # can run in parallel without blocking one another. S/R breakout shares the
        # BB slot (both are 48h swing trades — only one at a time makes sense).
        slot_key = signal.position_slot or symbol

        # Check both the portfolio AND an in-flight guard: asyncio yields between
        # the portfolio check and portfolio.create_position, so two concurrent
        # signal handlers for the same slot could both pass the first check.
        if self._portfolio.get_position_for_slot(slot_key) is not None:
            return ExecutionResult(False, error=f"Slot '{slot_key}' already occupied")
        if slot_key in self._executing:
            return ExecutionResult(False, error=f"Execution in progress for slot '{slot_key}'")
        self._executing.add(slot_key)
        try:
            return await self._execute_signal_inner(signal, atr, symbol, slot_key)
        finally:
            self._executing.discard(slot_key)

    async def _execute_signal_inner(
        self, signal: CombinedSignal, atr: float, symbol: str, slot_key: str = ""
    ) -> "ExecutionResult":
        balance = await self._exchange.get_balance()

        if not self._risk.check_daily_loss_limit(
            self._daily_starting_balance,
            balance,
            self._portfolio.get_total_unrealized_pnl(),
        ):
            self.halt_trading("Daily loss limit reached")
            await self.emergency_close_all("daily_loss_limit")
            loss_pct = (
                (self._daily_starting_balance - balance) / self._daily_starting_balance
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
            elif signal.dominant_strategy == "asia_bo":
                risk_override = getattr(self._config.risk, "asia_risk_pct",
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
            return ExecutionResult(False, error="Could not build trade setup")

        ok, reason = self._risk.validate_new_trade(
            setup, self._portfolio.get_open_position_count()
        )
        if not ok:
            return ExecutionResult(False, error=reason)

        side = "buy" if signal.direction == 1 else "sell"
        # PaperExchange reads SL/TP from the order params (check_sl_tp). For live,
        # attaching SL/TP via create_order params is unreliable on MEXC, so we
        # send a clean entry and place dedicated reduce-only SL/TP orders after
        # the fill (see set_sl_tp call below).
        if self._config.exchange.paper_mode:
            params = {
                "stopLossPrice": setup.sl_price,
                "takeProfitPrice": setup.tp_price,
            }
        else:
            params = {}

        # Maker entry: place a post-only limit at the signal price to pay 0% fee
        # instead of 0.01% taker. Over a year this is worth several % of return
        # (see research_maximize.py). Falls back to market if unfilled.
        use_maker = (
            getattr(self._config.exchange, "maker_entry", False)
            and hasattr(self._exchange, "place_limit_order")
        )
        try:
            if use_maker:
                order: Optional[OrderResult] = await self._exchange.place_limit_order(
                    setup.symbol, side, setup.quantity, setup.entry_price, params
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

        # Live mode: place dedicated SL/TP orders. A live position must never sit
        # without a stop — if placement fails, close immediately for safety.
        if not self._config.exchange.paper_mode and hasattr(self._exchange, "set_sl_tp"):
            pos_side = "long" if signal.direction == 1 else "short"
            try:
                await self._exchange.set_sl_tp(
                    setup.symbol, pos_side,
                    setup.sl_price, setup.tp_price, setup.quantity,
                )
                logger.info(
                    "Live SL/TP placed: sl=%.2f tp=%.2f", setup.sl_price, setup.tp_price
                )
            except Exception as e:
                logger.error("SL/TP placement failed — closing position for safety: %s", e)
                try:
                    await self._exchange.close_position(
                        setup.symbol, pos_side, setup.quantity, "no_stop_safety"
                    )
                except Exception as ce:
                    logger.critical("EMERGENCY: could not close unprotected position: %s", ce)
                return ExecutionResult(False, error="SL/TP placement failed; position closed")

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
        }
        # Day-trading strategies use a shorter max-hold window. Store it in the
        # scores dict so _enforce_max_hold can read it per-position.
        if signal.dominant_strategy in ("orb", "asia_bo"):
            scores["max_hold"] = getattr(self._config.risk, "day_max_hold_candles", 6)

        position = self._portfolio.create_position(
            symbol=setup.symbol,
            direction=signal.direction,
            entry_price=order.filled_price,
            sl_price=setup.sl_price,
            tp_price=setup.tp_price,
            quantity=setup.quantity,
            strategy_scores=scores,
            is_paper=self._config.exchange.paper_mode,
            position_id=order.order_id,  # unify portfolio/paper/DB id
        )

        trade_rec = TradeRecord(
            id=position.id,
            symbol=setup.symbol,
            side=position.side,
            entry_price=order.filled_price,
            quantity=setup.quantity,
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

    async def close_position(
        self, pos: Position, reason: str, current_price: float
    ) -> bool:
        """Public close for live mode: places a reduce-only market order, then
        records the fill. Paper mode is handled by PaperExchange.close_position."""
        try:
            if hasattr(self._exchange, "close_position"):
                order = await self._exchange.close_position(
                    pos.symbol, pos.side, pos.quantity, reason
                )
                exit_price = order.filled_price if order else current_price
            else:
                exit_price = current_price
            await self._close_position_internal(pos, exit_price, reason)
            return True
        except Exception as e:
            logger.error("close_position failed for %s: %s", pos.id, e)
            return False

    async def emergency_close_all(self, reason: str) -> None:
        for pos in list(self._portfolio.get_open_positions()):
            try:
                current_price = await self._exchange.get_current_price(pos.symbol)
                await self._close_position_internal(pos, current_price, reason)
            except Exception as e:
                logger.error("Emergency close failed for %s: %s", pos.id, e)

    async def _close_position_internal(
        self, pos: Position, exit_price: float, reason: str
    ) -> None:
        direction = pos.direction
        raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
        fees = (pos.entry_price + exit_price) * pos.quantity * 0.0001
        net_pnl = raw_pnl - fees
        denom = pos.entry_price * pos.quantity
        pnl_pct = net_pnl / denom if denom > 0 else 0.0

        self._record_trade_outcome(net_pnl)
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

    async def _on_paper_position_closed(
        self, paper_pos, exit_price: float, net_pnl: float, fees: float, reason: str
    ) -> None:
        pos = self._portfolio.get_position_by_id(paper_pos.id)
        if pos is None:
            return
        pnl_pct = net_pnl / (pos.entry_price * pos.quantity) if pos.quantity > 0 else 0.0
        self._record_trade_outcome(net_pnl)
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
