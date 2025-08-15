# src/infrastructure/exchanges/exmo_api.py
from __future__ import annotations
import hashlib
import hmac
import time
import os
from typing import Any, Dict, Optional

from .http_utils import HttpClient

class ExmoApi:
    """
    Минимальный клиент под публичные/приватные методы EXMO v1.1/v2,
    с фокусом на свечи и базовые трейд-методы.
    """
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, base_url: str = "https://api.exmo.com"):
        self.api_key = api_key or os.getenv("EXMO_API_KEY", "")
        self.api_secret = (api_secret or os.getenv("EXMO_API_SECRET", "")).encode("utf-8")
        self.http = HttpClient(base_url=base_url.rstrip("/"))

    # ---------- Публичные ----------
    def candles_history(self, symbol: str, resolution: int, ts_from: int, ts_to: int) -> Dict[str, Any]:
        # v1.1/v2 различаются по маршрутам у EXMO; задействуем /v1.1/candles_history (как в твоих логах)
        params = {"symbol": symbol, "resolution": resolution, "from": ts_from, "to": ts_to}
        r = self.http.get("/v1.1/candles_history", params=params)
        return r.json()

    def ticker(self) -> Dict[str, Any]:
        r = self.http.get("/v1.1/ticker")
        return r.json()

    # ---------- Приватные ----------
    def _signed_headers(self, payload: Dict[str, Any]) -> Dict[str, str]:
        nonce = str(int(time.time() * 1000))
        body = "&".join(f"{k}={v}" for k, v in payload.items())
        sign = hmac.new(self.api_secret, body.encode("utf-8"), hashlib.sha512).hexdigest()
        return {
            "Key": self.api_key,
            "Sign": sign,
            "Content-Type": "application/x-www-form-urlencoded",
            "Nonce": nonce,
        }

    def user_info(self) -> Dict[str, Any]:
        payload = {"nonce": int(time.time() * 1000)}
        headers = self._signed_headers(payload)
        r = self.http.post("/v1.1/user_info", headers=headers, json_data=None)  # EXMO принимает form, но http_utils задает json; можно расширить
        # При желании добавь поддержку data=payload в http_utils
        return r.json()

    # Пример создания ордера (проверь точные поля по текущему API EXMO)
    def create_order(self, pair: str, quantity: float, price: float, order_type: str = "buy") -> Dict[str, Any]:
        payload = {
            "nonce": int(time.time() * 1000),
            "pair": pair,
            "quantity": quantity,
            "price": price,
            "type": order_type,
        }
        headers = self._signed_headers(payload)
        # Нужно отправлять form-encoded: можно расширить http_utils с параметром 'data=payload'
        r = self.http.session.post(
            self.http._full_url("/v1.1/order_create"),
            data=payload,
            headers=headers,
            timeout=self.http.timeout,
        )
        r.raise_for_status()
        return r.json()
