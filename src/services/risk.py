from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from src.config.settings import RiskCfg


@dataclass
class RiskService:
    cfg: RiskCfg

    @staticmethod
    def _dec(v: Any) -> Decimal:
        return v if isinstance(v, Decimal) else Decimal(str(v))

    def size(self, market: Dict[str, Any], equity_usd: Optional[Decimal] = None) -> Dict[str, Decimal]:
        """
        Возвращает словарь:
          - price: Decimal
          - notional_usd: Decimal (фикс из cfg.position_size_usd, либо max_position_pct*equity_usd, либо 50)
          - qty_base: Decimal (notional / price), округление вниз
        """
        if "last_price" not in market:
            raise KeyError("market must contain 'last_price'")
        price = self._dec(market["last_price"])
        if price <= 0:
            raise ValueError("last_price must be positive")

        notional: Optional[Decimal] = self.cfg.position_size_usd
        if notional is None:
            if equity_usd is not None:
                pct = Decimal(str(self.cfg.max_position_pct))
                notional = (equity_usd * pct).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            else:
                notional = Decimal("50.00")

        qty_base = (notional / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        return {"price": price, "notional_usd": notional, "qty_base": qty_base}
