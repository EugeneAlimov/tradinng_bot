# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Any, Dict, Optional, Union, List

import requests


Number = Union[int, float, str]


class ExmoPrivate:
    """
    Мини-клиент приватного REST API EXMO v1.1.
    Авторизация: заголовки Key/Sign, подпись HMAC-SHA512 по urlencoded(body), параметр nonce.
    База: https://api.exmo.com/v1.1/{method}

    Нота bene:
    - Некоторые параметры могут отличаться между версиями API/аккаунтами. Мы передаём только то, что поддерживаем явно.
    - Параметр `immediate_or_cancel` пробрасываем ТОЛЬКО если он True — биржа может игнорировать его,
      а в live_trade мы и так реализуем «FOK-подобное» поведение (подождали и отменили остаток).
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

    # ---------- низкоуровневые утилиты ----------

    def _nonce(self) -> int:
        now = int(time.time() * 1000)  # мс
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
        POST с Key/Sign + nonce и надёжными ретраями.
        Повторяем на 429/5xx, таймаутах и типичных бизнес-ошибках (nonce/flood).
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
            # часто встречаются поля result/error
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
                    time.sleep(delay)
                    delay *= 1.7
                    continue
                raise
            except (requests.Timeout, requests.ConnectionError):
                if attempt < max_tries:
                    time.sleep(delay)
                    delay *= 1.7
                    continue
                raise
            except RuntimeError as e:
                msg = str(e).lower()
                # типовые бизнес-ошибки
                if any(k in msg for k in ("nonce", "flood", "too many", "try again")) and attempt < max_tries:
                    time.sleep(delay + random.random() * 0.5)  # type: ignore[name-defined]
                    delay *= 1.7
                    continue
                raise

    def _get_public(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{method}"
        r = requests.get(url, params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---------- публичные методы ----------

    def pair_settings(self, pair: Optional[str] = None) -> Dict[str, Any]:
        data = self._get_public("pair_settings")
        if pair:
            if isinstance(data, dict):
                return data.get(pair, {})
            return {}
        return data

    def ticker(self, pair: str) -> Dict[str, Any]:
        try:
            data = self._get_public("ticker")
        except Exception:
            return {}
        t = data.get(pair)
        return t if isinstance(t, dict) else {}

    def order_book(self, pair: str, limit: int = 20) -> Dict[str, Any]:
        try:
            data = self._get_public("order_book", params={"pair": pair, "limit": limit})
        except Exception:
            return {}
        ob = data.get(pair)
        return ob if isinstance(ob, dict) else {}

    # ---------- приватные методы ----------

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
        quantity: Number,
        price: Number,
        side: str,                     # "buy" | "sell"
        client_id: Optional[object] = None,
        immediate_or_cancel: bool = False,  # ← поддержка IOC (если биржа примет)
    ) -> Dict[str, Any]:
        """
        EXMO v1.1: order_create(pair, quantity, price, type, [client_id], [immediate_or_cancel?]).
        Мы приводим числа к строкам; client_id должен быть числом (строка-число).
        """
        def _num(x: Number) -> str:
            if isinstance(x, str):
                return x
            return f"{x:.16f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)

        params: Dict[str, Any] = {
            "pair": pair,
            "quantity": _num(quantity),
            "price": _num(price),
            "type": side,
        }
        if client_id is not None:
            try:
                params["client_id"] = str(int(str(client_id).strip()))
            except Exception:
                # некорректный client_id — безопасно игнорируем
                pass

        # Пробросим IOC-флаг, только если True (на некоторых аккаунтах/версиях его нет — биржа проигнорирует)
        if immediate_or_cancel:
            params["immediate_or_cancel"] = "true"

        return self._post("order_create", params)

    def order_cancel(self, order_id: str) -> Dict[str, Any]:
        return self._post("order_cancel", {"order_id": order_id})

    def order_trades(self, order_id: str) -> Dict[str, Any]:
        return self._post("order_trades", {"order_id": order_id})

    def order_status(self, pair: str, order_id: str) -> Dict[str, Any]:
        """
        Best-effort статус ордера.
        1) Пробуем получить сделки (fills) через order_trades → считаем исполненный объём.
        2) Если нет трейдов, смотрим user_open_orders(pair) → если ордер там есть — статус 'open'.
        3) Иначе считаем, что 'canceled' или 'unknown' (биржа может не вернуть явный статус).
        Возвращаем унифицированные поля: status, quantity_processed, price (по последнему fill или лимиту).
        """
        filled_qty = 0.0
        last_price = None

        try:
            tr = self.order_trades(order_id)
            # форматы разные: {'result': True, 'trades': [{'price': '...', 'quantity': '...'}, ...]}
            trades: List[Dict[str, Any]] = tr.get("trades") or tr.get("response") or []
            if isinstance(trades, dict):  # иногда словарь с id=>trade
                trades = list(trades.values())
            for t in trades:
                q = float(t.get("quantity") or t.get("qty") or 0.0)
                p = float(t.get("price") or 0.0)
                filled_qty += q
                last_price = p or last_price
        except Exception:
            pass

        if filled_qty > 0:
            return {
                "status": "filled",  # может быть partial, но для live_trade это достаточно
                "quantity_processed": filled_qty,
                "price": last_price,
            }

        try:
            open_orders = self.user_open_orders(pair=pair)
            orders = open_orders.get(pair) if isinstance(open_orders, dict) else None
            if isinstance(orders, list):
                for o in orders:
                    if str(o.get("order_id")) == str(order_id):
                        # EXMO иногда отдаёт 'quantity' и 'quantity_left'/'quantity_processed'
                        qp = float(o.get("quantity_processed") or o.get("filled_qty") or 0.0)
                        pr = float(o.get("price") or 0.0)
                        return {
                            "status": "open",
                            "quantity_processed": qp,
                            "price": pr,
                        }
        except Exception:
            pass

        # не нашли — считаем отменён/неизвестен
        return {
            "status": "canceled",
            "quantity_processed": 0.0,
            "price": last_price or 0.0,
        }
