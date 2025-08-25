# src/infrastructure/exchange/validator.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)
getcontext().prec = 28


class ValidationError(Exception):
    pass


@dataclass
class ValidatedBalance:
    currency: str
    free: Decimal
    used: Decimal
    total: Decimal


@dataclass
class ValidatedOrder:
    order_id: str
    pair: str
    side: str
    price: Decimal
    quantity: Decimal
    filled: Decimal
    status: str
    timestamp: int


@dataclass
class ValidatedTicker:
    pair: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    high_24h: Decimal
    low_24h: Decimal


class ExchangeDataValidator:
    @staticmethod
    def to_decimal(value: Any, field_name: str = "value") -> Decimal:
        if value is None:
            raise ValidationError(f"{field_name} is None")
        if isinstance(value, Decimal):
            return value
        try:
            s = str(value).strip()
            if not s or s.lower() == "null":
                raise ValidationError(f"{field_name} is empty/null")
            low = s.lower()
            if low in ("inf", "+inf", "-inf", "infinity", "-infinity", "nan"):
                raise ValidationError(f"{field_name} invalid literal: {s}")
            d = Decimal(s)
            if field_name in ("quantity", "volume", "fee") and d < 0:
                raise ValidationError(f"{field_name} negative: {d}")
            return d
        except (InvalidOperation, ValueError) as e:
            raise ValidationError(f"{field_name} parse error: {e}")

    @classmethod
    def validate_balance(cls, balance: Dict[str, Any]) -> Dict[str, ValidatedBalance]:
        if not isinstance(balance, dict):
            raise ValidationError(f"balance must be dict, got {type(balance)}")
        out: Dict[str, ValidatedBalance] = {}
        for cur, data in balance.items():
            try:
                if not isinstance(cur, str) or not cur:
                    logger.warning("invalid currency key: %r", cur)
                    continue
                cur_u = cur.upper().strip()
                if isinstance(data, dict):
                    free = cls.to_decimal(data.get("free", 0), f"{cur_u}.free")
                    used = cls.to_decimal(data.get("used", 0), f"{cur_u}.used")
                    total = cls.to_decimal(data.get("total", free + used), f"{cur_u}.total")
                else:
                    free = cls.to_decimal(data, f"{cur_u}.free")
                    used = Decimal("0")
                    total = free
                if abs(total - (free + used)) > Decimal("0.00000001"):
                    logger.warning("balance inconsistency %s: total=%s vs free+used=%s", cur_u, total, free + used)
                out[cur_u] = ValidatedBalance(cur_u, free, used, total)
            except ValidationError as e:
                logger.error("balance[%s] invalid: %s", cur, e)
        return out

    @classmethod
    def validate_order(cls, od: Dict[str, Any]) -> ValidatedOrder:
        if not isinstance(od, dict):
            raise ValidationError("order must be dict")
        oid = str(od.get("order_id", "")).strip()
        if not oid:
            raise ValidationError("order_id missing")
        pair = str(od.get("pair", od.get("symbol", ""))).upper()
        if "_" not in pair:
            raise ValidationError(f"pair invalid: {pair}")
        side = str(od.get("type", od.get("side", ""))).lower()
        if side not in ("buy", "sell"):
            raise ValidationError(f"side invalid: {side}")
        price = cls.to_decimal(od.get("price"), "price")
        qty = cls.to_decimal(od.get("quantity", od.get("amount")), "quantity")
        filled = cls.to_decimal(od.get("filled", od.get("executed_quantity", 0)), "filled")
        status = str(od.get("status", "open")).lower()
        ts = int(od.get("created", od.get("timestamp", 0)))
        if filled > qty:
            raise ValidationError(f"filled {filled} > qty {qty}")
        if price <= 0:
            raise ValidationError(f"price <= 0: {price}")
        return ValidatedOrder(oid, pair, side, price, qty, filled, status, ts)

    @classmethod
    def validate_ticker(cls, tk: Dict[str, Any]) -> ValidatedTicker:
        if not isinstance(tk, dict):
            raise ValidationError("ticker must be dict")
        bid = cls.to_decimal(tk.get("buy_price", tk.get("bid")), "bid")
        ask = cls.to_decimal(tk.get("sell_price", tk.get("ask")), "ask")
        last = cls.to_decimal(tk.get("last_trade", tk.get("last")), "last")
        vol = cls.to_decimal(tk.get("vol", tk.get("volume", 0)), "volume")
        high = cls.to_decimal(tk.get("high", last), "high")
        low = cls.to_decimal(tk.get("low", last), "low")
        eps = Decimal("0.00000001")
        if bid > ask + eps:
            raise ValidationError(f"spread invalid: bid {bid} > ask {ask}")
        if high < low:
            raise ValidationError(f"high < low: {high} < {low}")
        if last > high or last < low:
            logger.warning("last %s outside [%s, %s]", last, low, high)
        return ValidatedTicker(pair=str(tk.get("pair", "")), bid=bid, ask=ask, last=last,
                               volume_24h=vol, high_24h=high, low_24h=low)

    @classmethod
    def validate_candles(cls, candles: List[Dict[str, Any]]) -> List[Dict[str, Decimal]]:
        if not isinstance(candles, list):
            raise ValidationError("candles must be list")
        out: List[Dict[str, Decimal]] = []
        for i, c in enumerate(candles):
            try:
                if not isinstance(c, dict):
                    raise ValidationError("candle not dict")
                ts = int(c.get("t", c.get("timestamp", 0)))
                o = cls.to_decimal(c.get("o", c.get("open")), f"candle[{i}].open")
                h = cls.to_decimal(c.get("h", c.get("high")), f"candle[{i}].high")
                l = cls.to_decimal(c.get("l", c.get("low")), f"candle[{i}].low")
                cl = cls.to_decimal(c.get("c", c.get("close")), f"candle[{i}].close")
                v = cls.to_decimal(c.get("v", c.get("volume", 0)), f"candle[{i}].volume")
                if h < l:
                    raise ValidationError("high < low")
                if not (l <= o <= h):
                    raise ValidationError("open outside range")
                if not (l <= cl <= h):
                    raise ValidationError("close outside range")
                out.append({"timestamp": Decimal(ts), "open": o, "high": h, "low": l, "close": cl, "volume": v})
            except ValidationError as e:
                logger.error("candle %d invalid: %s", i, e)
        return out


