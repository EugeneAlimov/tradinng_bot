from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import os
from typing import Optional
from src.config.env import load_env, env_str

SETTINGS_SINGLETON = None


@dataclass
class RiskCfg:
    position_size_usd: Decimal = Decimal(os.getenv("RISK_POSITION_SIZE_USD", "50"))
    max_daily_loss: float = float(os.getenv("RISK_MAX_DAILY_LOSS", "0.03"))


@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("EXMO_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("EXMO_API_SECRET", ""))
    storage_path: str = field(default_factory=lambda: os.getenv("STORAGE_PATH", "data/"))
    default_pair: str = field(default_factory=lambda: os.getenv("DEFAULT_PAIR", "DOGE_EUR"))
    risk: RiskCfg = field(default_factory=RiskCfg)


def get_settings() -> Settings:
    global SETTINGS_SINGLETON
    if SETTINGS_SINGLETON is not None:
        return SETTINGS_SINGLETON
    load_env()
    s = Settings()
    # normalize env strings
    s.api_key = s.api_key or env_str("EXMO_API_KEY", "")
    s.api_secret = s.api_secret or env_str("EXMO_API_SECRET", "")
    SETTINGS_SINGLETON = s
    return s
