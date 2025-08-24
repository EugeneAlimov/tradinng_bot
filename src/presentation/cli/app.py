# src/presentation/cli/app.py
from __future__ import annotations

import os
import logging
from typing import Tuple

from src.security.credentials import SecureCredentialsManager

logger = logging.getLogger(__name__)


def _load_env_file(path: str) -> None:
    """
    Загружает .env (если необходимо) и НЕ выводит ключи ни в каком виде.
    Оставлено для совместимости с текущим CLI.
    """
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    # Не печатаем значение, просто выставляем
                    os.environ.setdefault(k, v)
        logger.info("[env] .env loaded")
    except Exception as e:
        logger.warning("[env] load failed: %s", e)


def load_credentials() -> Tuple[str, str]:
    """
    Унифицированная загрузка ключей EXMO.
    Никаких хвостов/длин ключей в лог не выводим.
    """
    mgr = SecureCredentialsManager()
    key, secret = mgr.get_credentials("exmo")
    logger.info("[security] credentials loaded")
    return key, secret
