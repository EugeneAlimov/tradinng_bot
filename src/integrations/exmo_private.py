# src/integrations/exmo_private.py
from __future__ import annotations

import os
import time
import hmac
import hashlib
import urllib.parse
import logging
from typing import Any, Dict, Optional

import requests

from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager
from src.infrastructure.exchange.order_manager import OrderIDGenerator  # для резервной генерации client_id (если не задан)

logger = logging.getLogger(__name__)


class ExmoPrivate:
    """
    Минимальная приватная интеграция c EXMO v1.1 с:
      - thread/process-safe nonce
      - безопасной генерацией client_id (если не задан)
      - без вывода ключей в логи

    Методы, ожидаемые остальным кодом:
      - user_info()
      - user_open_orders(pair: Optional[str] = None)
      - order_create(pair, quantity, price, side, client_id: Optional[object] = None)
      - order_cancel(order_id)
      - order_trades(order_id)
      - ticker_pair(pair)   # через общий 'ticker'
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.exmo.com/v1.1",
        timeout: int = 20,
        nonce_storage: Optional[str] = None,
    ) -> None:
        self.key = str(api_key or "")
        self.secret = str(api_secret or "").encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)

        # nonce с файловой блокировкой
        nonce_file = nonce_storage or os.environ.get("EXMO_NONCE_FILE", "data/.exmo_nonce")
        self.nonce = ThreadSafeNonceManager(nonce_file)

        # сессия HTTP
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "tradinng-bot/EXMO"})

        # резервный генератор client_id (если вызывающая сторона не передала)
        self._client_id_gen = OrderIDGenerator()

    # ------------------------- низкоуровневые утилиты -------------------------

    def _sign_and_post(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{method}"
        p: Dict[str, Any] = dict(params or {})
        # гарантируем уникальный nonce
        p["nonce"] = self.nonce.get_next_nonce()

        payload = urllib.parse.urlencode(p).encode("utf-8")
        sign = hmac.new(self.secret, payload, hashlib.sha512).hexdigest()

        headers = {
            "Key": self.key,
            "Sign": sign,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # ВНИМАНИЕ: не логируем ключ/секрет!
        # Логируем только имя метода и набор ключей параметров без значений
        try:
            resp = self.session.post(url, data=p, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error("HTTP error %s on %s: %s", method, url, e)
            raise
        except ValueError as e:
            logger.error("JSON decode error on %s: %s", method, e)
            raise

        if isinstance(data, dict) and data.get("error"):
            # EXMO специфичная строка ошибки
            err = str(data.get("error"))
            logger.warning("EXMO error on %s: %s", method, err)
            raise RuntimeError(f"EXMO API error: {err}")

        return data

    # ------------------------- публичные методы, ожидаемые проектом -------------------------

    def user_info(self) -> Dict[str, Any]:
        return self._sign_and_post("user_info")

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if pair:
            params["pair"] = pair
        return self._sign_and_post("user_open_orders", params)

    def order_create(
        self,
        pair: str,
        quantity: Any,
        price: Any,
        side: str,
        client_id: Optional[object] = None,
    ) -> Dict[str, Any]:
        """
        Создание ордера. Гарантируем уникальный и валидный client_id.
        EXMO ожидает:
          - pair: "DOGE_EUR"
          - quantity: str/float
          - price: str/float
          - type: "buy"/"sell"
          - client_id: str (целое положительное, обычно <= int32)
        """
        if not pair or "_" not in pair:
            raise ValueError(f"Invalid pair: {pair}")

        side = str(side or "").lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}")

        params: Dict[str, Any] = {
            "pair": pair,
            "quantity": str(quantity),
            "price": str(price),
            "type": side,
        }

        # безопасная обработка client_id
        if client_id is None:
            cid = self._client_id_gen.generate()
        else:
            try:
                cid = int(str(client_id).strip())
                if cid <= 0:
                    raise ValueError("client_id must be positive")
            except Exception:
                # если пришло мусорное значение — сгенерируем сами
                cid = self._client_id_gen.generate()

        # EXMO обычно принимает client_id как строку
        params["client_id"] = str(cid % 2_147_483_647)

        return self._sign_and_post("order_create", params)

    def order_cancel(self, order_id: Any) -> Dict[str, Any]:
        params = {"order_id": str(order_id)}
        return self._sign_and_post("order_cancel", params)

    def order_trades(self, order_id: Any) -> Dict[str, Any]:
        params = {"order_id": str(order_id)}
        return self._sign_and_post("order_trades", params)

    def ticker_pair(self, pair: str) -> Optional[Dict[str, Any]]:
        """
        EXMO v1.1 'ticker' возвращает весь скоуп. Здесь — обертка по конкретной паре.
        """
        data = self._sign_and_post("ticker")
        if isinstance(data, dict):
            return data.get(pair)
        return None
