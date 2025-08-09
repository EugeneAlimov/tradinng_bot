from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import os
from src.config.env import load_env, env_str
from typing import Optional

_ENV_LOADED: bool = False
SETTINGS_SINGLETON = None  # ← добавили эту строку

def load_env(path: Optional[str] = None) -> None:
    """
    Разово пытается загрузить .env (если установлен python-dotenv).
    Безопасно вызывать многократно.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv as _ld
        _ld(dotenv_path=path) if path else _ld()
    except Exception:
        # Библиотеки может не быть — это ок: читаем os.environ
        pass
    _ENV_LOADED = True

def env_str(key: str, default: str = "") -> str:
    """Строка из окружения, снимает лишние кавычки, если есть."""
    val = os.environ.get(key, default)
    if isinstance(val, str) and len(val) >= 2:
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            return val[1:-1]
    return val


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
    """
    Singleton настроек. Подхватывает EXMO ключи из .env/окружения,
    если они не заданы в коде.
    """
    global SETTINGS_SINGLETON
    if SETTINGS_SINGLETON is not None:
        return SETTINGS_SINGLETON
    # Загружаем .env (если установлен python-dotenv)
    load_env()
    s = Settings()
    # Если в коде пусто — подхватываем из окружения
    s.api_key = s.api_key or env_str("EXMO_API_KEY", "")
    s.api_secret = s.api_secret or env_str("EXMO_API_SECRET", "")
    SETTINGS_SINGLETON = s
    return s
