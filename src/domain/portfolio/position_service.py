from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from src.core.domain.models import Position, TradeFill, TradingPair
from src.core.ports.storage import StoragePort


@dataclass
class PositionService:
    storage: StoragePort

    def get(self, pair: TradingPair) -> Position:
        p = self.storage.get_position(pair)
        return p or Position(pair=pair)

    def apply(self, pair: TradingPair, fill: TradeFill) -> Position:
        p = self.get(pair)
        p.apply_fill(fill)
        self.storage.save_position(p)
        return p

    def compute_unrealized(self, pair: TradingPair, last_price: Decimal) -> Decimal:
        p = self.get(pair)
        if p.qty == 0:
            return Decimal("0")
        return (last_price - p.avg_price) * p.qty
