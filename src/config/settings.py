from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import os
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
    default_pair: str = field(default_factory=lambda: os.getenv("DEFAULT_PAIR", "DOGE_EUR"))# -*- coding: utf-8 -*-
"""
Унифицированные настройки проекта:
- читаем переменные окружения;
- опционально читаем .env (если найден) без внешних зависимостей;
- опционально читаем YAML-файл (если задан путь через TRADING_BOT_CONFIG=...).

Есть минимальная валидация и удобные свойства.
"""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional


_ENV_BOOL_TRUE = {"1", "true", "yes", "on", "y", "t"}
_ENV_BOOL_FALSE = {"0", "false", "no", "off", "n", "f"}


def _str2bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in _ENV_BOOL_TRUE:
        return True
    if s in _ENV_BOOL_FALSE:
        return False
    return default


def _parse_env_file(path: Path) -> Dict[str, str]:
    """
    Простейший парсер .env без зависимостей (ключ=значение, без кавычек).
    Игнорирует комментарии и пустые строки.
    """
    out: Dict[str, str] = {}
    if not path.exists():
        return out

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # допускаем KEY="value" и KEY='value' и KEY=value
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        out[k] = v
    return out


def _parse_yaml(path: Path) -> Dict[str, Any]:
    """
    Мини-парсер YAML: пытается загрузить .yml/.yaml как JSON-подобный словарь.
    Если PyYAML не установлен — мягкий фолбэк: пытаемся прочитать как JSON.
    """
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        # Фолбэк на JSON (разрешает простые словари)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}


@dataclass
class Settings:
    # --- EXMO/API ---
    exmo_api_key: Optional[str] = None
    exmo_api_secret: Optional[str] = None
    exmo_base_url: str = "https://api.exmo.com/v1.1"
    exmo_timeout: int = 20

    # --- торговля/риск ---
    default_pair: Optional[str] = None
    max_notional_eur: float = 100.0
    maker_by_default: bool = True

    # --- пути/файлы ---
    data_dir: Path = field(default_factory=lambda: Path("data"))
    nonce_file: Path = field(default_factory=lambda: Path("data/.exmo_nonce"))

    # --- логирование ---
    log_level: str = "INFO"
    mask_api_keys_in_logs: bool = True

    # --- внутренняя отладка ---
    debug: bool = False

    def validate(self) -> None:
        if not self.exmo_api_key or not self.exmo_api_secret:
            # Не роняем процесс: возможно бэктест/оптимизация без API.
            # Но для live trading это критично — там будет отдельная проверка.
            pass

        if self.max_notional_eur <= 0:
            raise ValueError("max_notional_eur должен быть > 0")

        ll = str(self.log_level).upper().strip()
        if ll not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(f"Некорректный log_level: {self.log_level}")
        self.log_level = ll

    # Удобство: int лог-уровень
    @property
    def log_level_int(self) -> int:
        import logging
        return getattr(logging, self.log_level, logging.INFO)


def load_settings() -> Settings:
    """
    Загрузка настроек в порядке приоритета:
      1) ENV (включая те, что подгружены из .env/YAML)
      2) .env в корне проекта (если есть)
      3) YAML/JSON файл по пути TRADING_BOT_CONFIG (если указан)

    Примечание: если и .env, и YAML заданы — значения ENV имеют приоритет.
    """
    # 1) Начинаем с текущего окружения
    env_map: Dict[str, str] = dict(os.environ)

    # 2) .env (не обязателен)
    env_file = Path(".env")
    env_map.update(_parse_env_file(env_file))

    # 3) YAML/JSON конфиг (опционально)
    cfg_path = os.getenv("TRADING_BOT_CONFIG")
    yaml_map: Dict[str, Any] = {}
    if cfg_path:
        yaml_map = _parse_yaml(Path(cfg_path)) or {}

    def g(name: str, default: Optional[str] = None) -> Optional[str]:
        if name in env_map:
            return env_map[name]
        v = yaml_map.get(name)
        return str(v) if v is not None else default

    s = Settings(
        # API
        exmo_api_key=g("EXMO_API_KEY"),
        exmo_api_secret=g("EXMO_API_SECRET"),
        exmo_base_url=g("EXMO_BASE_URL", "https://api.exmo.com/v1.1") or "https://api.exmo.com/v1.1",
        exmo_timeout=int(g("EXMO_TIMEOUT", "20") or "20"),

        # торговля
        default_pair=g("DEFAULT_PAIR"),
        max_notional_eur=float(g("MAX_NOTIONAL_EUR", "100") or "100"),
        maker_by_default=_str2bool(g("MAKER_BY_DEFAULT", "true"), True),

        # пути
        data_dir=Path(g("DATA_DIR", "data") or "data"),
        nonce_file=Path(g("EXMO_NONCE_FILE", "data/.exmo_nonce") or "data/.exmo_nonce"),

        # логи
        log_level=g("LOG_LEVEL", "INFO") or "INFO",
        mask_api_keys_in_logs=_str2bool(g("MASK_API_KEYS_IN_LOGS", "true"), True),

        # debug
        debug=_str2bool(g("DEBUG", "false"), False),
    )
    s.validate()
    return s

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
