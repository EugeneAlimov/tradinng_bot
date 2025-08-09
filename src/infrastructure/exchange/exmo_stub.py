
from __future__ import annotations
from decimal import Decimal
from typing import Iterable
from src.core.ports.exchange import ExchangePort
from src.core.domain.models import TradingPair, OrderRequest, TradeFill

class ExmoStubExchange(ExchangePort):
    """Paper/live placeholder. In paper mode it mirrors MarketData price and instantly 'fills' orders."""
    def __init__(self, market):
        self.market = market

    def get_price(self, pair: TradingPair) -> Decimal:
        return self.market.get_price(pair)

    def place_order(self, req: OrderRequest) -> str:
        # Immediately "accept"
        return "paper-order-1"

    def cancel(self, order_id: str) -> None:
        pass

    def get_fills(self, client_id: str) -> Iterable[TradeFill]:
        return []

    def get_balance(self, asset: str) -> Decimal:
        return Decimal("0")
