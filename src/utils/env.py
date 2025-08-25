# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from typing import Dict, Tuple


def _strip_inline_comment(s: str) -> str:
    """Убираем #комментарий, если он вне кавычек."""
    out = []
    in_sq = in_dq = False
    for ch in s:
        if ch == "'" and not in_dq:
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch == "#" and not in_sq and not in_dq:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(v: str) -> str:
    v = v.strip()
    if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in ("'", '"')):
        return v[1:-1]
    return v


def _split_kv(line: str) -> tuple[str, str] | tuple[None, None]:
    """
    Разбираем:
      KEY=VAL
      export KEY=VAL
      KEY: VAL
      (поддержка кавычек и инлайн-комментов)
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None, None
    if s.startswith("export "):
        s = s[7:].lstrip()

    # ищем первый = или : вне кавычек
    in_sq = in_dq = False
    pos = -1
    for i, ch in enumerate(s):
        if ch == "'" and not in_dq:
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch in ("=", ":") and not in_sq and not in_dq:
            pos = i;
            break
    if pos <= 0:
        return None, None

    k = s[:pos].strip()
    v = s[pos + 1:].strip()
    if not k:
        return None, None

    v = _strip_inline_comment(v)
    v = _unquote(v)
    return k, v


def load_env_file(path: str = ".env", override: bool = False) -> Tuple[int, Dict[str, str]]:
    """
    Простейший .env-лоадер:
      - KEY=VAL, export KEY=VAL, KEY: VAL
      - кавычки и инлайн-комменты '# ...' поддерживаются
      - override: перетирать уже существующие os.environ или нет
    Возвращает (кол-во_загруженных, словарь_загруженных).
    """
    loaded: Dict[str, str] = {}
    if not path or not os.path.exists(path):
        return 0, loaded

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            k, v = _split_kv(raw)
            if not k:
                continue
            if override or (k not in os.environ):
                os.environ[k] = v
                loaded[k] = v
    return len(loaded), loaded
