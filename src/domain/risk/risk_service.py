
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any
from src.config.settings import RiskCfg
from datetime import datetime, timedelta
from typing import Optional

@dataclass
class RiskService:
    cfg: RiskCfg

    def size(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        price = ctx.get("last_price")
        if not price or price <= 0:
            return {"allow": False}
        qty = (Decimal(self.cfg.position_size_usd) / price).quantize(Decimal("0.000001"))
        return {"allow": True, "qty": qty, "limit_price": None, "client_id": ctx.get("client_id", "paper")}

@dataclass
class RiskLimits:
    max_daily_loss_bps: float = 0.0     # например 50 => -0.50% дневной лимит
    cooldown_bars: int = 0              # не открывать новую сделку N баров после последней

class RiskGuard:
    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self._day_start = None
        self._day_start_equity = None
        self._last_trade_bar_index: Optional[int] = None
        self.paused_reason: Optional[str] = None

    def on_new_day(self, equity: float, now: datetime):
        if (self._day_start is None) or (now.date() != self._day_start.date()):
            self._day_start = now
            self._day_start_equity = equity
            self.paused_reason = None

    def notify_trade(self, bar_index: int):
        self._last_trade_bar_index = bar_index

    def check_cooldown(self, current_bar_index: int) -> Optional[str]:
        if self.limits.cooldown_bars <= 0:
            return None
        if self._last_trade_bar_index is None:
            return None
        if current_bar_index - self._last_trade_bar_index < self.limits.cooldown_bars:
            return f"cooldown active: {current_bar_index - self._last_trade_bar_index}/{self.limits.cooldown_bars} bars"
        return None

    def check_daily_loss(self, current_equity: float) -> Optional[str]:
        if not self.limits.max_daily_loss_bps or self._day_start_equity is None:
            return None
        change = (current_equity - self._day_start_equity) / self._day_start_equity * 1e4  # bps
        if change <= -abs(self.limits.max_daily_loss_bps):
            return f"daily loss limit hit ({change:.1f} bps ≤ -{abs(self.limits.max_daily_loss_bps):.1f} bps)"
        return None

    def can_trade(self, current_bar_index: int, current_equity: float) -> (bool, Optional[str]):
        # порядок проверок важен — сначала фатальные
        reason = self.check_daily_loss(current_equity)
        if reason:
            self.paused_reason = reason
            return False, reason
        reason = self.check_cooldown(current_bar_index)
        if reason:
            return False, reason
        return True, None