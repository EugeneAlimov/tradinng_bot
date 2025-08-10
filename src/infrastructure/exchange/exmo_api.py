# src/infrastructure/exchange/exmo_api.py
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests

from .http_utils import SimpleTTLCache, RateLimiter, with_retries


@dataclass
class ExmoCredentials:
    api_key: str = ""
    api_secret: str = ""


@dataclass
class ExmoApi:
    """
    Лёгкий клиент EXMO (по умолчанию read-only).
    Публичные и приватные методы. Торговые выключены, пока allow_trading=False.
    """
    creds: ExmoCredentials = field(default_factory=ExmoCredentials)
    base_url: str = "https://api.exmo.com/v1.1"
    timeout: float = 15.0
    user_agent: str = "clean-crypto-bot/0.1"
    allow_trading: bool = False  # безопасность

    # настройки кэша/лимитов
    cache_ttls: Dict[str, float] = field(default_factory=lambda: {
        # endpoint -> TTL seconds
        "ticker": 1.0,
        "order_book": 0.5,
        "trades": 0.5,
        "candles": 0.5,
        "kline": 0.5,
        "ohlcv": 0.5,
        "ping": 0.5,
        # приватные сознательно не кэшируем по умолчанию
    })
    public_min_interval: float = 0.25   # ~4 rps
    private_min_interval: float = 0.5   # ~2 rps
    retry_attempts: int = 3

    def __post_init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})
        self._cache = SimpleTTLCache(max_items=2048)
        self._rl_public = RateLimiter(self.public_min_interval)
        self._rl_private = RateLimiter(self.private_min_interval)

    # ── низкоуровневые HTTP ─────────────────────────────────────────────
    def _sign_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.creds.api_key or not self.creds.api_secret:
            raise RuntimeError("EXMO creds are not set")
        payload = dict(payload)
        payload["nonce"] = int(time.time() * 1000)
        b = "&".join(f"{k}={payload[k]}" for k in sorted(payload))
        sig = hmac.new(self.creds.api_secret.encode(), b.encode(), hashlib.sha512).hexdigest()
        headers = {
            "Key": self.creds.api_key,
            "Sign": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return {"data": b, "headers": headers}

    def _public_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, use_cache: bool = True) -> Any:
        url = f"{self.base_url}/{endpoint}"
        ttl = self.cache_ttls.get(endpoint, 0.0) if use_cache else 0.0

        def _do():
            self._rl_public.wait()
            r = self._session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            # форматы у v1.1 разные: иногда {"result":...,"error":...}, иногда сразу объект
            if isinstance(data, dict) and "error" in data and data.get("error"):
                raise RuntimeError(f"EXMO error: {data.get('error')}")
            return data

        if ttl > 0:
            cached = self._cache.get("GET", url, params)
            if cached is not None:
                return cached
            data = with_retries(_do, attempts=self.retry_attempts)
            self._cache.set("GET", url, params, data, ttl)
            return data
        else:
            return with_retries(_do, attempts=self.retry_attempts)

    def _private_post(self, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{endpoint}"
        payload = payload or {}

        def _do():
            self._rl_private.wait()
            signed = self._sign_payload(payload)
            r = self._session.post(url, headers=signed["headers"], data=signed["data"], timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("Malformed EXMO response")
            # приватные ответы почти всегда {"result": True/False, "error": "...", ...}
            if data.get("error"):
                raise RuntimeError(f"EXMO error: {data['error']}")
            # некоторые методы кладут полезную нагрузку в поля без "result"
            return data

        return with_retries(_do, attempts=self.retry_attempts)

    # ── публичные методы ───────────────────────────────────────────────
    def ping(self) -> bool:
        # ping'а в v1.1 нет, эмулируем быстрым /ticker с cache TTL
        try:
            _ = self.ticker()
            return True
        except Exception:
            return False

    def ticker(self) -> Dict[str, Dict[str, str]]:
        return self._public_get("ticker", params=None, use_cache=True)

    def ticker_pair(self, pair: str) -> Dict[str, str]:
        tk = self.ticker()
        return tk.get(pair, {}) if isinstance(tk, dict) else {}

    def order_book(self, pair: str, limit: int = 50) -> Dict[str, Any]:
        return self._public_get("order_book", params={"pair": pair, "limit": int(limit)}, use_cache=True)

    def trades(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        # В v1.1 публичные trades — endpoint 'trades', параметр pair и limit
        raw = self._public_get("trades", params={"pair": pair, "limit": int(limit)}, use_cache=True)
        # формат: {"PAIR":[{...}, ...]} либо {"result":...,"error":...}
        if isinstance(raw, dict) and pair in raw:
            return raw[pair]
        return []

    # В проекте уже реализованы обёртки под свечи:
    def candles(self, pair: str, timeframe: str = "1m", limit: int = 50):
        """
        Базовые свечи. Ходим только в "candles" эндпоинт и НИКУДА неfallback-аем,
        чтобы избежать рекурсии. Возвращаем [] если пусто/ошибка.
        Ожидаемый ответ: list[dict] с ключами ts/open/high/low/close/volume (как у нас в проекте).
        Если придёт list[list], нормализуем.
        """
        try:
            # ❶ Подстрой путь под твой рабочий эндпоинт.
            # Раньше у нас candles работал — вероятно, это был "candles" или "candles_history".
            data = self._public_get("candles", params={"symbol": pair, "interval": timeframe, "limit": limit})
            if isinstance(data, list):
                if data and isinstance(data[0], list):
                    # нормализуем [ts,o,h,l,c,v] → dict
                    return [
                        {"ts": int(r[0]), "open": str(r[1]), "high": str(r[2]),
                         "low": str(r[3]), "close": str(r[4]), "volume": str(r[5])}
                        for r in data
                    ]
                return data
        except RuntimeError as e:
            # если это "API function do not exist" — не ретраимся бесконечно
            if "do not exist" in str(e):
                return []
        except Exception:
            pass
        return []

    def kline(self, pair: str, timeframe: str = "1m", limit: int = 50):
        """
        Агрегированные свечи. Если пусто — НЕТ взаимного вызова candles здесь.
        Возвращаем [] при ошибке/пустом ответе.
        """
        try:
            data = self._public_get("kline", params={"symbol": pair, "interval": timeframe, "limit": limit})
            if isinstance(data, list):
                # может быть уже dict-список или list[list]
                if data and isinstance(data[0], list):
                    return [
                        {"ts": int(r[0]), "open": str(r[1]), "high": str(r[2]),
                         "low": str(r[3]), "close": str(r[4]), "volume": str(r[5])}
                        for r in data
                    ]
                return data
        except RuntimeError as e:
            if "do not exist" in str(e):
                return []
        except Exception:
            pass
        return []

    def ohlcv(self, pair: str, timeframe: str = "1m", limit: int = 50):
        """
        Унифицированная обёртка: пробуем нативный ohlcv.
        Если пусто — fallback → kline, и только если снова пусто — fallback → candles.
        Никакой обратной рекурсии.
        """
        try:
            data = self._public_get("ohlcv", params={"symbol": pair, "interval": timeframe, "limit": limit})
            if isinstance(data, list) and data:
                if isinstance(data[0], list):
                    return [
                        {"ts": int(r[0]), "open": str(r[1]), "high": str(r[2]),
                         "low": str(r[3]), "close": str(r[4]), "volume": str(r[5])}
                        for r in data
                    ]
                return data
        except RuntimeError as e:
            if "do not exist" not in str(e):
                # если это не 'do not exist' — просто сваливаемся на kline
                pass
        except Exception:
            pass

        # fallback 1: kline
        kl = self.kline(pair=pair, timeframe=timeframe, limit=limit)
        if kl:
            return kl

        # fallback 2: candles
        cd = self.candles(pair=pair, timeframe=timeframe, limit=limit)
        if cd:
            return cd

        return []

    # ── приватные методы (read-only) ───────────────────────────────────
    def user_balances(self) -> Dict[str, Decimal]:
        raw = self._private_post("user_info")
        # форматы у EXMO различаются; ожидаем balances в "balances" или "balances":{"USD":"..."}
        balances = raw.get("balances") or raw.get("wallet") or {}
        out: Dict[str, Decimal] = {}
        for k, v in balances.items():
            try:
                out[k] = Decimal(str(v))
            except Exception:
                out[k] = Decimal("0")
        return out

    def user_open_orders(self, pair: str) -> Dict[str, Any]:
        return self._private_post("user_open_orders", {"pair": pair})

    def user_trades(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        raw = self._private_post("user_trades", {"pair": pair, "limit": int(limit)})
        # формат обычно {"result":True, "error":"", "trades":[{...}]}
        trades = raw.get("trades")
        if isinstance(trades, list):
            return trades
        # иногда {"PAIR":[...]}
        if pair in raw and isinstance(raw[pair], list):
            return raw[pair]
        return []
