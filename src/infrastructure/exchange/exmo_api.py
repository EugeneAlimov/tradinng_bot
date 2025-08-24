# src/infrastructure/exchange/exmo_api.py
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional, Tuple

from src.config.settings import get_settings
from src.infrastructure.exchange.http_utils import HttpClient

LOG = logging.getLogger("exmo.api")


class ExmoAPI:
    """
    Мини‑обёртка EXMO (v1.1). Делает правильное склеивание URL без двойного /v1.1/.
    Публичные методы через GET, приватные — через POST с HMAC‑SHA512 подписью.
    """

    PUBLIC_BASE = "https://api.exmo.com/v1.1/"
    PRIVATE_BASE = "https://api.exmo.com/v1.1/"

    def __init__(self, key: str = "", secret: str = "", timeout_sec: float = 10.0,
                 retries: int = 3, backoff_factor: float = 0.3, debug: bool = False):
        self.key = (key or "").strip()
        self.secret = (secret or "").encode()
        self.pub = HttpClient(self.PUBLIC_BASE, timeout_sec=timeout_sec, retries=retries,
                              backoff_factor=backoff_factor, debug=debug, user_agent="tradinng-bot/StageA")
        self.priv = HttpClient(self.PRIVATE_BASE, timeout_sec=timeout_sec, retries=retries,
                               backoff_factor=backoff_factor, debug=debug, user_agent="tradinng-bot/StageA")

    # -------- helpers --------
    def _signed_headers(self, payload: Dict[str, Any]) -> Dict[str, str]:
        body = "&".join(f"{k}={payload[k]}" for k in payload)
        sign = hmac.new(self.secret, body.encode(), hashlib.sha512).hexdigest()
        return {"Key": self.key, "Sign": sign}

    def _require_keys(self):
        if not (self.key and self.secret):
            raise RuntimeError("EXMO api keys are not set (EXMO_KEY/EXMO_SECRET)")

    # -------- public endpoints --------
    def candles_history(self, symbol: str, resolution: int, since_ts: int, till_ts: int) -> Any:
        """
        Получить свечи: https://api.exmo.com/v1.1/candles_history
        NOTE: аккуратно формируем путь, чтобы не получилось /v1.1/v1.1/...
        """
        return self.pub.get("candles_history", {
            "symbol": symbol,
            "resolution": resolution,
            "from": since_ts,
            "to": till_ts
        })

    def ticker(self) -> Any:
        return self.pub.get("ticker")

    # -------- private endpoints --------
    def user_info(self) -> Any:
        self._require_keys()
        payload = {"nonce": int(time.time() * 1000)}
        headers = self._signed_headers(payload)
        return self.priv.post("user_info", data=payload, headers=headers)

    def user_trades(self, pair: str, limit: int = 100) -> Any:
        self._require_keys()
        payload = {"nonce": int(time.time() * 1000), "pair": pair, "limit": limit}
        headers = self._signed_headers(payload)
        return self.priv.post("user_trades", data=payload, headers=headers)

    def order_create(self, pair: str, quantity: float, price: float, type_: str = "buy") -> Any:
        self._require_keys()
        payload = {
            "nonce": int(time.time() * 1000),
            "pair": pair,
            "quantity": quantity,
            "price": price,
            "type": type_,
        }
        headers = self._signed_headers(payload)
        return self.priv.post("order_create", data=payload, headers=headers)

    def order_cancel(self, order_id: int) -> Any:
        self._require_keys()
        payload = {"nonce": int(time.time() * 1000), "order_id": order_id}
        headers = self._signed_headers(payload)
        return self.priv.post("order_cancel", data=payload, headers=headers)


def build_exmo_from_settings():
    """
    Удобный фабричный метод: подхватывает EXMO_* и DEBUG флаги из Settings.
    """
    s = get_settings()
    return ExmoAPI(
        key=s.exmo_key,
        secret=s.exmo_secret,
        timeout_sec=s.http_timeout_sec,
        retries=s.http_retries,
        backoff_factor=s.http_backoff_factor,
        debug=s.exmo_debug or s.debug,
    )
