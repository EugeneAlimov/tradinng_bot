# src/infrastructure/exchange/http_utils.py
from __future__ import annotations

import json
import time
import threading
from typing import Any, Dict, Tuple, Optional, Callable

class SimpleTTLCache:
    """
    Очень простой in-memory TTL-кэш (потокобезопасный).
    Ключом делаем tuple (method, url, frozen_params_json).
    """
    def __init__(self, max_items: int = 1024):
        self._data: Dict[Tuple[str, str, str], Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max = max_items

    @staticmethod
    def _freeze_params(params: Optional[Dict[str, Any]]) -> str:
        if not params:
            return "{}"
        # сортируем ключи, чтобы одинаковые словари давали одинаковую строку
        return json.dumps(params, sort_keys=True, separators=(",", ":"))

    def get(self, method: str, url: str, params: Optional[Dict[str, Any]]) -> Optional[Any]:
        key = (method.upper(), url, self._freeze_params(params))
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < now:
                self._data.pop(key, None)
                return None
            return value

    def set(self, method: str, url: str, params: Optional[Dict[str, Any]], value: Any, ttl: float) -> None:
        key = (method.upper(), url, self._freeze_params(params))
        exp = time.time() + max(0.0, ttl)
        with self._lock:
            if len(self._data) >= self._max:
                # простая эвикция: зачистим просроченные/старые
                now = time.time()
                dead = [k for k, (e, _) in self._data.items() if e < now]
                for k in dead:
                    self._data.pop(k, None)
                if len(self._data) >= self._max:
                    # удалим произвольно один элемент
                    self._data.pop(next(iter(self._data)), None)
            self._data[key] = (exp, value)


class RateLimiter:
    """
    Простой рейткеппер: гарантирует минимальный интервал между запросами.
    Отдельный инстанс — для public и для private.
    """
    def __init__(self, min_interval_sec: float):
        self._min = float(min_interval_sec)
        self._lock = threading.Lock()
        self._last_ts = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            delta = now - self._last_ts
            if delta < self._min:
                time.sleep(self._min - delta)
            self._last_ts = time.time()


def with_retries(fn: Callable[[], Any], attempts: int = 3, backoff_base: float = 0.25) -> Any:
    """
    Универсальный ретрайзер. Повторяет вызов fn() при сетевых/серверных сбоях.
    Исключения от fn пробрасывает после исчерпания попыток.
    """
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            time.sleep(backoff_base * (2 ** i))
    if last_err:
        raise last_err
