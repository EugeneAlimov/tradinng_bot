from __future__ import annotations
from decimal import Decimal
from src.core.domain.models import TradingPair
from src.core.ports.market_data import MarketDataPort


class PaperFeed(MarketDataPort):
    def __init__(self, start_price: Decimal = Decimal("0.1")):
        self._price = Decimal(start_price)

    def get_price(self, pair: TradingPair) -> Decimal:
        return self._price

    def get_candles(self, pair: TradingPair, timeframe: str, limit: int):
        return []
