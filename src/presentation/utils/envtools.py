# src/presentation/utils/envtools.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Tuple


def _parse_env_line(line: str) -> Tuple[str, str] | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if "=" not in s:
        return None
    k, v = s.split("=", 1)
    k = k.strip()
    v = v.strip().strip("'").strip('"')
    if not k:
        return None
    return k, v


def load_env_file(path: str | os.PathLike[str] = ".env", override: bool = False) -> int:
    """
    Простой загрузчик .env без зависимостей.
    - Комментарии начинаются с '#'
    - Формат: KEY=VALUE (кавычки у VALUE допустимы)
    - override=False — не перезаписывает уже существующие переменные окружения
    Возвращает количество загруженных ключей.
    """
    p = Path(path)
    if not p.exists():
        return 0
    loaded = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if not parsed:
            continue
        k, v = parsed
        if override or (k not in os.environ):
            os.environ[k] = v
            loaded += 1
    return loaded
