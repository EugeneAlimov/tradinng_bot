from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class TradingPair:
    base: str
    quote: str

    def symbol(self) -> str:
        return f"{self.base}_{self.quote}"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Price:
    value: Decimal
    ts_ms: int


@dataclass(frozen=True)
class OrderRequest:
    pair: TradingPair
    side: Side
    qty: Decimal  # base asset quantity
    limit_price: Optional[Decimal] = None
    client_id: Optional[str] = None


@dataclass(frozen=True)
class TradeFill:
    order_id: str
    pair: TradingPair
    qty: Decimal
    price: Decimal
    ts_ms: int


@dataclass
class Position:
    pair: TradingPair
    qty: Decimal = field(default_factory=Decimal)
    avg_price: Decimal = field(default_factory=Decimal)
    unrealized_pnl: Decimal = Decimal("0")

    def apply_fill(self, fill: TradeFill) -> None:
        if fill.qty == 0:
            return
        if fill.pair != self.pair:
            return
        if fill.qty > 0:
            new_qty = self.qty + fill.qty
            self.avg_price = (
                (self.avg_price * self.qty + fill.price * fill.qty) / new_qty
                if new_qty != 0 else Decimal("0")
            )
            self.qty = new_qty
        else:
            self.qty = self.qty + fill.qty  # selling reduces qty
        # unrealized PnL is computed externally from current price
