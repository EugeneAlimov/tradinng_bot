# src/services/risk.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Dict

@dataclass(frozen=True)
class RiskCfg:
    position_size_usd: Decimal
    max_daily_loss: float = 0.0  # доля от позиции (0..1)

class RiskService:
    def __init__(self, cfg: RiskCfg):
        self.cfg = cfg

    def size(self, ctx: Mapping[str, Any]) -> Dict[str, Decimal | str]:
        """
        ctx ожидает ключ 'last_price' (Decimal/float/str).
        Возвращает: {qty, position_usd, max_daily_loss_usd, reason?}
        """
        raw = ctx.get("last_price", None)
        price = Decimal(str(raw)) if raw is not None else Decimal("0")

        if price <= 0:
            return {
                "qty": Decimal("0"),
                "position_usd": Decimal("0"),
                "max_daily_loss_usd": Decimal("0"),
                "reason": "bad_price",
            }

        qty = (self.cfg.position_size_usd / price).quantize(Decimal("0.00000001"))
        mdl = (Decimal(str(self.cfg.max_daily_loss)) * self.cfg.position_size_usd).quantize(Decimal("0.01"))

        return {
            "qty": qty,
            "position_usd": self.cfg.position_size_usd,
            "max_daily_loss_usd": mdl,
        }
