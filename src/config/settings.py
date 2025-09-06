# src/config/settings.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

__all__ = ["RiskCfg", "Settings", "get_settings"]


@dataclass(frozen=True)
class RiskCfg:
    # базовые
    max_position_pct: float = 0.25  # 25% долей (0..1)
    stop_loss_bps: int = 250
    cooldown_bars: int = 3
    fee_bps: int = 10
    slip_bps: int = 2

    # расширенные, на которые ссылаются тесты/сервисы
    position_size_usd: Optional[Decimal] = None
    max_daily_loss: Optional[float] = None  # доля (0..1), например 0.03

    def __post_init__(self) -> None:
        # нормализация доли
        mp = float(self.max_position_pct)
        if mp > 1.0:
            mp /= 100.0
        if not (0.0 < mp <= 1.0):
            raise ValueError("max_position_pct must be in (0,1]")
        object.__setattr__(self, "max_position_pct", mp)

        for name in ("stop_loss_bps", "fee_bps", "slip_bps", "cooldown_bars"):
            v = int(getattr(self, name))
            if v < 0:
                raise ValueError(f"{name} must be >= 0")
            object.__setattr__(self, name, v)

        if self.position_size_usd is not None:
            try:
                ps = Decimal(self.position_size_usd)
            except Exception as e:
                raise ValueError(f"position_size_usd invalid: {e}")
            if ps < 0:
                raise ValueError("position_size_usd must be >= 0")
            object.__setattr__(self, "position_size_usd", ps)

        if self.max_daily_loss is not None:
            mdl = float(self.max_daily_loss)
            if not (0.0 < mdl < 1.0):
                raise ValueError("max_daily_loss must be in (0,1)")
            object.__setattr__(self, "max_daily_loss", mdl)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> "RiskCfg":
        d = dict(d or {})
        return cls(
            max_position_pct=d.get("max_position_pct", 0.25),
            stop_loss_bps=d.get("stop_loss_bps", 250),
            cooldown_bars=d.get("cooldown_bars", 3),
            fee_bps=d.get("fee_bps", 10),
            slip_bps=d.get("slip_bps", 2),
            position_size_usd=d.get("position_size_usd"),
            max_daily_loss=d.get("max_daily_loss"),
        )

    @classmethod
    def from_args(cls, args: Any) -> "RiskCfg":
        mp = getattr(args, "risk_max_position_pct", 0.25)
        try:
            mp = float(mp)
        except Exception:
            mp = 0.25
        return cls(
            max_position_pct=mp,
            stop_loss_bps=getattr(args, "risk_stop_loss_bps", 250),
            cooldown_bars=getattr(args, "cooldown_bars", 3),
            fee_bps=getattr(args, "fee_bps", 10),
            slip_bps=getattr(args, "slip_bps", 2),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_position_pct": self.max_position_pct,
            "stop_loss_bps": self.stop_loss_bps,
            "cooldown_bars": self.cooldown_bars,
            "fee_bps": self.fee_bps,
            "slip_bps": self.slip_bps,
            "position_size_usd": str(self.position_size_usd) if self.position_size_usd is not None else None,
            "max_daily_loss": self.max_daily_loss,
        }

    @property
    def position_fraction(self) -> float:
        return float(self.max_position_pct)


@dataclass(frozen=True)
class Settings:
    exmo_base_url: str = "https://api.exmo.com/v1.1"
    # сюда можно добавить ключи/секреты, если нужны реальные запросы
    # api_key: str = ""
    # api_secret: str = ""


def get_settings() -> Settings:
    """Нужен для импортов в infrastructure/cli-модулях."""
    return Settings()
