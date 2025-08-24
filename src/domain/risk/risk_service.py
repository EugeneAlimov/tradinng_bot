# src/domain/risk/risk_service.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math
from datetime import datetime, timezone

BPS = 1e-4

@dataclass
class RiskCfg:
    max_position_pct: float = 0.25          # 25% от эквити по умолчанию
    stop_loss_bps: int = 300                # 300 б.п. = 3%
    max_daily_loss_bps: Optional[int] = None

@dataclass
class PositionSnapshot:
    qty: float
    avg_price: float
    side: str  # "LONG" | "SHORT" (если коротких нет — просто "LONG")
    updated_at: datetime

class RiskService:
    def __init__(self, cfg: RiskCfg):
        self.cfg = cfg
        self.daily_pnl_bps: float = 0.0
        self.consecutive_api_errors: int = 0
        self.last_trade_confirmed: bool = False

    # вызывать при каждом подтверждённом трейде
    def update_daily_pnl(self, pnl_abs: float, equity_start_of_day: float, source: str = "") -> None:
        if equity_start_of_day <= 0:
            return
        self.daily_pnl_bps += (pnl_abs / equity_start_of_day) / BPS
        self.last_trade_confirmed = True

    def register_api_error(self) -> None:
        self.consecutive_api_errors += 1

    def reset_api_errors(self) -> None:
        self.consecutive_api_errors = 0

    # до выставления ордера — проверяем лимит позиции
    def pre_trade_check(self, desired_qty: float, mark_price: float, equity: float) -> tuple[bool, str]:
        if equity <= 0 or mark_price <= 0:
            return False, "Invalid equity/price"
        max_notional = equity * self.cfg.max_position_pct
        desired_notional = abs(desired_qty) * mark_price
        if desired_notional > max_notional + 1e-12:
            return False, f"Position notional {desired_notional:.2f} exceeds max {max_notional:.2f}"
        if self.cfg.max_daily_loss_bps is not None and self.daily_pnl_bps <= -abs(self.cfg.max_daily_loss_bps):
            return False, f"Daily loss limit reached: {self.daily_pnl_bps:.0f} bps"
        return True, "OK"

    # после частичного/полного исполнения
    def on_fill(self, position: PositionSnapshot) -> None:
        self.last_trade_confirmed = True

    def stop_price(self, position: PositionSnapshot) -> Optional[float]:
        if position.qty == 0 or self.cfg.stop_loss_bps is None:
            return None
        sl = abs(self.cfg.stop_loss_bps) * BPS
        if position.side == "LONG":
            return position.avg_price * (1.0 - sl)
        else:
            return position.avg_price * (1.0 + sl)

    # проверка на выход по стопу
    def should_stop_out(self, position: PositionSnapshot, mark_price: float) -> bool:
        sp = self.stop_price(position)
        if sp is None:
            return False
        if position.side == "LONG":
            return mark_price <= sp
        else:
            return mark_price >= sp
