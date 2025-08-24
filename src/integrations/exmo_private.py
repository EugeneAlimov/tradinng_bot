# src/integrations/exmo_private.py
from __future__ import annotations

import os
import hmac
import hashlib
import urllib.parse
from typing import Dict, Any, Optional
import logging
import time

import requests

from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager
from src.infrastructure.resilience.circuit_breaker import ErrorRecoverySystem
from src.infrastructure.exchange.order_manager import OrderIDGenerator

logger = logging.getLogger(__name__)


class ExmoPrivate:
    """
    Приватный EXMO API клиент с:
      - thread-safe монотонным nonce
      - circuit breaker + retry
      - безопасной генерацией client_id (через OrderIDGenerator)
    Совместим по интерфейсу с существующим кодом.
    """
    def __init__(self,
                 api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 base_url: str = "https://api.exmo.com/v1.1",
                 timeout: int = 20):
        self.key = (api_key or os.environ.get("EXMO_KEY") or os.environ.get("EXMO_API_KEY") or "").strip()
        self.secret = (api_secret or os.environ.get("EXMO_SECRET") or os.environ.get("EXMO_API_SECRET") or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if not self.key or not self.secret:
            raise RuntimeError("EXMO credentials missing")

        self._secret_bytes = self.secret.encode("utf-8")
        nonce_path = os.environ.get("EXMO_NONCE_FILE", "data/.exmo_nonce")
        self._nonce = ThreadSafeNonceManager(nonce_path)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "tradinng_bot/1.0"})
        self._ers = ErrorRecoverySystem()
        self._id_gen = OrderIDGenerator()

    # ---------- Low-level ----------
    def _post_raw(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = dict(params or {})
        p["nonce"] = self._nonce.next()
        payload = urllib.parse.urlencode(p).encode("utf-8")
        sign = hmac.new(self._secret_bytes, payload, hashlib.sha512).hexdigest()
        headers = {"Key": self.key, "Sign": sign, "Content-Type": "application/x-www-form-urlencoded"}
        url = f"{self.base_url}/{method}"
        resp = self._session.post(url, data=p, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            err = str(data.get("error"))
            # мэп стандартных причин
            low = err.lower()
            if "nonce" in low or "flood" in low or "rate" in low:
                # пробрасываем, чтобы retry/circuit обработали
                raise RuntimeError(f"EXMO API error: {err}")
            raise RuntimeError(f"EXMO API error: {err}")
        return data

    def _post(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._ers.protected_call("exmo_api", self._post_raw, method, params)

    # ---------- Public-ish wrappers ----------
    def user_info(self) -> Dict[str, Any]:
        return self._post("user_info")

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params = {"pair": pair} if pair else None
        return self._post("user_open_orders", params)

    def order_cancel(self, order_id: str) -> Dict[str, Any]:
        return self._post("order_cancel", {"order_id": order_id})

    def order_trades(self, order_id: str) -> Dict[str, Any]:
        return self._post("order_trades", {"order_id": order_id})

    def ticker_pair(self, pair: str) -> Dict[str, Any]:
        # у EXMO «ticker» возвращает сразу все пары; чтобы не дергать избыточно — используем «ticker» и берём нужное
        data = self._post("ticker")
        if isinstance(data, dict):
            return data.get(pair, {})
        return {}

    # ---------- Trading ----------
    def order_create(self, pair: str, quantity: str, price: str, side: str, client_id: Optional[object] = None) -> Dict[str, Any]:
        """
        EXMO docs: client_id должен быть уникальным (int). Мы гарантируем уникальность.
        """
        params: Dict[str, Any] = {
            "pair": pair,
            "quantity": str(quantity),
            "price": str(price),
            "type": side.lower(),  # buy / sell
        }
        # если передан client_id — мягко валидируем; иначе генерируем
        cid: Optional[int] = None
        if client_id is not None:
            try:
                cid = int(str(client_id).strip())
            except Exception:
                cid = None
        if cid is None:
            cid = self._id_gen.generate()
        params["client_id"] = str(cid)
        return self._post("order_create", params)
