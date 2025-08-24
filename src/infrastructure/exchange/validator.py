# -*- coding: utf-8 -*-
"""
Validation for balances, tickers, orders, candles.
All numeric data is converted to Decimal; invalid records are skipped with logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


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
            if s.lower() in ("inf", "-inf", "infinity", "-infinity", "nan"):
                raise ValidationError(f"{field_name} invalid: {s}")
            d = Decimal(s)
            if field_name in ("quantity", "volume", "fee") and d < 0:
                raise ValidationError(f"{field_name} cannot be negative: {d}")
            return d
        except (InvalidOperation, ValueError) as e:
            raise ValidationError(f"Cannot convert {field_name}='{value}' to Decimal: {e}")

    @classmethod
    def validate_balance(cls, balance_data: Dict[str, Any]) -> Dict[str, ValidatedBalance]:
        if not isinstance(balance_data, dict):
            raise ValidationError(f"Balance data must be dict, got {type(balance_data)}")

        out: Dict[str, ValidatedBalance] = {}
        for ccy, amount in balance_data.items():
            try:
                if not isinstance(ccy, str) or not ccy:
                    logger.warning("Invalid currency key: %r", ccy)
                    continue
                ccy = ccy.upper().strip()
                if isinstance(amount, dict):
                    free = cls.to_decimal(amount.get("free", 0), f"{ccy}.free")
                    used = cls.to_decimal(amount.get("used", 0), f"{ccy}.used")
                    total = cls.to_decimal(amount.get("total", free + used), f"{ccy}.total")
                else:
                    free = cls.to_decimal(amount, f"{ccy}.free")
                    used = Decimal("0")
                    total = free
                if abs(total - (free + used)) > Decimal("0.00000001"):
                    logger.warning("Balance inconsistency %s: total=%s free=%s used=%s", ccy, total, free, used)
                out[ccy] = ValidatedBalance(currency=ccy, free=free, used=used, total=total)
            except ValidationError as e:
                logger.error("Balance validation failed for %s: %s", ccy, e)
                continue
        return out

    @classmethod
    def validate_order(cls, order_data: Dict[str, Any]) -> ValidatedOrder:
        if not isinstance(order_data, dict):
            raise ValidationError(f"Order data must be dict, got {type(order_data)}")
        oid = str(order_data.get("order_id", "") or "")
        if not oid:
            raise ValidationError("Order ID missing")
        pair = str(order_data.get("pair", order_data.get("symbol", ""))).upper()
        if "_" not in pair:
            raise ValidationError(f"Invalid pair: {pair}")
        side = str(order_data.get("type", order_data.get("side", ""))).lower()
        if side not in ("buy", "sell"):
            raise ValidationError(f"Invalid side: {side}")
        price = cls.to_decimal(order_data.get("price"), "price")
        qty = cls.to_decimal(order_data.get("quantity", order_data.get("amount")), "quantity")
        filled = cls.to_decimal(order_data.get("filled", order_data.get("executed_quantity", 0)), "filled")
        status = str(order_data.get("status", "open")).lower()
        ts = int(order_data.get("created", order_data.get("timestamp", 0)) or 0)
        if filled > qty:
            raise ValidationError(f"Filled {filled} > qty {qty}")
        if price <= 0:
            raise ValidationError(f"Invalid price: {price}")
        return ValidatedOrder(
            order_id=oid, pair=pair, side=side, price=price,
            quantity=qty, filled=filled, status=status, timestamp=ts
        )

    @classmethod
    def validate_ticker(cls, ticker: Dict[str, Any]) -> ValidatedTicker:
        if not isinstance(ticker, dict):
            raise ValidationError(f"Ticker data must be dict, got {type(ticker)}")
        bid = cls.to_decimal(ticker.get("buy_price", ticker.get("bid")), "bid")
        ask = cls.to_decimal(ticker.get("sell_price", ticker.get("ask")), "ask")
        last = cls.to_decimal(ticker.get("last_trade", ticker.get("last")), "last")
        vol = cls.to_decimal(ticker.get("vol", ticker.get("volume", 0)), "volume")
        high = cls.to_decimal(ticker.get("high", last), "high")
        low = cls.to_decimal(ticker.get("low", last), "low")
        if bid >= ask:
            raise ValidationError(f"Invalid spread: bid={bid} >= ask={ask}")
        if high < low:
            raise ValidationError(f"Invalid high/low: {high} < {low}")
        return ValidatedTicker(
            pair=str(ticker.get("pair", "")),
            bid=bid, ask=ask, last=last, volume_24h=vol, high_24h=high, low_24h=low
        )

    @classmethod
    def validate_candles(cls, candles: List[Dict[str, Any]]) -> List[Dict[str, Decimal]]:
        if not isinstance(candles, list):
            raise ValidationError(f"Candles data must be list, got {type(candles)}")
        out: List[Dict[str, Decimal]] = []
        for i, c in enumerate(candles):
            try:
                if not isinstance(c, dict):
                    raise ValidationError(f"Candle[{i}] must be dict")
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
                out.append({
                    "timestamp": int(c.get("t", c.get("timestamp", 0)) or 0),
                    "open": o, "high": h, "low": l, "close": cl, "volume": v
                })
            except ValidationError as e:
                logger.error("Candle[%s] invalid: %s", i, e)
                continue
        return out


class SafeExmoWrapper:
    """Adapter over EXMO private/public API client that validates data."""
    def __init__(self, exmo_api: Any):
        self.api = exmo_api
        self.validator = ExchangeDataValidator()

    def get_validated_balances(self) -> Dict[str, ValidatedBalance]:
        try:
            raw = self.api.user_info()
            balances = raw.get("balances") or raw.get("balance") or {}
            return self.validator.validate_balance(balances)
        except Exception as e:
            logger.error("get_validated_balances failed: %s", e)
            return {}

    def get_validated_ticker(self, pair: str) -> Optional[ValidatedTicker]:
        try:
            t = self.api.ticker_pair(pair)
            if not t:
                return None
            t["pair"] = pair
            return self.validator.validate_ticker(t)
        except Exception as e:
            logger.error("get_validated_ticker(%s) failed: %s", pair, e)
            return None

    def get_validated_open_orders(self, pair: Optional[str] = None) -> List[ValidatedOrder]:
        try:
            raw = self.api.user_open_orders(pair)
            out: List[ValidatedOrder] = []
            if isinstance(raw, dict):
                for p, arr in raw.items():
                    if isinstance(arr, list):
                        for o in arr:
                            try:
                                o["pair"] = p
                                out.append(self.validator.validate_order(o))
                            except ValidationError as e:
                                logger.warning("Skip invalid open order: %s", e)
            return out
        except Exception as e:
            logger.error("get_validated_open_orders failed: %s", e)
            return []
