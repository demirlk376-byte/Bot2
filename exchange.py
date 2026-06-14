from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    filled_price: float
    quantity: float
    timestamp: int
    is_paper: bool


@dataclass
class Position:
    symbol: str
    side: str          # 'long' | 'short'
    contracts: float   # BTC amount
    entry_price: float
    unrealized_pnl: float = 0.0
    leverage: int = 10


class ExchangeInterface(Protocol):
    async def get_balance(self) -> float: ...
    async def get_position(self, symbol: str) -> Optional[Position]: ...
    async def place_market_order(
        self, symbol: str, side: str, amount: float, params: dict
    ) -> OrderResult: ...
    async def close_position(
        self, symbol: str, side: str, amount: float
    ) -> OrderResult: ...
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int], limit: int
    ) -> list[list]: ...
    async def get_current_price(self, symbol: str) -> float: ...
    async def watch_ticker(self, symbol: str) -> dict: ...


# ---------------------------------------------------------------------------
# Paper Exchange
# ---------------------------------------------------------------------------

@dataclass
class _PaperPosition:
    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    sl_price: float
    tp_price: float
    margin_used: float
    leverage: int
    fee_rate: float = 0.0001
    closed: bool = False
    exit_price: float = 0.0
    exit_reason: str = ""


class PaperExchange:
    FEE_RATE = 0.0001       # taker fee (market orders)
    FEE_MAKER = 0.0         # maker fee (limit/post-only orders) — MEXC futures maker = 0%
    SLIPPAGE = 0.0005

    def __init__(self, initial_balance: float, leverage: int = 10):
        self._balance = initial_balance
        self._leverage = leverage
        self._positions: dict[str, _PaperPosition] = {}
        self._order_history: list[OrderResult] = []
        self._current_price: float = 0.0          # last single-symbol price (fallback)
        self._prices: dict[str, float] = {}        # per-symbol prices (multi-coin)
        self._price_lock = asyncio.Lock()
        self._close_callbacks: list = []
        self._rest_exchange = None  # set by DataManager for OHLCV

    def set_rest_exchange(self, exchange) -> None:
        self._rest_exchange = exchange

    def set_balance(self, balance: float) -> None:
        """Restore a persisted balance after a restart."""
        self._balance = balance

    def restore_position(
        self, pos_id: str, symbol: str, side: str, quantity: float,
        entry_price: float, sl_price: float, tp_price: float,
    ) -> None:
        """Rebuild an open paper position after a restart. The margin was already
        deducted (and is reflected in the persisted balance), so we only recreate
        the object — we do NOT touch the balance here."""
        margin = (entry_price * quantity) / self._leverage
        self._positions[pos_id] = _PaperPosition(
            id=pos_id, symbol=symbol, side=side, quantity=quantity,
            entry_price=entry_price, sl_price=sl_price, tp_price=tp_price,
            margin_used=margin, leverage=self._leverage,
        )

    async def update_price(self, price: float, symbol: str | None = None) -> None:
        async with self._price_lock:
            self._current_price = price
            if symbol is not None:
                self._prices[symbol] = price

    def _price_for(self, symbol: str) -> float:
        """Per-symbol price, falling back to the last single price (single-coin)."""
        return self._prices.get(symbol, self._current_price)

    async def get_balance(self) -> float:
        return self._balance

    async def get_position(self, symbol: str) -> Optional[Position]:
        for pos in self._positions.values():
            if pos.symbol == symbol and not pos.closed:
                return Position(
                    symbol=pos.symbol,
                    side=pos.side,
                    contracts=pos.quantity,
                    entry_price=pos.entry_price,
                    unrealized_pnl=self._calc_unrealized(pos),
                    leverage=pos.leverage,
                )
        return None

    def get_open_positions(self) -> list[_PaperPosition]:
        return [p for p in self._positions.values() if not p.closed]

    async def place_market_order(
        self, symbol: str, side: str, amount: float, params: dict
    ) -> OrderResult:
        direction = 1 if side == "buy" else -1
        fill_price = self._price_for(symbol) * (1 + direction * self.SLIPPAGE)
        fee = fill_price * amount * self.FEE_RATE
        margin = (fill_price * amount) / self._leverage
        self._balance -= margin + fee

        pos_id = str(uuid.uuid4())
        pos = _PaperPosition(
            id=pos_id,
            symbol=symbol,
            side="long" if side == "buy" else "short",
            quantity=amount,
            entry_price=fill_price,
            sl_price=params.get("stopLossPrice", 0.0),
            tp_price=params.get("takeProfitPrice", 0.0),
            margin_used=margin,
            leverage=self._leverage,
        )
        self._positions[pos_id] = pos

        result = OrderResult(
            order_id=pos_id,
            symbol=symbol,
            side=side,
            filled_price=fill_price,
            quantity=amount,
            timestamp=int(time.time() * 1000),
            is_paper=True,
        )
        self._order_history.append(result)
        logger.info(
            "PAPER %s %s qty=%.4f price=%.2f margin=%.2f",
            side.upper(), symbol, amount, fill_price, margin,
        )
        return result

    async def place_limit_order(
        self, symbol: str, side: str, amount: float, limit_price: float, params: dict
    ) -> OrderResult:
        """Maker entry: fill at the limit price with no slippage and the maker
        fee (0% on MEXC futures). In paper mode we assume the resting limit at
        the just-closed price fills, which mirrors the backtest's maker model."""
        fill_price = limit_price
        fee = fill_price * amount * self.FEE_MAKER
        margin = (fill_price * amount) / self._leverage
        self._balance -= margin + fee

        pos_id = str(uuid.uuid4())
        pos = _PaperPosition(
            id=pos_id,
            symbol=symbol,
            side="long" if side == "buy" else "short",
            quantity=amount,
            entry_price=fill_price,
            sl_price=params.get("stopLossPrice", 0.0),
            tp_price=params.get("takeProfitPrice", 0.0),
            margin_used=margin,
            leverage=self._leverage,
            fee_rate=self.FEE_MAKER,
        )
        self._positions[pos_id] = pos

        result = OrderResult(
            order_id=pos_id, symbol=symbol, side=side,
            filled_price=fill_price, quantity=amount,
            timestamp=int(time.time() * 1000), is_paper=True,
        )
        self._order_history.append(result)
        logger.info(
            "PAPER LIMIT %s %s qty=%.4f price=%.2f margin=%.2f (maker)",
            side.upper(), symbol, amount, fill_price, margin,
        )
        return result

    async def close_position(
        self, symbol: str, side: str, amount: float, reason: str = "manual"
    ) -> Optional[OrderResult]:
        for pos in self.get_open_positions():
            if pos.symbol == symbol:
                return await self._close_paper_position(
                    pos, self._price_for(symbol), reason
                )
        return None

    async def check_sl_tp(
        self, candle_high: float, candle_low: float, symbol: str | None = None
    ) -> None:
        """Check SL/TP against a just-closed candle. If `symbol` is given, only
        that symbol's positions are checked (multi-coin); otherwise all (single)."""
        for pos in list(self.get_open_positions()):
            if symbol is not None and pos.symbol != symbol:
                continue
            triggered = False
            exit_price = 0.0
            reason = ""

            if pos.side == "long":
                if pos.sl_price > 0 and candle_low <= pos.sl_price:
                    exit_price = pos.sl_price
                    reason = "sl_hit"
                    triggered = True
                elif pos.tp_price > 0 and candle_high >= pos.tp_price:
                    exit_price = pos.tp_price
                    reason = "tp_hit"
                    triggered = True
            else:  # short
                if pos.sl_price > 0 and candle_high >= pos.sl_price:
                    exit_price = pos.sl_price
                    reason = "sl_hit"
                    triggered = True
                elif pos.tp_price > 0 and candle_low <= pos.tp_price:
                    exit_price = pos.tp_price
                    reason = "tp_hit"
                    triggered = True

            if triggered:
                await self._close_paper_position(pos, exit_price, reason)

    async def check_sl_tp_tick(self, symbol: str, price: float) -> None:
        """Tick-level SL/TP check against the live price. Called on every ticker
        update so an exit fires within seconds instead of waiting for the 1h
        candle to close (which could be up to an hour late)."""
        if price <= 0:
            return
        for pos in list(self.get_open_positions()):
            if pos.symbol != symbol:
                continue
            exit_price = 0.0
            reason = ""
            if pos.side == "long":
                if pos.sl_price > 0 and price <= pos.sl_price:
                    exit_price, reason = pos.sl_price, "sl_hit"
                elif pos.tp_price > 0 and price >= pos.tp_price:
                    exit_price, reason = pos.tp_price, "tp_hit"
            else:  # short
                if pos.sl_price > 0 and price >= pos.sl_price:
                    exit_price, reason = pos.sl_price, "sl_hit"
                elif pos.tp_price > 0 and price <= pos.tp_price:
                    exit_price, reason = pos.tp_price, "tp_hit"
            if reason:
                await self._close_paper_position(pos, exit_price, reason)

    async def _close_paper_position(
        self, pos: _PaperPosition, exit_price: float, reason: str
    ) -> OrderResult:
        direction = 1 if pos.side == "long" else -1
        raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
        fees = (pos.entry_price + exit_price) * pos.quantity * self.FEE_RATE
        net_pnl = raw_pnl - fees
        self._balance += pos.margin_used + net_pnl

        pos.closed = True
        pos.exit_price = exit_price
        pos.exit_reason = reason

        logger.info(
            "PAPER CLOSE %s pos=%s exit=%.2f pnl=%.2f reason=%s",
            pos.symbol, pos.side, exit_price, net_pnl, reason,
        )

        for cb in self._close_callbacks:
            asyncio.create_task(cb(pos, exit_price, net_pnl, fees, reason))

        return OrderResult(
            order_id=pos.id,
            symbol=pos.symbol,
            side="sell" if pos.side == "long" else "buy",
            filled_price=exit_price,
            quantity=pos.quantity,
            timestamp=int(time.time() * 1000),
            is_paper=True,
        )

    def update_position_sl(self, position_id: str, new_sl: float) -> None:
        """Sync a trailing-stop SL update into the paper position so that the
        next call to check_sl_tp / check_sl_tp_tick fires at the new price."""
        pos = self._positions.get(position_id)
        if pos is not None and not pos.closed:
            pos.sl_price = new_sl

    def register_close_callback(self, cb) -> None:
        self._close_callbacks.append(cb)

    def _calc_unrealized(self, pos: _PaperPosition) -> float:
        direction = 1 if pos.side == "long" else -1
        return direction * (self._price_for(pos.symbol) - pos.entry_price) * pos.quantity

    def get_total_unrealized_pnl(self) -> float:
        return sum(self._calc_unrealized(p) for p in self.get_open_positions())

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int], limit: int
    ) -> list[list]:
        if self._rest_exchange is None:
            raise RuntimeError("PaperExchange: rest_exchange not set")
        return await self._rest_exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

    async def get_current_price(self, symbol: str) -> float:
        return self._price_for(symbol)

    async def watch_ticker(self, symbol: str) -> dict:
        if self._rest_exchange is None:
            raise RuntimeError("PaperExchange: rest_exchange not set")
        return await self._rest_exchange.watch_ticker(symbol)


