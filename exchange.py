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
    # True only when the fill actually executed as a post-only maker limit.
    # The entry fee rate must be keyed off THIS, not off the maker ATTEMPT —
    # place_limit_order falls back to a market (taker) fill on rejection or
    # timeout, and booking those at 0% overstated PnL (audit finding).
    was_maker: bool = False


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
        margin = (fill_price * amount) / self._leverage
        # Deduct ONLY margin here. Fees (entry via pos.fee_rate + exit taker)
        # are charged once, inside net_pnl at close — deducting the entry fee
        # here too double-charged every taker entry (audit fix): the paper
        # balance drifted below initial + SUM(pnl_usdt) from the trades table.
        self._balance -= margin

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
        self, symbol: str, side: str, amount: float, limit_price: float, params: dict,
        fallback_market: bool = True,
    ) -> OrderResult:
        """Maker entry: fill at the limit price with no slippage and the maker
        fee (0% on MEXC futures). In paper mode we assume the resting limit at
        the just-closed price fills, which mirrors the backtest's maker model."""
        fill_price = limit_price
        margin = (fill_price * amount) / self._leverage
        # Only margin — all fees are charged once at close via pos.fee_rate
        # (0 for this maker path). See place_market_order (audit fix).
        self._balance -= margin

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
            was_maker=True,
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
        # Paper allows multiple sleeves per symbol; matching on symbol alone
        # closed whichever position iterated first (e.g. an ORB max-hold could
        # close the BB swing 36h early and corrupt both sleeves' paper stats —
        # audit fix). Match side too and pick the closest-quantity position.
        cands = [p for p in self.get_open_positions()
                 if p.symbol == symbol and p.side == side]
        if not cands:  # fall back: symbol-only (legacy callers / side unknown)
            cands = [p for p in self.get_open_positions() if p.symbol == symbol]
        if not cands:
            return None
        pos = min(cands, key=lambda p: abs(p.quantity - amount))
        return await self._close_paper_position(
            pos, self._price_for(symbol), reason
        )

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
        # Global mutex for plan-order (SL/TP) operations. MEXC's futures plan-order
        # endpoint has a strict per-second rate limit: concurrent cancel+place bursts
        # from multiple symbols closing simultaneously reliably hit code 510. Allowing
        # only ONE symbol's stop operations at a time (cancel → SL → TP) prevents
        # the burst entirely without adding arbitrary sleeps.
        self._stop_order_lock = asyncio.Lock()

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
            # ccxt's load_markets() calls fetch_currencies(), which on MEXC hits the
            # SPOT-private endpoint spotPrivateGetCapitalConfigGetall. A futures-only
            # API key has no spot-wallet permission, so that call fails with
            # code 10072 "Api key info invalid" and crashes startup before any trade.
            # We only trade USDT-M swaps — the currency list is unnecessary — so skip
            # the private currency fetch. Swap markets still load via the public
            # markets endpoint.
            self._exchange.has["fetchCurrencies"] = False
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

    async def get_equity(self) -> float:
        """True account equity straight from MEXC (cash + locked margin +
        unrealized PnL). Used for the daily-loss limit so it measures the real
        account drawdown instead of a reconstructed free+margin+uPnL figure that
        can drift from the exchange. Returns 0.0 only if NOTHING is readable."""
        try:
            bal = await self._exchange.fetch_balance({"type": "swap"})
        except Exception as e:
            logger.debug("get_equity fetch_balance failed: %s", e)
            return 0.0
        # MEXC returns native account equity in the raw payload. `data` may be a
        # dict (single account) or a list of per-asset dicts — handle both.
        info = bal.get("info") or {}
        data = info.get("data")
        candidates = []
        if isinstance(data, dict):
            candidates.append(data)
        elif isinstance(data, list):
            candidates.extend(d for d in data if isinstance(d, dict))
        for d in candidates:
            # Only trust the USDT asset's equity (or a single-account payload).
            if d.get("currency") not in (None, "USDT"):
                continue
            for key in ("equity", "accountEquity", "totalEquity"):
                v = d.get(key)
                if v is not None:
                    try:
                        eq = float(v)
                        if eq > 0:
                            return eq
                    except (TypeError, ValueError):
                        pass
        # Fallback to ccxt's normalized total = free + used (locked margin). This
        # is authoritative from the exchange and INCLUDES locked margin, so it
        # stays correct even if the bot's portfolio is momentarily empty (e.g.
        # right after a restart before positions are restored). It omits unrealized
        # PnL, but the 35% daily-loss buffer easily absorbs that. Returning free
        # alone here was the bug that false-tripped the daily-loss halt: locked
        # margin read as a total-account loss.
        usdt = bal.get("USDT") or {}
        total = usdt.get("total")
        if total is not None:
            try:
                t = float(total)
                if t > 0:
                    return t
            except (TypeError, ValueError):
                pass
        return 0.0

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

    def _round_sltp_params(self, symbol: str, params: dict) -> dict:
        """ccxt applies price_to_precision only to triggerPrice, NOT to the
        stopLossPrice/takeProfitPrice we attach to the entry order (they ride
        through untouched to MEXC's OrderCreate). Round them to the symbol's
        price tick ourselves so MEXC doesn't reject an off-tick stop price."""
        for k in ("stopLossPrice", "takeProfitPrice"):
            v = params.get(k)
            if v:
                try:
                    params[k] = float(self._exchange.price_to_precision(symbol, v))
                except Exception:
                    pass
        return params

    async def has_sltp_orders(self, symbol: str) -> Optional[bool]:
        """Verify a position has resting SL/TP stop orders on MEXC.

        Returns True if at least one stop/trigger order exists, False if it is
        confirmed there are none (a read succeeded and came back empty), and
        None if it could not be determined (every read failed). Used right after
        an entry to confirm the entry-attached SL/TP actually rests before
        trusting the position is protected. MEXC's separate plan-order PLACE
        endpoint is broken, but these GET/list endpoints still work."""
        inner = self._exchange
        mexc_sym = symbol.split(":")[0].replace("/", "_")
        determined = False
        for method in ("contractPrivateGetStoporderOpenOrders",
                       "contractPrivateGetPlanorderListOrders",
                       "contractPrivateGetStoporderListOrders"):
            if not hasattr(inner, method):
                continue
            try:
                resp = await getattr(inner, method)({"symbol": mexc_sym})
                determined = True
                data = resp.get("data") if isinstance(resp, dict) else resp
                if data:
                    return True
            except Exception as e:
                logger.debug("has_sltp_orders %s failed: %s", method, e)
                continue
        return False if determined else None

    async def get_position(self, symbol: str) -> Optional[Position]:
        positions = await self._exchange.fetch_positions([symbol])
        for p in positions:
            # MEXC can return any numeric field as None inside an otherwise-valid
            # position (e.g. unrealizedPnl=None right after open). `.get(k, 0)`
            # does NOT protect against an explicit None value — the key exists —
            # so float(None) would crash get_position, which the reconciliation
            # loop, restore, and safety checks all depend on. Use `or 0` to treat
            # missing AND None alike.
            if float(p.get("contracts") or 0) != 0:
                side = "long" if p["side"] == "long" else "short"
                return Position(
                    symbol=symbol,
                    side=side,
                    # ccxt reports `contracts` as the contract count; convert to
                    # base-currency units so it matches the bot's internal
                    # quantity (which is always base) — the reconciliation loop
                    # compares the two directly.
                    contracts=self._to_base(symbol, float(p.get("contracts") or 0)),
                    entry_price=float(p.get("entryPrice") or 0),
                    unrealized_pnl=float(p.get("unrealizedPnl") or 0),
                    leverage=int(p.get("leverage") or self._leverage),
                )
        return None

    async def has_attached_protection(self, symbol: str) -> bool:
        """True if the MEXC position already carries entry-attached SL/TP — the
        position-level stop set on the entry order, which is sticky (survives
        cancel_stop_orders) and is MEXC's reliable exit mechanism.

        resync uses this to avoid stacking duplicate plan (trigger) orders on top
        of working protection. CONSERVATIVE: returns True only on a POSITIVE
        finding; on any error/uncertainty it returns False so the caller falls
        back to placing a stop — a position is never left unprotected by a
        false positive."""
        inner = self._exchange
        # 1) Position info: MEXC exposes the attached SL/TP as fields on the
        #    position (exact key varies by account/ccxt version — probe several).
        try:
            poss = await inner.fetch_positions([symbol])
            for pp in poss:
                if float(pp.get("contracts") or 0) == 0:
                    continue
                raw = pp.get("info") or {}
                for k in ("stopLossPrice", "takeProfitPrice", "slPrice", "tpPrice",
                          "stopLoss", "takeProfit", "slTriggerPrice", "tpTriggerPrice"):
                    v = raw.get(k)
                    if v not in (None, "", 0, "0", 0.0):
                        logger.info("protection check %s: attached %s=%s", symbol, k, v)
                        return True
        except Exception as e:
            logger.debug("protection check %s: fetch_positions failed: %s", symbol, e)
        # 2) Stop-order list: on some accounts the attached TP/SL shows up here
        #    (and NOT in the plan-order list, which holds trigger-limit orders).
        mexc_sym = symbol.split(":")[0].replace("/", "_")
        for method in ("contractPrivateGetStoporderListOrders",
                       "contractPrivateGetStoporderListStopOrders"):
            if hasattr(inner, method):
                try:
                    resp = await getattr(inner, method)({"symbol": mexc_sym})
                    data = resp.get("data") if isinstance(resp, dict) else resp
                    if data:
                        n = len(data) if isinstance(data, list) else 1
                        logger.info("protection check %s: %s → %d stop order(s)",
                                    symbol, method, n)
                        return True
                except Exception:
                    continue
        return False

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
        # Isolated margin (openType=1) ADDITIONALLY requires the leverage param on
        # the entry order itself — MEXC rejects it otherwise ("requires a leverage
        # parameter for isolated margin orders"). Cross mode (openType=2) must NOT
        # carry leverage (it's account-level there).
        order_params = {"openType": self._open_type, **params}
        if self._open_type == 1:
            order_params.setdefault("leverage", self._leverage)
        order_params = self._round_sltp_params(symbol, order_params)
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
        # Isolated margin (openType=1) requires the leverage param on the entry
        # order; MEXC rejects it otherwise. See place_market_order for details.
        if self._open_type == 1:
            order_params.setdefault("leverage", self._leverage)
        order_params = self._round_sltp_params(symbol, order_params)
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
                    was_maker=True,
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
                                       int(time.time() * 1000), False,
                                       was_maker=True)
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
        # round_up: the base qty came from _to_base (contracts x contractSize)
        # and the float round trip often lands one ulp BELOW the integer count
        # (e.g. 0.0049/0.0001 -> 48.999...). Truncating would close 48 of 49
        # contracts, book a FULL close in the DB, and leave dust riding on MEXC
        # with its stops stripped by the resync. reduceOnly caps any overshoot
        # at the real position size, so rounding up is always safe (audit fix).
        contracts = self._to_contracts(symbol, amount, round_up=True)
        # Isolated margin (openType=1) requires the leverage param on EVERY order,
        # including reduce-only closes — MEXC rejects it otherwise. Without this a
        # close (max-hold / emergency / reconciliation) silently failed, leaving
        # the position open on MEXC but marked closed in the DB → orphaned.
        close_params = {"reduceOnly": True, "openType": self._open_type}
        if self._open_type == 1:
            close_params["leverage"] = self._leverage
        order = await self._exchange.create_order(
            symbol, "market", close_side, contracts, None, close_params,
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

    async def _place_trigger_order(
        self, symbol: str, order_type: str, side: str,
        contracts: float, params: dict, label: str
    ) -> dict | None:
        """Place one MEXC plan (trigger) order with retry on rate-limit (code 510).

        MEXC returns code 510 ("Requests are too frequent") when multiple trigger
        orders are placed in rapid succession — e.g. when a batch of max_hold
        closes fires simultaneously and each sleeve tries to resync its stops.
        Three attempts with 1.5 / 3.0 / 6.0 s back-off are enough to clear the
        window without significantly delaying stop placement.
        """
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._exchange.create_order(
                    symbol, order_type, side, contracts, None, params
                )
                return resp
            except Exception as e:
                last_exc = e
                err = str(e)
                if "510" in err or "too frequent" in err.lower() or "rate limit" in err.lower():
                    wait = 1.5 * (2 ** attempt)   # 1.5 s → 3.0 s → 6.0 s
                    logger.warning(
                        "%s order rate-limited for %s (attempt %d/3) — retry in %.1fs",
                        label, symbol, attempt + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Non-rate-limit error: don't retry, propagate immediately
                raise
        raise last_exc  # type: ignore[misc]

    async def set_sl_tp(
        self, symbol: str, position_side: str, sl_price: float, tp_price: float,
        amount: float
    ) -> None:
        # Acquire the global stop-order mutex so concurrent closes on different
        # symbols don't burst the plan-order endpoint simultaneously (MEXC 510).
        async with self._stop_order_lock:
            await self._set_sl_tp_locked(symbol, position_side, sl_price, tp_price, amount)

    async def _set_sl_tp_locked(
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

        def _has_id(resp) -> bool:
            return bool(resp and (resp.get("id") or resp.get("info", {}).get("orderId")))

        # MEXC plan-order endpoint occasionally returns a 200 with all fields
        # None (a silent business-layer reject). Retry up to 3 times with a
        # short back-off before treating it as a hard failure — this covers
        # transient rate-limit echoes and brief exchange hiccups at startup.
        sl_ok = False
        for _attempt in range(3):
            try:
                sl_resp = await self._place_trigger_order(
                    symbol, "market", close_side, contracts,
                    {**base, "triggerPrice": sl_price, "triggerType": sl_trigger}, "SL",
                )
                if _has_id(sl_resp):
                    sl_ok = True
                    break
                logger.warning(
                    "SL silent reject for %s (attempt %d/3) — will retry",
                    symbol, _attempt + 1,
                )
                await asyncio.sleep(1.5 * (2 ** _attempt))  # 1.5 s → 3 s → 6 s
            except Exception as e:
                logger.warning("SL order error for %s (attempt %d/3): %s", symbol, _attempt + 1, e)
                await asyncio.sleep(1.5 * (2 ** _attempt))
        if not sl_ok:
            logger.error("SL placement failed for %s after 3 attempts", symbol)

        tp_ok = False
        for _attempt in range(3):
            try:
                tp_resp = await self._place_trigger_order(
                    symbol, "market", close_side, contracts,
                    {**base, "triggerPrice": tp_price, "triggerType": tp_trigger}, "TP",
                )
                if _has_id(tp_resp):
                    tp_ok = True
                    break
                logger.warning(
                    "TP silent reject for %s (attempt %d/3) — will retry",
                    symbol, _attempt + 1,
                )
                await asyncio.sleep(1.5 * (2 ** _attempt))
            except Exception as e:
                logger.warning("TP order error for %s (attempt %d/3): %s", symbol, _attempt + 1, e)
                await asyncio.sleep(1.5 * (2 ** _attempt))
        if not tp_ok:
            logger.warning("TP placement failed for %s after 3 attempts — will exit via max-hold", symbol)

        if not sl_ok:
            raise RuntimeError(f"SL placement failed for {symbol} — position will be closed")
        if not tp_ok:
            logger.error(
                "TP placement FAILED for %s after 3 attempts (SL IS in place) — "
                "position will exit via max-hold/trailing", symbol)

    async def _get_attached_stop(self, symbol: str) -> Optional[dict]:
        """Return the position-attached SL/TP stop order (MEXC stoporder family)
        for this symbol, or None. Live entries attach SL/TP on the entry order —
        that protection rests in stoporder/open_orders, NOT the plan-order list."""
        inner = self._exchange
        mexc_sym = symbol.split(":")[0].replace("/", "_")
        for method in ("contractPrivateGetStoporderOpenOrders",
                       "contractPrivateGetStoporderListOrders"):
            if not hasattr(inner, method):
                continue
            try:
                resp = await getattr(inner, method)({"symbol": mexc_sym})
                data = resp.get("data") if isinstance(resp, dict) else resp
                if isinstance(data, dict):        # some gateways wrap a page object
                    data = data.get("resultList") or data.get("list") or []
                for o in (data or []):
                    # state 1 = untriggered/active; tolerate missing state field.
                    if str(o.get("state", "1")) in ("1", "active", ""):
                        return o
            except Exception as e:
                logger.debug("_get_attached_stop %s %s: %s", symbol, method, e)
        return None

    async def move_stop_loss(
        self, symbol: str, position_side: str, new_sl: float, amount: float
    ) -> bool:
        """Fail-safe mid-life SL move (BE/trailing).

        Preferred path — the entry-attached SL/TP (how every live entry is
        protected): modify it IN PLACE via stoporder/change_price. Atomic: no
        moment without a stop, no extra orders, TP passed through unchanged.

        Fallback path (no attached stop found — e.g. protection was rebuilt by
        resync as plan orders): place the NEW plan stop first, verify it rests,
        THEN cancel the old plan stop. Order matters — the position must never
        sit without a resting stop, and MEXC's plan-order place endpoint has a
        history of silent rejects.

        Failure semantics (every branch leaves the position protected):
          • change_price fails → abort, attached stop rests at old price
          • can't list existing plan orders → abort, nothing touched
          • new plan stop placement fails/silent-rejects → abort, old rests
          • old plan cancel fails → return True anyway: the new (tighter) stop
            triggers first; the leftover reduce-only trigger is a no-op once
            the position is gone and the orphan-cleanup removes it.
        Returns True only when the exchange CONFIRMED the new stop (caller may
        then update its internal sl_price)."""
        async with self._stop_order_lock:
            attached = await self._get_attached_stop(symbol)
            if attached is not None:
                return await self._change_attached_sl(symbol, attached, new_sl)
            return await self._move_sl_via_plan_orders(
                symbol, position_side, new_sl, amount)

    async def _change_attached_sl(
        self, symbol: str, attached: dict, new_sl: float
    ) -> bool:
        """Modify the position-attached stop's SL price in place, keeping the
        existing TP untouched (a 0 price means 'cancel that side', so the
        current TP must be passed through explicitly).

        MEXC has TWO modify endpoints and the ids are NOT interchangeable
        (probe evidence 2026-07-11: change_price with the stoporder-list id →
        code 2040 "Order does not exist"):
          • stoporder/change_plan_price {stopPlanOrderId: <stoporder list
            'id'>} — modifies the resting stop-plan order itself. This is the
            one that matches what _get_attached_stop returns → tried FIRST.
          • stoporder/change_price {orderId: <the ORIGINAL entry order id —
            the list entry's 'orderId' field>} — keyed off the parent order.
            Tried as fallback when the first form is rejected."""
        inner = self._exchange
        stop_id = attached.get("id")
        parent_id = attached.get("orderId")
        if not stop_id and not parent_id:
            logger.warning("move_stop_loss %s: attached stop has no id: %s",
                           symbol, attached)
            return False
        cur_tp = float(attached.get("takeProfitPrice") or 0)
        try:
            new_sl = float(inner.price_to_precision(symbol, new_sl))
        except Exception:
            pass

        attempts = []
        if stop_id and hasattr(inner, "contractPrivatePostStoporderChangePlanPrice"):
            attempts.append(("change_plan_price",
                             inner.contractPrivatePostStoporderChangePlanPrice,
                             {"stopPlanOrderId": stop_id,
                              "stopLossPrice": new_sl,
                              "takeProfitPrice": cur_tp}))
        if parent_id and hasattr(inner, "contractPrivatePostStoporderChangePrice"):
            attempts.append(("change_price",
                             inner.contractPrivatePostStoporderChangePrice,
                             {"orderId": parent_id,
                              "stopLossPrice": new_sl,
                              "takeProfitPrice": cur_tp}))
        if not attempts:
            return False

        ok = False
        for name, fn, payload in attempts:
            try:
                resp = await fn(payload)
            except Exception as e:
                logger.warning("move_stop_loss %s: %s failed: %s", symbol, name, e)
                continue
            # MEXC contract responses carry success:true/false; an explicit
            # false is a reject → try the next form.
            if isinstance(resp, dict) and resp.get("success") is False:
                logger.warning("move_stop_loss %s: %s rejected: %s",
                               symbol, name, resp)
                continue
            ok = True
            break
        if not ok:
            return False
        check = await self._get_attached_stop(symbol)
        if check is not None:
            got = float(check.get("stopLossPrice") or 0)
            if got > 0 and abs(got - new_sl) / new_sl > 0.001:
                logger.warning(
                    "move_stop_loss %s: change_price verify mismatch "
                    "(want %.6f, exchange shows %.6f)", symbol, new_sl, got)
                return False
        logger.info("move_stop_loss %s: attached SL changed to %.6f (stop %s)",
                    symbol, new_sl, stop_id or parent_id)
        return True

    async def _move_sl_via_plan_orders(
        self, symbol: str, position_side: str, new_sl: float, amount: float
    ) -> bool:
        inner = self._exchange
        mexc_sym = symbol.split(":")[0].replace("/", "_")
        sl_trigger = 2 if position_side == "long" else 1

        # 1) Snapshot the currently-resting SL plan orders (same triggerType).
        #    If we can't read them we can't cancel them later, which would
        #    stack duplicates on every candle — abort instead.
        try:
            resp = await inner.contractPrivateGetPlanorderListOrders(
                {"symbol": mexc_sym, "states": "1"})
            data = resp.get("data") if isinstance(resp, dict) else resp
        except Exception as e:
            logger.warning("move_stop_loss %s: plan-order list failed: %s",
                           symbol, e)
            return False
        old_ids = []
        for o in (data or []):
            try:
                if int(o.get("triggerType", 0)) == sl_trigger:
                    old_ids.append(str(o.get("id") or o.get("orderId")))
            except Exception:
                continue

        # 2) Place the new SL trigger (market-on-trigger, reduce-only).
        close_side = "sell" if position_side == "long" else "buy"
        open_type = 1 if self._margin_mode == "isolated" else 2
        params = {
            "orderType": 5, "executeCycle": 1, "openType": open_type,
            "reduceOnly": True,
            "triggerPrice": new_sl, "triggerType": sl_trigger,
        }
        if open_type == 1:
            params["leverage"] = self._leverage
        contracts = self._to_contracts(symbol, amount, round_up=True)
        try:
            new_resp = await self._place_trigger_order(
                symbol, "market", close_side, contracts, params, "SL-move")
        except Exception as e:
            logger.warning("move_stop_loss %s: new SL placement failed: %s",
                           symbol, e)
            return False
        new_id = None
        if new_resp:
            new_id = new_resp.get("id") or new_resp.get("info", {}).get("orderId")
        if not new_id:
            # Silent business-layer reject (200 with empty fields) — the old
            # stop still rests, so simply report failure.
            logger.warning("move_stop_loss %s: new SL silently rejected", symbol)
            return False

        # 3) Cancel the old SL trigger(s) by id. Best-effort — see docstring.
        stale = [oid for oid in old_ids if oid and oid != str(new_id)]
        if stale and hasattr(inner, "contractPrivatePostPlanorderCancel"):
            try:
                await inner.contractPrivatePostPlanorderCancel(
                    [{"symbol": mexc_sym, "orderId": oid} for oid in stale])
            except Exception as e:
                logger.warning(
                    "move_stop_loss %s: old SL cancel failed (%s) — harmless, "
                    "new stop %s rests and orphan cleanup will collect the rest",
                    symbol, e, new_id)
        logger.info("move_stop_loss %s: SL moved to %.6f (order %s, %d old cancelled)",
                    symbol, new_sl, new_id, len(stale))
        return True

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
