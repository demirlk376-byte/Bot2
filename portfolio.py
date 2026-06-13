from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Position:
    id: str
    symbol: str
    direction: int       # +1 | -1
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float
    entry_time: datetime
    unrealized_pnl: float = 0.0
    is_paper: bool = True
    strategy_scores: dict = field(default_factory=dict)

    @property
    def side(self) -> str:
        return "long" if self.direction == 1 else "short"


class Portfolio:
    def __init__(self, is_paper: bool = True):
        self._positions: dict[str, Position] = {}
        self._is_paper = is_paper

    def add_position(self, position: Position) -> None:
        self._positions[position.id] = position

    def remove_position(self, position_id: str) -> None:
        self._positions.pop(position_id, None)

    def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_open_position_count(self) -> int:
        return len(self._positions)

    def get_position_by_id(self, position_id: str) -> Optional[Position]:
        return self._positions.get(position_id)

    def get_position_for_symbol(self, symbol: str) -> Optional[Position]:
        for p in self._positions.values():
            if p.symbol == symbol:
                return p
        return None

    def update_unrealized_pnl(self, current_price: float) -> None:
        for pos in self._positions.values():
            pos.unrealized_pnl = pos.direction * (current_price - pos.entry_price) * pos.quantity

    def update_unrealized_pnl_for(self, symbol: str, current_price: float) -> None:
        """Update unrealized PnL for one symbol only (multi-coin: each coin has
        its own price, so a single shared price would be wrong)."""
        for pos in self._positions.values():
            if pos.symbol == symbol:
                pos.unrealized_pnl = (
                    pos.direction * (current_price - pos.entry_price) * pos.quantity
                )

    def get_total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    def create_position(
        self,
        symbol: str,
        direction: int,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        quantity: float,
        strategy_scores: dict,
        is_paper: bool = True,
        position_id: str | None = None,
        entry_time: datetime | None = None,
    ) -> Position:
        # position_id lets the portfolio, the paper-exchange position and the DB
        # row all share ONE id. Without this, the paper close callback (keyed by
        # the exchange's id) could never find the portfolio position, so closes
        # were never recorded and the coin stayed "open" forever.
        pos = Position(
            id=position_id or str(uuid.uuid4()),
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            quantity=quantity,
            entry_time=entry_time or datetime.now(timezone.utc),
            is_paper=is_paper,
            strategy_scores=strategy_scores,
        )
        self.add_position(pos)
        return pos
