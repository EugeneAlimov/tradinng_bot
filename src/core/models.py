#!/usr/bin/env python3
"""🎯 Модели данных торговой системы"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

@dataclass
class TradingPair:
    base: str
    quote: str

    def __str__(self) -> str:
        return f"{self.base}_{self.quote}"

@dataclass
class TradeSignal:
    action: str
    quantity: Decimal
    price: Decimal
    confidence: float
    reason: str
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class Position:
    currency: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal
