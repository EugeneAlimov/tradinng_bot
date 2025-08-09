from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import os

@dataclass
class RiskCfg:
    position_size_usd: Decimal = Decimal(os.getenv("RISK_POSITION_SIZE_USD", "50"))
    max_daily_loss: float = float(os.getenv("RISK_MAX_DAILY_LOSS", "0.03"))

@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("EXMO_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("EXMO_API_SECRET", ""))
    storage_path: str = field(default_factory=lambda: os.getenv("STORAGE_PATH", "data/"))
    default_pair: str = field(default_factory=lambda: os.getenv("TRADING_PAIR", "DOGE_EUR"))
    mode: str = field(default_factory=lambda: os.getenv("TRADING_MODE", "paper"))
    risk: RiskCfg = field(default_factory=RiskCfg)

def get_settings() -> Settings:
    return Settings()
