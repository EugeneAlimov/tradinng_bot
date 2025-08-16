from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Dict, Any
from src.core.domain.models import TradingPair

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass
class StrategyCfg:
    lookback: int = 100
    entry_z: float = 1.0
    exit_z: float = 0.2


@dataclass
class MeanReversion:
    cfg: StrategyCfg = field(default_factory=list)

    def decide(self, pair: TradingPair, ctx: Dict[str, Any]) -> Dict[str, Any]:
        price: Decimal | None = ctx.get("last_price")
        if price is None or price <= 0:
            return {"action": "HOLD"}
        return {"action": "HOLD"}
