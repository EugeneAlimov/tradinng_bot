# src/config/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import getcontext
from pathlib import Path
from typing import Final

# ---------- numeric / decimal ----------
getcontext().prec = int(os.environ.get("DECIMAL_PRECISION", "28"))

# ---------- paths ----------
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DATA_DIR: Final[Path] = Path(os.environ.get("BOT_DATA_DIR", PROJECT_ROOT / "data"))
CACHE_DIR: Final[Path] = Path(os.environ.get("BOT_CACHE_DIR", DATA_DIR / "cache"))
LOG_DIR: Final[Path] = Path(os.environ.get("BOT_LOG_DIR", PROJECT_ROOT / "logs"))

for _p in (DATA_DIR, CACHE_DIR, LOG_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ---------- env helpers ----------
def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default

def env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default))

# ---------- logging ----------
LOG_LEVEL: Final[str] = env_str("LOG_LEVEL", "INFO")

# ---------- timezone ----------
TIMEZONE: Final[str] = env_str("TZ", "UTC")

# ---------- exchange creds / files ----------
EXMO_KEY: Final[str] = (
    os.environ.get("EXMO_API_KEY")
    or os.environ.get("EXMO_KEY")
    or ""
)
EXMO_SECRET: Final[str] = (
    os.environ.get("EXMO_API_SECRET")
    or os.environ.get("EXMO_SECRET")
    or ""
)

EXMO_NONCE_FILE: Final[str] = env_str("EXMO_NONCE_FILE", str(DATA_DIR / ".exmo_nonce"))

DEFAULT_RESAMPLE: Final[str] = env_str("DEFAULT_RESAMPLE", "5m")

MAX_DAILY_LOSS_BPS: Final[int] = env_int("MAX_DAILY_LOSS_BPS", 0)
FEE_BPS: Final[int] = env_int("FEE_BPS", 10)
SLIP_BPS: Final[int] = env_int("SLIP_BPS", 2)

# ---------- Risk config expected by some modules ----------
@dataclass(frozen=True)
class RiskCfg:
    max_position_pct: int = 30
    max_daily_loss_pct: int = 5
    max_drawdown_pct: int = 20
    max_daily_trades: int = 20
    max_consecutive_losses: int = 5
    cooldown_after_loss_minutes: int = 30


__all__ = [
    "PROJECT_ROOT", "DATA_DIR", "CACHE_DIR", "LOG_DIR",
    "LOG_LEVEL", "TIMEZONE",
    "EXMO_KEY", "EXMO_SECRET", "EXMO_NONCE_FILE",
    "DEFAULT_RESAMPLE", "MAX_DAILY_LOSS_BPS", "FEE_BPS", "SLIP_BPS",
    "RiskCfg",
    "env_bool", "env_int", "env_str",
]
