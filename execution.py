from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
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

        if isinstance(exchange, PaperExchange):
            exchange.register_close_callback(self._on_paper_position_closed)

    def register_close_callback(self, cb: Callable) -> None:
        self._on_close_callbacks.append(cb)

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

    async def execute_signal(
        self, signal: CombinedSignal, atr: float
    ) -> ExecutionResult:
        if self.is_halted():
            return ExecutionResult(False, error="Trading halted (daily loss limit)")

        if signal.direction == 0:
            return ExecutionResult(False, error="No signal")

        # Multi-coin: the signal carries its own symbol; fall back to the
        # configured primary symbol for single-coin operation.
        symbol = signal.symbol or self._config.exchange.symbol

        # One position per symbol — never stack two trades on the same coin.
        if self._portfolio.get_position_for_symbol(symbol) is not None:
            return ExecutionResult(False, error=f"Position already open for {symbol}")

        balance = await self._exchange.get_balance()

        if not self._risk.check_daily_loss_limit(
            self._daily_starting_balance,
            balance,
            self._portfolio.get_total_unrealized_pnl(),
        ):
            self.halt_trading("Daily loss limit reached")
            await self.emergency_close_all("daily_loss_limit")
            return ExecutionResult(False, error="Daily loss limit")

        setup = self._risk.build_trade_setup(
            direction=signal.direction,
            entry_price=signal.entry_price,
            atr=atr,
            balance=balance,
            leverage=self._config.exchange.leverage,
            symbol=symbol,
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
        }

        position = self._portfolio.create_position(
            symbol=setup.symbol,
            direction=signal.direction,
            entry_price=order.filled_price,
            sl_price=setup.sl_price,
            tp_price=setup.tp_price,
            quantity=setup.quantity,
            strategy_scores=scores,
            is_paper=self._config.exchange.paper_mode,
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
        pnl_pct = net_pnl / (pos.entry_price * pos.quantity)

        self._portfolio.remove_position(pos.id)
        await self._db.log_trade_close(
            trade_id=pos.id,
            exit_price=exit_price,
            exit_time=datetime.utcnow().isoformat(),
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
        self._portfolio.remove_position(pos.id)
        await self._db.log_trade_close(
            trade_id=pos.id,
            exit_price=exit_price,
            exit_time=datetime.utcnow().isoformat(),
            pnl_usdt=net_pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            fees_usdt=fees,
        )
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
