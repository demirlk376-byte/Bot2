from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import RiskConfig

logger = logging.getLogger(__name__)

MIN_BTC_ORDER = 0.001  # MEXC minimum


@dataclass
class TradeSetup:
    symbol: str
    direction: int
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float
    position_value: float
    margin_required: float
    risk_usdt: float
    risk_pct: float
    rr_ratio: float


class RiskManager:
    def __init__(self, config: RiskConfig):
        self._cfg = config

    def calculate_sl_tp(
        self, direction: int, entry_price: float, atr: float
    ) -> tuple[float, float]:
        sl_dist = atr * self._cfg.atr_sl_multiplier
        tp_dist = sl_dist * self._cfg.rr_ratio

        if direction == 1:
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        return sl, tp

    def calculate_position_size(
        self, balance: float, entry_price: float, sl_price: float
    ) -> float:
        risk_amount = balance * self._cfg.max_risk_per_trade
        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct <= 0:
            return 0.0
        quantity = risk_amount / (entry_price * sl_dist_pct)
        max_qty = (balance * 0.5) / entry_price
        quantity = min(quantity, max_qty)
        quantity = max(quantity, 0.0)
        quantity = round(quantity, 3)  # 3 decimal places (BTC precision)
        return quantity

    def build_trade_setup(
        self,
        direction: int,
        entry_price: float,
        atr: float,
        balance: float,
        leverage: int,
        symbol: str = "BTC/USDT:USDT",
        size_mult: float = 1.0,
    ) -> Optional[TradeSetup]:
        sl, tp = self.calculate_sl_tp(direction, entry_price, atr)
        quantity = self.calculate_position_size(balance, entry_price, sl)
        # Confidence sizing only ever scales DOWN (size_mult ≤ 1.0), so the
        # validated max risk is never exceeded.
        if size_mult < 1.0:
            quantity = round(quantity * size_mult, 3)

        if quantity < MIN_BTC_ORDER:
            logger.debug("Position size %.4f below minimum %.4f", quantity, MIN_BTC_ORDER)
            return None

        sl_dist = abs(entry_price - sl)
        tp_dist = abs(tp - entry_price)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0.0

        if rr < 1.5:
            logger.debug("RR ratio %.2f below minimum 1.5", rr)
            return None

        risk_usdt = sl_dist * quantity
        risk_pct = risk_usdt / balance if balance > 0 else 0.0

        if risk_pct > self._cfg.max_risk_per_trade * 1.25:
            logger.warning("Risk %.2f%% exceeds limit", risk_pct * 100)
            return None

        pos_value = quantity * entry_price
        margin = pos_value / leverage

        return TradeSetup(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl,
            tp_price=tp,
            quantity=quantity,
            position_value=pos_value,
            margin_required=margin,
            risk_usdt=risk_usdt,
            risk_pct=risk_pct,
            rr_ratio=rr,
        )

    def check_daily_loss_limit(
        self,
        starting_balance: float,
        current_balance: float,
        open_unrealized_pnl: float,
    ) -> bool:
        if starting_balance <= 0:
            return True
        effective = current_balance + open_unrealized_pnl
        loss_pct = (starting_balance - effective) / starting_balance
        return loss_pct < self._cfg.daily_max_loss

    def validate_new_trade(
        self,
        setup: TradeSetup,
        open_position_count: int,
    ) -> tuple[bool, str]:
        if open_position_count >= self._cfg.max_positions:
            return False, f"Max positions ({self._cfg.max_positions}) reached"
        if setup.rr_ratio < 1.5:
            return False, f"RR ratio {setup.rr_ratio:.2f} too low"
        return True, "ok"