class SafeExmoWrapper:
    """
    Обёртка над EXMO API с валидацией данных. Методы возвращают уже проверенные
    структуры либо пустые/None при ошибке (с логированием).
    """

    def __init__(self, exmo_api):
        self.api = exmo_api
        self.v = ExchangeDataValidator

    def get_validated_balances(self) -> Dict[str, ValidatedBalance]:
        try:
            raw = self.api.user_info()
            bal = raw.get("balances", raw.get("balance", {}))
            return self.v.validate_balance(bal)
        except Exception as e:
            logger.error("balances fetch failed: %s", e)
            return {}

    def get_validated_ticker(self, pair: str) -> Optional[ValidatedTicker]:
        try:
            data = self.api.ticker_pair(pair) or {}
            data["pair"] = pair
            return self.v.validate_ticker(data)
        except Exception as e:
            logger.error("ticker %s failed: %s", pair, e)
            return None

    def get_validated_open_orders(self, pair: Optional[str] = None) -> List[ValidatedOrder]:
        try:
            raw = self.api.user_open_orders(pair)
            out: List[ValidatedOrder] = []
            if isinstance(raw, dict):
                for p, lst in raw.items():
                    for od in lst or []:
                        try:
                            od["pair"] = p
                            out.append(self.v.validate_order(od))
                        except ValidationError as ve:
                            logger.warning("skip invalid order: %s", ve)
            return out
        except Exception as e:
            logger.error("open orders failed: %s", e)
            return []
