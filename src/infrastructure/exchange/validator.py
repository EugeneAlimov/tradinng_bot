# src/infrastructure/exchange/validator.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
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
    """Валидатор ответов биржи."""

    @staticmethod
    def to_decimal(value: Any, field_name: str = "value") -> Decimal:
        if value is None:
            raise ValidationError(f"{field_name} is None")
        if isinstance(value, Decimal):
            return value
        try:
            s = str(value).strip()
            if not s or s.lower() == "null":
                raise ValidationError(f"{field_name} is empty or null")
            if s.lower() in ("inf", "infinity", "-inf", "-infinity", "nan"):
                raise ValidationError(f"{field_name} has invalid special value: {s}")
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
                    logger.warning("Invalid currency key: %s", ccy)
                    continue
                ccy_u = ccy.upper().strip()

                if isinstance(amount, dict):
                    free = cls.to_decimal(amount.get("free", 0), f"{ccy_u}.free")
                    used = cls.to_decimal(amount.get("used", 0), f"{ccy_u}.used")
                    total = cls.to_decimal(amount.get("total", free + used), f"{ccy_u}.total")
                else:
                    free = cls.to_decimal(amount, f"{ccy_u}.free")
                    used = Decimal("0")
                    total = free

                if abs(total - (free + used)) > Decimal("0.00000001"):
                    logger.warning("Balance inconsistency %s: total=%s free=%s used=%s", ccy_u, total, free, used)

                out[ccy_u] = ValidatedBalance(currency=ccy_u, free=free, used=used, total=total)
            except ValidationError as e:
                logger.error("Balance validation failed for %s: %s", ccy, e)
        return out

    @classmethod
    def validate_order(cls, order_data: Dict[str, Any]) -> ValidatedOrder:
        if not isinstance(order_data, dict):
            raise ValidationError(f"Order data must be dict, got {type(order_data)}")

        order_id = str(order_data.get("order_id", ""))
        if not order_id:
            raise ValidationError("Order ID missing")

        pair = str(order_data.get("pair", order_data.get("symbol", ""))).upper()
        if "_" not in pair:
            raise ValidationError(f"Invalid pair: {pair}")

        side = str(order_data.get("type", order_data.get("side", ""))).lower()
        if side not in ("buy", "sell"):
            raise ValidationError(f"Invalid side: {side}")

        price = cls.to_decimal(order_data.get("price"), "price")
        quantity = cls.to_decimal(order_data.get("quantity", order_data.get("amount")), "quantity")
        filled = cls.to_decimal(order_data.get("filled", order_data.get("executed_quantity", 0)), "filled")

        status = str(order_data.get("status", "open")).lower()
        ts = int(order_data.get("created", order_data.get("timestamp", 0)))

        if filled > quantity:
            raise ValidationError(f"Filled {filled} > quantity {quantity}")
        if price <= 0:
            raise ValidationError(f"Invalid price: {price}")

        return ValidatedOrder(
            order_id=order_id,
            pair=pair,
            side=side,
            price=price,
            quantity=quantity,
            filled=filled,
            status=status,
            timestamp=ts,
        )

    @classmethod
    def validate_ticker(cls, ticker_data: Dict[str, Any]) -> ValidatedTicker:
        if not isinstance(ticker_data, dict):
            raise ValidationError(f"Ticker data must be dict, got {type(ticker_data)}")

        bid = cls.to_decimal(ticker_data.get("buy_price", ticker_data.get("bid")), "bid")
        ask = cls.to_decimal(ticker_data.get("sell_price", ticker_data.get("ask")), "ask")
        last = cls.to_decimal(ticker_data.get("last_trade", ticker_data.get("last")), "last")
        volume = cls.to_decimal(ticker_data.get("vol", ticker_data.get("volume", 0)), "volume")
        high = cls.to_decimal(ticker_data.get("high", last), "high")
        low = cls.to_decimal(ticker_data.get("low", last), "low")

        if bid >= ask:
            raise ValidationError(f"Invalid spread: bid={bid} >= ask={ask}")
        if high < low:
            raise ValidationError(f"Invalid high/low: high={high} < low={low}")
        if last > high or last < low:
            logger.warning("Last price %s outside [%s,%s]", last, low, high)

        return ValidatedTicker(
            pair=str(ticker_data.get("pair", "")),
            bid=bid,
            ask=ask,
            last=last,
            volume_24h=volume,
            high_24h=high,
            low_24h=low,
        )


class SafeExmoWrapper:
    """Обертка над ExmoPrivate с автоматической валидацией ответов (там, где применимо)."""

    def __init__(self, exmo_api) -> None:
        self.api = exmo_api

    def get_validated_balances(self) -> Dict[str, ValidatedBalance]:
        try:
            raw = self.api.user_info()
            balances = raw.get("balances") or raw.get("balance") or {}
            return ExchangeDataValidator.validate_balance(balances)
        except Exception as e:
            logger.error("Balances fetch/validate failed: %s", e)
            return {}

    def get_validated_ticker(self, pair: str) -> Optional[ValidatedTicker]:
        try:
            data = self.api.ticker_pair(pair)
            if not data:
                return None
            data["pair"] = pair
            return ExchangeDataValidator.validate_ticker(data)
        except Exception as e:
            logger.error("Ticker fetch/validate failed for %s: %s", pair, e)
            return None

    def get_validated_open_orders(self, pair: Optional[str] = None) -> List[ValidatedOrder]:
        try:
            raw = self.api.user_open_orders(pair)
            out: List[ValidatedOrder] = []
            if isinstance(raw, dict):
                for p, orders in raw.items():
                    if not isinstance(orders, list):
                        continue
                    for o in orders:
                        try:
                            o = dict(o or {})
                            o["pair"] = p
                            out.append(ExchangeDataValidator.validate_order(o))
                        except ValidationError as ve:
                            logger.warning("Skip invalid open order: %s", ve)
            return out
        except Exception as e:
            logger.error("Open orders fetch/validate failed: %s", e)
            return []
