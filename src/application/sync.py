# src/domain/risk/advanced_risk.py
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskLimits:
    max_position_pct: Decimal = Decimal("30")
    max_daily_loss_pct: Decimal = Decimal("5")
    max_drawdown_pct: Decimal = Decimal("20")
    max_leverage: Decimal = Decimal("3")
    max_correlated_exposure: Decimal = Decimal("50")
    min_liquidity_ratio: Decimal = Decimal("2")
    max_daily_trades: int = 20
    max_consecutive_losses: int = 5
    cooldown_after_loss_minutes: int = 30


@dataclass
class TradingStats:
    daily_trades: int = 0
    daily_pnl: Decimal = Decimal("0")
    consecutive_losses: int = 0
    last_loss_time: Optional[datetime] = None
    peak_equity: Decimal = Decimal("0")
    current_drawdown: Decimal = Decimal("0")
    last_reset_date: date = field(default_factory=lambda: datetime.utcnow().date())


class AdvancedRiskManager:
    def __init__(self, limits: Optional[RiskLimits] = None, initial_capital: Decimal = Decimal("1000")):
        self.limits = limits or RiskLimits()
        self.initial_capital = initial_capital
        self.stats = TradingStats()
        self.blocked_until: Optional[datetime] = None
        self.risk_level = RiskLevel.LOW

    def _maybe_daily_reset(self) -> None:
        today = datetime.utcnow().date()
        if self.stats.last_reset_date != today:
            self.stats.daily_trades = 0
            self.stats.daily_pnl = Decimal("0")
            self.stats.last_reset_date = today
            logger.info("risk: daily stats reset")

    def _activate_cooldown(self) -> None:
        self.blocked_until = datetime.utcnow() + timedelta(minutes=self.limits.cooldown_after_loss_minutes)
        logger.warning("risk: trading blocked until %s", self.blocked_until.isoformat())

    def _risk_multiplier(self) -> Decimal:
        mult = Decimal("1.0")
        dd = self.stats.current_drawdown
        if dd > Decimal("15"):
            mult *= Decimal("0.5")
        elif dd > Decimal("10"):
            mult *= Decimal("0.75")
        if self.stats.consecutive_losses >= 3:
            mult *= Decimal("0.5")
        elif self.stats.consecutive_losses >= 2:
            mult *= Decimal("0.7")
        if self.risk_level == RiskLevel.CRITICAL:
            mult *= Decimal("0.25")
        elif self.risk_level == RiskLevel.HIGH:
            mult *= Decimal("0.5")
        elif self.risk_level == RiskLevel.MEDIUM:
            mult *= Decimal("0.75")
        return max(Decimal("0.1"), min(Decimal("1.0"), mult))

    def _update_level(self, equity: Decimal) -> None:
        score = 0
        if self.stats.peak_equity > 0:
            self.stats.current_drawdown = ((self.stats.peak_equity - equity) / self.stats.peak_equity) * Decimal("100")
        if self.stats.current_drawdown > Decimal("15"):
            score += 3
        elif self.stats.current_drawdown > Decimal("10"):
            score += 2
        elif self.stats.current_drawdown > Decimal("5"):
            score += 1
        if self.stats.consecutive_losses >= 4:
            score += 3
        elif self.stats.consecutive_losses >= 3:
            score += 2
        elif self.stats.consecutive_losses >= 2:
            score += 1
        if self.stats.daily_pnl < 0:
            daily_loss_pct = abs(self.stats.daily_pnl / max(Decimal("1"), equity)) * Decimal("100")
            if daily_loss_pct > Decimal("3"):
                score += 2
            elif daily_loss_pct > Decimal("2"):
                score += 1
        self.risk_level = (
            RiskLevel.CRITICAL if score >= 6 else
            RiskLevel.HIGH if score >= 4 else
            RiskLevel.MEDIUM if score >= 2 else
            RiskLevel.LOW
        )

    def pre_trade_check(
        self, order_side: str, quantity: Decimal, price: Decimal, current_position: Decimal, current_equity: Decimal
    ) -> Tuple[bool, str]:
        self._maybe_daily_reset()
        if self.blocked_until and datetime.utcnow() < self.blocked_until:
            mins = int((self.blocked_until - datetime.utcnow()).total_seconds() // 60)
            return False, f"cooldown: {mins}m left"
        if self.stats.daily_trades >= self.limits.max_daily_trades:
            return False, "daily trade limit reached"
        if self.stats.consecutive_losses >= self.limits.max_consecutive_losses:
            self._activate_cooldown()
            return False, "too many consecutive losses"
        pos_value = quantity * price
        pos_pct = (pos_value / max(Decimal("1"), current_equity)) * Decimal("100")
        if pos_pct > self.limits.max_position_pct:
            return False, f"position too large: {pos_pct:.2f}%"
        if self.stats.daily_pnl < 0:
            loss_pct = abs(self.stats.daily_pnl / max(Decimal("1"), current_equity)) * Decimal("100")
            if loss_pct >= self.limits.max_daily_loss_pct:
                return False, f"daily loss limit reached: {loss_pct:.2f}%"
        self._update_level(current_equity)
        return True, "OK"

    def update_after_trade(self, pnl: Decimal, current_equity: Decimal, is_win: bool) -> None:
        self._maybe_daily_reset()
        self.stats.daily_trades += 1
        self.stats.daily_pnl += pnl
        if is_win:
            self.stats.consecutive_losses = 0
        else:
            self.stats.consecutive_losses += 1
            if self.stats.consecutive_losses >= self.limits.max_consecutive_losses:
                self._activate_cooldown()
        if current_equity > self.stats.peak_equity:
            self.stats.peak_equity = current_equity
        self._update_level(current_equity)

    def calc_position_size(
        self, entry_price: Decimal, stop_loss: Decimal, equity: Decimal, volatility: Optional[Decimal] = None
    ) -> Decimal:
        risk_per_trade = equity * Decimal("0.01")
        dist = abs(entry_price - stop_loss)
        if dist <= 0:
            return Decimal("0")
        base = risk_per_trade / dist
        if volatility and volatility > 0:
            base *= min(Decimal("1"), Decimal("20") / volatility)
        base *= self._risk_multiplier()
        max_value = equity * (self.limits.max_position_pct / Decimal("100"))
        return min(base, max_value / entry_price)

    def calc_stop_loss(self, entry_price: Decimal, atr: Optional[Decimal] = None, support: Optional[Decimal] = None) -> Decimal:
        stops: List[Decimal] = []
        if atr and atr > 0:
            stops.append(entry_price - atr * Decimal("2"))
        stops.append(entry_price * Decimal("0.98"))
        if support and support < entry_price:
            stops.append(support * Decimal("0.995"))
        return max(stops) if stops else entry_price * Decimal("0.98")

    def calc_take_profit(self, entry_price: Decimal, stop_loss: Decimal, rr: Decimal = Decimal("2")) -> Decimal:
        risk = entry_price - stop_loss
        return entry_price + risk * rr

    def report(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level.value,
            "daily_trades": self.stats.daily_trades,
            "daily_pnl": str(self.stats.daily_pnl),
            "current_drawdown_pct": f"{self.stats.current_drawdown:.2f}",
            "consecutive_losses": self.stats.consecutive_losses,
            "blocked_until": self.blocked_until.isoformat() if self.blocked_until else None,
            "peak_equity": str(self.stats.peak_equity),
        }
