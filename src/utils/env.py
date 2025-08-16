# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import re
from typing import Dict, Tuple

_ENV_LINE = re.compile(
    r"""^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>.+?)\s*$"""
)

def _unquote(v: str) -> str:
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    return v

def load_env_file(path: str = ".env", override: bool = False) -> Tuple[int, Dict[str, str]]:
    """
    Простейший .env-лоадер:
      - понимает строки вида:  KEY=VAL,  export KEY=VAL,  KEY="VAL"
      - игнорирует пустые и начинающиеся с '#'
      - override: перетирать уже существующие переменные окружения или нет
    Возвращает (кол-во_загруженных, словарь_загруженных).
    """
    loaded: Dict[str, str] = {}
    if not path or not os.path.exists(path):
        return 0, loaded

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = _ENV_LINE.match(line)
            if not m:
                continue
            k = m.group("key")
            v = _unquote(m.group("val"))
            if override or (k not in os.environ):
                os.environ[k] = v
                loaded[k] = v
    return len(loaded), loaded
