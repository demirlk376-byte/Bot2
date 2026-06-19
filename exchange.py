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
        # Use the entry's ACTUAL fee rate (0% for a maker/limit entry, 0.01% for
        # a taker/market entry) plus the taker exit fee — mirrors the live path
        # (execution._close_position_internal). Charging taker on both legs would
        # bill a phantom entry fee on maker entries and drift the paper equity.
        fees = (pos.entry_price * pos.fee_rate
                + exit_price * self.FEE_RATE) * pos.quantity
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
        self._open_type = 1 if margin_mode == "isolated" else 2
        self._exchange = None

    async def initialize(self, symbol: str) -> None:
        # Create the ccxt.pro client ONCE. This is called per-symbol in multi-coin
        # mode to set leverage/margin for each coin; a single client handles all
        # symbols (symbol is passed per call). Re-creating it each time would
        # orphan the previous client → "Unclosed connector" leaks (one per extra
        # coin) on every startup. Guard so only the first call builds the client.
        if self._exchange is None:
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
        # MEXC requires openType (1=isolated, 2=cross) and positionType (1=long,
        # 2=short) for set_leverage; margin mode is implicit in openType so we
        # skip the separate set_margin_mode call which fails with the same error.
        open_type = 1 if self._margin_mode == "isolated" else 2
        for pos_type in (1, 2):  # 1=long, 2=short — must set for each direction
            try:
                await self._exchange.set_leverage(
                    self._leverage, symbol,
                    params={"openType": open_type, "positionType": pos_type},
                )
            except Exception as e:
                logger.debug("set_leverage pos_type=%d %s: %s", pos_type, symbol, e)

    async def get_balance(self) -> float:
        bal = await self._exchange.fetch_balance({"type": "swap"})
        # Defensive: MEXC can transiently return a missing/None free field. Treat
        # it as 0 rather than raising, so a hiccup degrades to "no free margin"
        # (entry skipped) instead of crashing the entry/halt path.
        usdt = bal.get("USDT") or {}
        return float(usdt.get("free") or 0.0)

    def _contract_size(self, symbol: str) -> float:
        """Base-currency units per MEXC contract (e.g. SOL=0.1, BTC=0.0001,
        XRP=1). Falls back to 1.0 if the market isn't loaded yet."""
        try:
            cs = self._exchange.market(symbol).get("contractSize")
            return float(cs) if cs else 1.0
        except Exception:
            return 1.0

    def _to_contracts(self, symbol: str, base_qty: float, round_up: bool = False) -> float:
        """Convert a base-currency quantity (e.g. 1.004 SOL) into the MEXC
        contract count to send to ccxt.

        ccxt's mexc create_order passes `amount` STRAIGHT THROUGH as `vol`
        (the contract count) — it does NOT divide by contractSize despite the
        docstring claiming base-currency units. So a coin whose contractSize is
        not 1 (SOL=0.1, BTC=0.0001, ...) would open contractSize× too small and
        the bot would mis-account every PnL/margin/equity figure by that factor.
        We divide here, then truncate to the contract step so risk never rounds
        upward.

        round_up=True nudges the value up one ulp before truncation so a value
        sitting exactly on a contract step (but stored as 11.9999998 due to float
        error) lands on the intended step. Used for reduce-only SL/TP sizing so a
        stop never covers FEWER contracts than the live position (reduceOnly caps
        the upside, so a tiny over-count is harmless; an under-count leaves part
        of the position unstopped)."""
        cs = self._contract_size(symbol)
        contracts = base_qty / cs if cs > 0 else base_qty
        if round_up:
            contracts *= (1 + 1e-9)
        try:
            return float(self._exchange.amount_to_precision(symbol, contracts))
        except Exception:
            return contracts

    def _to_base(self, symbol: str, contracts: float) -> float:
        """Convert a ccxt contract count back to base-currency units."""
        return contracts * self._contract_size(symbol)

    async def get_position(self, symbol: str) -> Optional[Position]:
        positions = await self._exchange.fetch_positions([symbol])
        for p in positions:
            if float(p.get("contracts", 0)) != 0:
                side = "long" if p["side"] == "long" else "short"
                return Position(
                    symbol=symbol,
                    side=side,
                    # ccxt reports `contracts` as the contract count; convert to
                    # base-currency units so it matches the bot's internal
                    # quantity (which is always base) — the reconciliation loop
                    # compares the two directly.
                    contracts=self._to_base(symbol, float(p["contracts"])),
                    entry_price=float(p["entryPrice"]),
                    unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                    leverage=int(p.get("leverage", self._leverage)),
                )
        return None

    async def place_market_order(
        self, symbol: str, side: str, amount: float, params: dict
    ) -> OrderResult:
        # `amount` is base-currency (e.g. SOL); convert to MEXC contract count.
        contracts = self._to_contracts(symbol, amount)
        # Guard: if the size rounds below one contract step the order is garbage
        # (MEXC would reject or fill 0). Reject here so the caller books a clean
        # error instead of a phantom $0 position. Covers low-priced coins whose
        # base-min differs from BTC's.
        if contracts <= 0:
            raise ValueError(
                f"{symbol}: size {amount} → {contracts} contracts (below min step)"
            )
        # openType must match what was set on set_leverage; without it ccxt defaults
        # to cross (openType=2) regardless of how leverage was configured.
        order_params = {"openType": self._open_type, **params}
        order = await self._exchange.create_order(
            symbol, "market", side, contracts, None, order_params
        )
        filled_price = float(order.get("average") or order.get("price") or 0)

        # MEXC futures sometimes returns average=0 immediately after placement
        # (fill processing is async). Retry fetch once to get actual fill price.
        if filled_price == 0:
            try:
                await asyncio.sleep(1)
                fetched = await self._exchange.fetch_order(str(order["id"]), symbol)
                filled_price = float(
                    fetched.get("average") or fetched.get("price") or
                    fetched.get("info", {}).get("dealAvgPrice") or 0
                )
            except Exception as e:
                logger.debug("fill-price re-fetch failed: %s", e)
        # Secondary fallback: MEXC-specific info fields
        if filled_price == 0:
            filled_price = float(
                order.get("info", {}).get("dealAvgPrice") or
                order.get("info", {}).get("avgPrice") or 0
            )
        # Last resort: the live mark price. A market order fills at ~mark, so this
        # is a faithful proxy for THIS order's fill. We deliberately do NOT fall
        # back to the position's entryPrice: MEXC nets same-symbol positions, so
        # on a multi-sleeve symbol fetch_positions returns the BLENDED entry of
        # all sleeves, which could be materially wrong for this specific order.
        if filled_price == 0:
            try:
                filled_price = await self.get_current_price(symbol)
                logger.warning(
                    "Fill price unavailable for order %s — using mark price %.6f as entry",
                    order.get("id"), filled_price,
                )
            except Exception as e:
                logger.error(
                    "Market order %s filled but price unavailable and mark-price "
                    "fallback failed (%s) — position will show $0 entry",
                    order.get("id"), e,
                )

        return OrderResult(
            order_id=str(order["id"]),
            symbol=symbol,
            side=side,
            filled_price=filled_price,
            # Report the ACTUAL base-currency size that hit the exchange after the
            # contract-step truncation, so the portfolio matches reality exactly.
            quantity=self._to_base(symbol, contracts),
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
        order_params = {"openType": self._open_type, **params}
        order_params["postOnly"] = True
        # `amount` is base-currency; convert to MEXC contract count for ccxt.
        contracts = self._to_contracts(symbol, amount)
        if contracts <= 0:
            raise ValueError(
                f"{symbol}: size {amount} → {contracts} contracts (below min step)"
            )
        try:
            order = await self._exchange.create_order(
                symbol, "limit", side, contracts, limit_price, order_params
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
                    filled_price=filled_price,
                    quantity=self._to_base(symbol, contracts),
                    timestamp=int(time.time() * 1000), is_paper=False,
                )
            if status == "canceled":
                break

        # Unfilled — cancel and decide fallback. We only fall back to a MARKET
        # order if the cancel is CONFIRMED (order definitely did not fill).
        # Otherwise a market fallback on top of a silently-filled limit would
        # DOUBLE the position (and the extra leg has no SL/TP).
        cancelled = False
        try:
            await self._exchange.cancel_order(order_id, symbol)
            cancelled = True
        except Exception as e:
            logger.debug("cancel_order failed (may be filled): %s", e)
            # Re-check: it might have filled between poll and cancel.
            try:
                fetched = await self._exchange.fetch_order(order_id, symbol)
                status = fetched.get("status")
                if status == "closed":
                    fp = float(fetched.get("average") or limit_price)
                    return OrderResult(order_id, symbol, side, fp,
                                       self._to_base(symbol, contracts),
                                       int(time.time() * 1000), False)
                if status == "canceled":
                    cancelled = True
            except Exception:
                # Could neither confirm cancel NOR confirm fill. Firing a market
                # order now risks a double entry, so skip rather than gamble.
                logger.warning(
                    "Limit %s state unknown after cancel failure — skipping market "
                    "fallback to avoid double entry", order_id)
                return None

        if cancelled and fallback_market:
            logger.info("Limit unfilled after %.0fs; falling back to market", timeout)
            return await self.place_market_order(symbol, side, amount, params)
        logger.info("Limit unfilled/uncancelled after %.0fs; skipping trade", timeout)
        return None

    async def close_position(
        self, symbol: str, side: str, amount: float, reason: str = "manual"
    ) -> OrderResult:
        close_side = "sell" if side == "long" else "buy"
        # `amount` is base-currency; convert to MEXC contract count for ccxt.
        contracts = self._to_contracts(symbol, amount)
        order = await self._exchange.create_order(
            symbol, "market", close_side, contracts, None,
            {"reduceOnly": True, "openType": self._open_type},
        )
        filled_price = float(order.get("average") or order.get("price") or 0)
        # Same MEXC async-fill issue as entry: average can be 0 right after the
        # reduce-only close. Re-fetch and fall back to dealAvgPrice, then the
        # mark price, so the caller never books a $0 exit (huge bogus PnL).
        if filled_price == 0:
            try:
                await asyncio.sleep(1)
                fetched = await self._exchange.fetch_order(str(order["id"]), symbol)
                filled_price = float(
                    fetched.get("average") or fetched.get("price") or
                    fetched.get("info", {}).get("dealAvgPrice") or 0
                )
            except Exception as e:
                logger.debug("close fill-price re-fetch failed: %s", e)
        if filled_price == 0:
            filled_price = float(
                order.get("info", {}).get("dealAvgPrice") or
                order.get("info", {}).get("avgPrice") or 0
            )
        if filled_price == 0:
            try:
                filled_price = await self.get_current_price(symbol)
                logger.warning(
                    "Close fill price unavailable for %s — using mark price %.6f",
                    order.get("id"), filled_price,
                )
            except Exception as e:
                logger.error("Close fill price unavailable and mark fallback failed: %s", e)
        return OrderResult(
            order_id=str(order["id"]),
            symbol=symbol,
            side=close_side,
            filled_price=filled_price,
            # Report the ACTUAL closed base-currency size (contracts truncated to
            # the step, converted back), not the requested `amount`. For non-1
            # contractSize coins where `amount` doesn't divide evenly, returning
            # `amount` overstates the close and can leave a dust remainder the
            # reconciliation loop mistakes for a residual sleeve.
            quantity=self._to_base(symbol, contracts),
            timestamp=int(time.time() * 1000),
            is_paper=False,
        )

    async def set_sl_tp(
        self, symbol: str, position_side: str, sl_price: float, tp_price: float,
        amount: float
    ) -> None:
        # MEXC plan orders (trigger/conditional) are placed by passing triggerPrice
        # in params alongside type="market". ccxt routes this to MEXC's
        # contractPrivatePostPlanorderPlace endpoint automatically.
        # orderType=5 → market execution when triggered (not limit, which is default=1).
        # triggerType: 1=price>=trigger (TP long / SL short), 2=price<=trigger (SL long / TP short).
        close_side = "sell" if position_side == "long" else "buy"
        sl_trigger  = 2 if position_side == "long" else 1
        tp_trigger  = 1 if position_side == "long" else 2
        open_type   = 1 if self._margin_mode == "isolated" else 2
        base: dict  = {
            "orderType": 5,     # 5 = market when triggered
            "executeCycle": 1,  # 24-hour validity
            "openType": open_type,
            "reduceOnly": True,
        }
        if open_type == 1:
            base["leverage"] = self._leverage

        # `amount` is base-currency; the plan-order vol is also a contract count.
        # round_up so the reduce-only stop never covers fewer contracts than the
        # live position (float-truncation could otherwise leave a sliver unstopped).
        contracts = self._to_contracts(symbol, amount, round_up=True)

        sl_ok = False
        try:
            sl_resp = await self._exchange.create_order(
                symbol, "market", close_side, contracts, None,
                {**base, "triggerPrice": sl_price, "triggerType": sl_trigger},
            )
            # Confirm the plan order actually rests: MEXC can return a success
            # envelope WITHOUT placing the order (business error inside a 200 that
            # ccxt doesn't raise on). An order id in the response means it was
            # accepted. Treating create_order's mere return as success would leave
            # a live position the bot believes is stopped but isn't.
            sl_ok = bool(sl_resp and (sl_resp.get("id") or
                                      sl_resp.get("info", {}).get("orderId")))
            if not sl_ok:
                logger.error("SL order returned no id (silent reject): %r", sl_resp)
        except Exception as e:
            logger.error("SL order failed: %s", e)
        tp_ok = False
        try:
            tp_resp = await self._exchange.create_order(
                symbol, "market", close_side, contracts, None,
                {**base, "triggerPrice": tp_price, "triggerType": tp_trigger},
            )
            tp_ok = bool(tp_resp and (tp_resp.get("id") or
                                      tp_resp.get("info", {}).get("orderId")))
            if not tp_ok:
                logger.error("TP order returned no id (silent reject): %r", tp_resp)
        except Exception as e:
            logger.error("TP order failed: %s", e)
        if not sl_ok:
            raise RuntimeError(f"SL placement failed for {symbol} — position will be closed")
        if not tp_ok:
            # SL protects the downside, so we do NOT force-close (that would book a
            # guaranteed fee loss). But the validated edge (esp. ORB/Asia) assumes a
            # fixed TP, so surface this loudly: the position will exit via
            # max-hold/trailing instead of the intended take-profit.
            logger.error(
                "TP placement FAILED for %s (SL IS in place) — position will exit "
                "via max-hold/trailing, not the intended take-profit", symbol)

    async def cancel_stop_orders(self, symbol: str) -> bool:
        """Cancel all pending SL/TP plan (trigger) orders for a symbol. Returns
        True if the cancel call succeeded (or there was nothing to cancel).

        SL/TP are placed as MEXC plan orders, which the regular cancel endpoint
        does not cover — they need contractPrivatePostPlanorderCancelAll. This is
        used both when reconciling an externally-closed position (to clear the
        leftover opposite-side trigger) and before moving a trailing stop."""
        inner = self._exchange
        ok = True
        try:
            await inner.cancel_all_orders(symbol)
        except Exception as e:
            logger.debug("cancel_all_orders failed for %s: %s", symbol, e)
        if hasattr(inner, "contractPrivatePostPlanorderCancelAll"):
            try:
                mexc_sym = symbol.split(":")[0].replace("/", "_")
                await inner.contractPrivatePostPlanorderCancelAll({"symbol": mexc_sym})
            except Exception as e:
                logger.error("Could not cancel plan orders for %s: %s", symbol, e)
                ok = False
        return ok

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
