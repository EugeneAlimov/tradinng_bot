from __future__ import annotations
from typing import Protocol, Sequence, Tuple
from decimal import Decimal
from src.core.domain.models import TradingPair


class MarketDataPort(Protocol):
    def get_price(self, pair: TradingPair) -> Decimal: ...

    def get_candles(self, pair: TradingPair, timeframe: str, limit: int) -> Sequence[
        Tuple[int, Decimal, Decimal, Decimal, Decimal]]: ...
