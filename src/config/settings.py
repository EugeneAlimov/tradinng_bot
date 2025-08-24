# src/config/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """
    Единый конфиг проекта (ENV/.env).
    """

    # --- Risk / Reconcile / Alerts
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "0.25"))
    stop_loss_bps: int = int(os.getenv("STOP_LOSS_BPS", "300"))
    reconcile_threshold_qty: float = float(os.getenv("RECONCILE_THRESHOLD_QTY", "0.0001"))

    # Telegram alerts (опционально)
    tg_token: str = os.getenv("TG_TOKEN", "")
    tg_chat: str = os.getenv("TG_CHAT", "")

    # EXMO creds (опционально; можно держать в keyring)
    exmo_key: str = os.getenv("EXMO_KEY", "")
    exmo_secret: str = os.getenv("EXMO_SECRET", "")

    # Прочее
    debug: bool = _get_env_bool("DEBUG", False)
    exmo_debug: bool = _get_env_bool("EXMO_DEBUG", False)
    http_timeout_sec: float = float(os.getenv("HTTP_TIMEOUT_SEC", "10"))
    http_retries: int = int(os.getenv("HTTP_RETRIES", "3"))
    http_backoff_factor: float = float(os.getenv("HTTP_BACKOFF_FACTOR", "0.3"))


def get_settings() -> Settings:
    """Единая точка входа для настроек."""
    return Settings()
