# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Any, Dict, Optional

import requests


class ExmoPrivate:
    """
    Мини-клиент приватного REST API EXMO v1.1.
    Авторизация: заголовки Key/Sign, подпись HMAC-SHA512 по urlencoded(body), параметр nonce.
    База: https://api.exmo.com/v1.1/{method}
    Документация/список методов см. в официальной Postman-коллекции и блог-статьях EXMO.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.exmo.com/v1.1", timeout: int = 20):
        if not api_key or not api_secret:
            raise ValueError("EXMO key/secret are required")
        self.key = api_key
        self.secret = api_secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._last_nonce: int = 0
        # простая персистентность nonce, чтобы избежать коллизий между перезапусками
        self._nonce_file = os.environ.get("EXMO_NONCE_FILE", "data/.exmo_nonce")

    def _nonce(self) -> int:
        now = int(time.time() * 1000)  # мс
        # обеспечим строго возрастающий nonce
        last = self._last_nonce
        if os.path.exists(self._nonce_file):
            try:
                with open(self._nonce_file, "r") as f:
                    last = max(last, int(f.read().strip() or "0"))
            except Exception:
                pass
        n = max(now, last + 1)
        self._last_nonce = n
        try:
            os.makedirs(os.path.dirname(self._nonce_file), exist_ok=True)
            with open(self._nonce_file, "w") as f:
                f.write(str(n))
        except Exception:
            pass
        return n

    def _sign(self, params: Dict[str, Any]) -> str:
        payload = urllib.parse.urlencode(params).encode("utf-8")
        return hmac.new(self.secret, payload, hashlib.sha512).hexdigest()

    def _post(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        POST c Key/Sign + nonce и надёжными ретраями.
        - Повторяем на 429/5xx, таймаутах и типичных бизнес-ошибках (nonce/flood).
        - Экспоненциальный бэкофф.
        """
        import random
        params = dict(params or {})

        def _once(payload: Dict[str, Any]) -> Dict[str, Any]:
            payload = dict(payload)
            payload["nonce"] = self._nonce()
            headers = {
                "Key": self.key,
                "Sign": self._sign(payload),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            url = f"{self.base_url}/{method}"
            r = requests.post(url, data=payload, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            # форматы разные; часто встречаются поля result/error
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(str(data.get("error")))
            return data

        max_tries = 5
        delay = 0.8
        for attempt in range(1, max_tries + 1):
            try:
                return _once(params)
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else None
                if code in (429, 500, 502, 503, 504) and attempt < max_tries:
                    time.sleep(delay);
                    delay *= 1.7;
                    continue
                raise
            except (requests.Timeout, requests.ConnectionError):
                if attempt < max_tries:
                    time.sleep(delay);
                    delay *= 1.7;
                    continue
                raise
            except RuntimeError as e:
                msg = str(e).lower()
                # типичные сообщения биржи: "nonce", "flood", "too many requests"
                if any(k in msg for k in ("nonce", "flood", "too many", "try again")) and attempt < max_tries:
                    time.sleep(delay + random.random() * 0.5);
                    delay *= 1.7;
                    continue
                raise

    # ===== Удобные обёртки по популярным методам =====
    def user_info(self) -> Dict[str, Any]:
        return self._post("user_info")

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if pair:
            params["pair"] = pair
        return self._post("user_open_orders", params)

    def order_create(
            self,
            pair: str,
            quantity: str,
            price: str,
            side: str,  # "buy" | "sell"
            client_id: Optional[object] = None,  # может прийти int/str
    ) -> Dict[str, Any]:
        """
        EXMO v1.1: order_create(pair, quantity, price, type, [client_id]).
        ВНИМАНИЕ: client_id должен быть ЧИСЛОМ. Если не приводится к int — не отправляем.
        """
        params: Dict[str, Any] = {
            "pair": pair,
            "quantity": quantity,
            "price": price,
            "type": side,
        }
        if client_id is not None:
            try:
                # приводим к int → обратно в строку (как обычно у REST)
                params["client_id"] = str(int(str(client_id).strip()))
            except Exception:
                # некорректный client_id — безопасно игнорируем
                pass

        return self._post("order_create", params)

    def order_cancel(self, order_id: str) -> Dict[str, Any]:
        return self._post("order_cancel", {"order_id": order_id})

    def order_trades(self, order_id: str) -> Dict[str, Any]:
        return self._post("order_trades", {"order_id": order_id})

    def _get_public(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Публичные методы EXMO (без подписи). Например: pair_settings.
        """
        url = f"{self.base_url}/{method}"
        r = requests.get(url, params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def pair_settings(self, pair: Optional[str] = None) -> Dict[str, Any]:
        """
        Возвращает настройки торговых пар.
        Если pair задан, возвращает словарь настроек только для этой пары.
        Поля у EXMO могут называться по-разному в зависимости от версии:
        - 'price_precision' или 'price_scale', 'price_decimals'
        - 'min_quantity', 'quantity_step'
        - 'min_amount' (минимальная сумма для сделки)
        Мы не делаем сильных предположений — просто возвращаем как есть.
        """
        data = self._get_public("pair_settings")
        if pair:
            if isinstance(data, dict):
                return data.get(pair, {})
            return {}
        return data

    def ticker(self, pair: str) -> Dict[str, Any]:
        """Публичный тикер. Возвращает словарь по запрошенной паре или {}."""
        try:
            data = self._get_public("ticker")  # должен уже быть в классе
        except Exception:
            return {}
        t = data.get(pair)
        return t if isinstance(t, dict) else {}

    def order_book(self, pair: str, limit: int = 20) -> Dict[str, Any]:
        """
        Публичный стакан. Возвращает {'ask': [[price, qty], ...], 'bid': [[price, qty], ...]} для пары,
        либо {}. Параметр limit - желаемая глубина.
        """
        try:
            data = self._get_public("order_book", params={"pair": pair, "limit": limit})
        except Exception:
            return {}
        ob = data.get(pair)
        return ob if isinstance(ob, dict) else {}
