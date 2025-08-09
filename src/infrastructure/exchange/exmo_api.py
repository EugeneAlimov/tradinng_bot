from __future__ import annotations

import time
import hmac
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Tuple
from urllib.parse import urlencode

import requests
from decimal import Decimal, InvalidOperation

from src.config.env import load_env, env_str


# ======== ВСПОМОГАТЕЛЬНОЕ ========

def _d(x: Any) -> Decimal:
    try:
        if isinstance(x, Decimal):
            return x
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _now_ms() -> int:
    return int(time.time() * 1000)

def __post_init__(self) -> None:
    # Если ключи не заданы — пробуем взять из .env
    if not self.creds.api_key or not self.creds.api_secret:
        load_env()
        self.creds.api_key = self.creds.api_key or env_str("EXMO_API_KEY", "")
        self.creds.api_secret = self.creds.api_secret or env_str("EXMO_API_SECRET", "")
    # Если включена торговля, ключи обязательны
    if self.allow_trading and (not self.creds.api_key or not self.creds.api_secret):
        raise RuntimeError("EXMO creds are not set")


@dataclass
class ExmoCredentials:
    api_key: str = ""
    api_secret: str = ""


@dataclass
class ExmoApi:
    """
    Лёгкий клиент EXMO (по умолчанию read-only).
    Реализованы безопасные публичные и приватные методы ТОЛЬКО-ДЛЯ-ЧТЕНИЯ.
    Торговые методы отключены, пока allow_trading=False.
    """
    creds: ExmoCredentials = field(default_factory=ExmoCredentials)
    base_url: str = "https://api.exmo.com/v1.1"
    timeout: float = 10.0
    user_agent: str = "clean-crypto-bot/0.1 (+paper; read-only)"
    allow_trading: bool = False  # ← защита от случайной торговли

    _session: requests.Session = field(default_factory=requests.Session, init=False)

    # ---------- HTTP CORE ----------

    def _headers_public(self) -> Dict[str, str]:
        return {"User-Agent": self.user_agent}

    def _headers_private(self, payload: Dict[str, Any]) -> Dict[str, str]:
        if not self.creds.api_key or not self.creds.api_secret:
            raise RuntimeError("EXMO creds are not set")

        body = urlencode(payload)
        sign = hmac.new(
            self.creds.api_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return {
            "User-Agent": self.user_agent,
            "Key": self.creds.api_key,
            "Sign": sign,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path}"
        r = self._session.get(url, params=params, headers=self._headers_public(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post_private(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path}"
        data = dict(payload or {})
        data.setdefault("nonce", _now_ms())
        headers = self._headers_private(data)
        r = self._session.post(url, data=data, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        js = r.json()
        # Некоторые приватные ручки EXMO возвращают {"result": False, "error": "..."}
        if isinstance(js, dict) and js.get("result") is False and js.get("error"):
            raise RuntimeError(f"EXMO API error: {js.get('error')}")
        return js

    # ---------- PUBLIC (market data) ----------

    def ping(self) -> bool:
        """
        Простейшая проверка доступности API.
        Реально у EXMO нет /ping в v1.1, поэтому используем /currency.
        """
        try:
            _ = self._get("currency")
            return True
        except Exception:
            return False

    def ticker(self) -> Dict[str, Any]:
        """Возвращает агрегированный тикер по всем парам."""
        return self._get("ticker")

    def ticker_pair(self, pair: str) -> Dict[str, Any]:
        """
        Тикер по конкретной паре. Пример пары: 'DOGE_EUR'.
        Возвращает словарь по этой паре или пустой, если нет.
        """
        data = self.ticker()
        return data.get(pair, {}) if isinstance(data, dict) else {}

    def order_book(self, pair: str, limit: int = 50) -> Dict[str, Any]:
        """
        Стакан заявок. EXMO v1.1: order_book?pair=BTC_USD
        """
        params = {"pair": pair, "limit": int(limit)}
        return self._get("order_book", params=params)

    def trades(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Последние сделки по паре. EXMO v1.1: trades?pair=BTC_USD
        Ответ формата: {"BTC_USD": [{trade}, ...]}
        """
        params = {"pair": pair}
        data = self._get("trades", params=params)
        arr = data.get(pair) if isinstance(data, dict) else None
        return arr if isinstance(arr, list) else []

    # ---------- PRIVATE (read-only) ----------

    def user_info(self) -> Dict[str, Any]:
        """Сводная инфа по аккаунту (read-only)."""
        return self._post_private("user_info")

    def user_balances(self) -> Dict[str, Decimal]:
        """
        Доступные балансы по валютам.
        Пример user_info: {"balances": {"USD":"10.5","DOGE":"100.0"}, ...}
        """
        ui = self.user_info()
        bals = ui.get("balances") if isinstance(ui, dict) else None
        if not isinstance(bals, dict):
            return {}
        return {k: _d(v) for k, v in bals.items()}

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        """
        Открытые ордера. Если pair=None — по всем.
        """
        if pair:
            return self._post_private("user_open_orders", {"pair": pair})
        return self._post_private("user_open_orders")

    def user_trades(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        История сделок по паре. EXMO: user_trades?pair=...
        Некоторые поля: type (buy/sell), price, quantity, amount, commission_amount, date
        """
        payload = {"pair": pair, "limit": int(limit)}
        data = self._post_private("user_trades", payload)
        arr = data.get(pair) if isinstance(data, dict) else None
        return arr if isinstance(arr, list) else []

    # ---------- GUARDED trading (disabled by default) ----------

    def place_order(self, pair: str, side: str, quantity: Decimal, price: Optional[Decimal] = None, order_type: str = "market") -> Dict[str, Any]:
        """
        Торговля ЗАПРЕЩЕНА по умолчанию. Вызов бросит ошибку, если allow_trading == False.
        Если когда-нибудь захочешь включить — проставь allow_trading=True и реализуй маппинг
        на exmo метод 'order_create'.
        """
        if not self.allow_trading:
            raise RuntimeError("Trading is disabled (allow_trading=False). This client is read-only.")
        raise NotImplementedError("Enable and implement when you are ready to trade for real.")

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self.allow_trading:
            raise RuntimeError("Trading is disabled (allow_trading=False). This client is read-only.")
        raise NotImplementedError("Enable and implement when you are ready to trade for real.")

    # ---------- УТИЛИТЫ-ПАРСЕРЫ (по желанию) ----------

    @staticmethod
    def parse_ticker_price(ticker_entry: Dict[str, Any]) -> Decimal:
        """
        Из ticker_entry достаёт последнюю цену (если есть).
        У EXMO в /ticker обычно ключи: 'last_trade', 'buy_price', 'sell_price', ...
        """
        if not isinstance(ticker_entry, dict):
            return Decimal("0")
        for key in ("last_trade", "buy_price", "sell_price", "last_price"):
            v = ticker_entry.get(key)
            if v is not None:
                val = _d(v)
                if val > 0:
                    return val
        return Decimal("0")

    @staticmethod
    def parse_trades_to_ohlc(
        trades: List[Dict[str, Any]],
        bucket_ms: int,
        max_bars: int,
    ) -> List[Tuple[int, Decimal, Decimal, Decimal, Decimal]]:
        """
        Грубая агрегация сделок в OHLC по размерам «ведра» (bucket_ms).
        Нужна если захочешь свечи из /trades.
        """
        if not trades:
            return []
        # ожидаем у сделки time или date (секунды) и price
        # EXMO обычно даёт "date" (unix seconds) и "price" как строку.
        buckets: Dict[int, List[Decimal]] = {}
        for t in trades:
            ts_s = int(t.get("date", 0))
            if not ts_s:
                continue
            ts_ms = ts_s * 1000
            price = _d(t.get("price"))
            if price <= 0:
                continue
            slot = (ts_ms // bucket_ms) * bucket_ms
            buckets.setdefault(slot, []).append(price)

        ohlc: List[Tuple[int, Decimal, Decimal, Decimal, Decimal]] = []
        for slot in sorted(buckets.keys())[-max_bars:]:
            prices = buckets[slot]
            if not prices:
                continue
            o = prices[0]
            h = max(prices)
            l = min(prices)
            c = prices[-1]
            ohlc.append((slot, o, h, l, c))
        return ohlc