# ---------------------------------------------------------------------------
# Live Exchange (ccxt.pro MEXC)
# ---------------------------------------------------------------------------

class LiveExchange:
    def __init__(self, api_key: str, api_secret: str, leverage: int = 10,
                 margin_mode: str = "isolated"):
        self._api_key = api_key
        self._api_secret = api_secret
        self._leverage = leverage
        self._margin_mode = margin_mode
        self._exchange = None

    async def initialize(self, symbol: str) -> None:
        try:
            import ccxt.pro as ccxtpro
        except ImportError:
            raise RuntimeError("ccxt[pro] not installed. Run: pip install 'ccxt[pro]'")

        self._exchange = ccxtpro.mexc({
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "options": {
                "defaultType": "swap",
                "defaultSubType": "linear",
            },
            "enableRateLimit": True,
        })
        await self._exchange.load_markets()
        try:
            await self._exchange.set_leverage(self._leverage, symbol)
            await self._exchange.set_margin_mode(self._margin_mode, symbol)
        except Exception as e:
            logger.warning("Could not set leverage/margin_mode: %s", e)

    async def get_balance(self) -> float:
        bal = await self._exchange.fetch_balance({"type": "swap"})
        return float(bal["USDT"]["free"])

    async def get_position(self, symbol: str) -> Optional[Position]:
        positions = await self._exchange.fetch_positions([symbol])
        for p in positions:
            if float(p.get("contracts", 0)) != 0:
                side = "long" if p["side"] == "long" else "short"
                return Position(
                    symbol=symbol,
                    side=side,
                    contracts=float(p["contracts"]),
                    entry_price=float(p["entryPrice"]),
                    unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                    leverage=int(p.get("leverage", self._leverage)),
                )
        return None

    async def place_market_order(
        self, symbol: str, side: str, amount: float, params: dict
    ) -> OrderResult:
        order = await self._exchange.create_order(
            symbol, "market", side, amount, None, params
        )
        filled_price = float(order.get("average") or order.get("price") or 0)
        return OrderResult(
            order_id=str(order["id"]),
            symbol=symbol,
            side=side,
            filled_price=filled_price,
            quantity=amount,
            timestamp=int(time.time() * 1000),
            is_paper=False,
        )

    async def place_limit_order(
        self, symbol: str, side: str, amount: float, limit_price: float,
        params: dict, timeout: float = 45.0, poll: float = 3.0,
        fallback_market: bool = True,
    ) -> Optional[OrderResult]:
        """Post-only (maker) limit entry. Places a passive limit at limit_price,
        polls for fill up to `timeout` seconds. If unfilled, cancels and either
        falls back to a market order (taker) or returns None to skip the trade.

        Maker entries pay 0% fee on MEXC futures vs 0.01% taker — over a year
        this is worth several percent of return (see research_maximize.py)."""
        order_params = dict(params)
        order_params["postOnly"] = True
        try:
            order = await self._exchange.create_order(
                symbol, "limit", side, amount, limit_price, order_params
            )
        except Exception as e:
            logger.warning("Post-only limit rejected (%s); using market", e)
            if fallback_market:
                return await self.place_market_order(symbol, side, amount, params)
            return None

        order_id = str(order["id"])
        waited = 0.0
        while waited < timeout:
            await asyncio.sleep(poll)
            waited += poll
            try:
                fetched = await self._exchange.fetch_order(order_id, symbol)
            except Exception as e:
                logger.debug("fetch_order failed: %s", e)
                continue
            status = fetched.get("status")
            if status == "closed":
                filled_price = float(
                    fetched.get("average") or fetched.get("price") or limit_price
                )
                logger.info("Maker limit filled: %s @ %.2f", symbol, filled_price)
                return OrderResult(
                    order_id=order_id, symbol=symbol, side=side,
                    filled_price=filled_price, quantity=amount,
                    timestamp=int(time.time() * 1000), is_paper=False,
                )
            if status == "canceled":
                break

        # Unfilled — cancel and decide fallback
        try:
            await self._exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.debug("cancel_order failed (may be filled): %s", e)
            # Re-check: it might have filled between poll and cancel
            try:
                fetched = await self._exchange.fetch_order(order_id, symbol)
                if fetched.get("status") == "closed":
                    fp = float(fetched.get("average") or limit_price)
                    return OrderResult(order_id, symbol, side, fp, amount,
                                       int(time.time() * 1000), False)
            except Exception:
                pass

        if fallback_market:
            logger.info("Limit unfilled after %.0fs; falling back to market", timeout)
            return await self.place_market_order(symbol, side, amount, params)
        logger.info("Limit unfilled after %.0fs; skipping trade", timeout)
        return None

    async def close_position(
        self, symbol: str, side: str, amount: float, reason: str = "manual"
    ) -> OrderResult:
        close_side = "sell" if side == "long" else "buy"
        order = await self._exchange.create_order(
            symbol, "market", close_side, amount, None, {"reduceOnly": True}
        )
        filled_price = float(order.get("average") or order.get("price") or 0)
        return OrderResult(
            order_id=str(order["id"]),
            symbol=symbol,
            side=close_side,
            filled_price=filled_price,
            quantity=amount,
            timestamp=int(time.time() * 1000),
            is_paper=False,
        )

    async def set_sl_tp(
        self, symbol: str, position_side: str, sl_price: float, tp_price: float,
        amount: float
    ) -> None:
        close_side = "sell" if position_side == "long" else "buy"
        try:
            await self._exchange.create_order(
                symbol, "stop_market", close_side, amount, None,
                {"stopPrice": sl_price, "reduceOnly": True},
            )
        except Exception as e:
            logger.warning("SL order failed: %s", e)
        try:
            await self._exchange.create_order(
                symbol, "take_profit_market", close_side, amount, None,
                {"stopPrice": tp_price, "reduceOnly": True},
            )
        except Exception as e:
            logger.warning("TP order failed: %s", e)

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int], limit: int
    ) -> list[list]:
        return await self._exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

    async def get_current_price(self, symbol: str) -> float:
        ticker = await self._exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    async def watch_ticker(self, symbol: str) -> dict:
        return await self._exchange.watch_ticker(symbol)

    async def close(self) -> None:
        if self._exchange:
            await self._exchange.close()
