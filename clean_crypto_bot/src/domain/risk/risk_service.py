
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any
from src.config.settings import RiskCfg

@dataclass
class RiskService:
    cfg: RiskCfg

    def size(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        price = ctx.get("last_price")
        if not price or price <= 0:
            return {"allow": False}
        qty = (Decimal(self.cfg.position_size_usd) / price).quantize(Decimal("0.000001"))
        return {"allow": True, "qty": qty, "limit_price": None, "client_id": ctx.get("client_id", "paper")}
