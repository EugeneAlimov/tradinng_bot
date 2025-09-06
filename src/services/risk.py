from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Any, Dict


@dataclass(frozen=True)
class RiskCfg:
    position_size_usd: Decimal
    max_daily_loss: float = 0.0  # доля (0..1)


class RiskService:
    def __init__(self, cfg: RiskCfg):
        self.cfg = cfg  # не создаём одноимённых атрибутов "size", чтобы не затереть метод

    def size(self, market: Mapping[str, Any]) -> Dict[str, Decimal]:
        """
        Простейшее позиционирование: фиксированный $-объём по последней цене.
        Возврат — словарь с qty (в базовой валюте).
        """
        last = Decimal(str(market["last_price"]))
        if last <= 0:
            raise ValueError("last_price must be positive")
        qty = (self.cfg.position_size_usd / last)
        return {"qty": qty}
