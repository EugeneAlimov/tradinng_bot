# src/infrastructure/exmo_cache.py
from __future__ import annotations

import json, os, time, hashlib
from typing import Any, Dict, Optional, Tuple

DEFAULT_CACHE_DIR = ".cache/candles"
DEFAULT_TTL_SEC = 60  # 1 минута актуальности окна


def _key(pair: str, res_min: int, since: int, to: int) -> str:
    raw = f"{pair}|{res_min}|{since}|{to}".encode()
    return hashlib.md5(raw).hexdigest()  # достаточно для имени файла


def _path(cache_dir: str, key: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{key}.json")


def save_cache(data: Dict[str, Any], pair: str, res_min: int, since: int, to: int,
               cache_dir: str = DEFAULT_CACHE_DIR) -> None:
    fp = _path(cache_dir, _key(pair, res_min, since, to))
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, fp)


def load_cache(pair: str, res_min: int, since: int, to: int,
               cache_dir: str = DEFAULT_CACHE_DIR, ttl_sec: int = DEFAULT_TTL_SEC) -> Optional[Dict[str, Any]]:
    fp = _path(cache_dir, _key(pair, res_min, since, to))
    try:
        st = os.stat(fp)
        if (time.time() - st.st_mtime) > ttl_sec:
            return None
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def fetch_with_cache(exmo, pair: str, res_min: int, since: int, to: int,
                     cache_dir: str = DEFAULT_CACHE_DIR, ttl_sec: int = DEFAULT_TTL_SEC) -> Dict[str, Any]:
    """
    Сначала пробуем сеть; при успехе пишем кеш.
    При сетевой ошибке — пробуем кеш (если свежий), иначе кидаем исключение дальше.
    """
    try:
        data = exmo.candles_history(pair, res_min, since, to)
        try:
            save_cache(data, pair, res_min, since, to, cache_dir)
        except Exception:
            pass
        return data
    except Exception:
        cached = load_cache(pair, res_min, since, to, cache_dir, ttl_sec)
        if cached is not None:
            return cached
        raise
