from __future__ import annotations

import os
from typing import Optional

_ENV_LOADED: bool = False


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
