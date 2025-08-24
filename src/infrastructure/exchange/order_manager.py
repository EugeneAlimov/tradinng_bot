# src/infrastructure/exchange/order_manager.py
from __future__ import annotations

import time
import threading
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
    """Информация об ордере в локальном трекинге."""
    order_id: str
    client_id: int
    pair: str
    side: str
    price: float
    quantity: float
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0


class OrderIDGenerator:
    """
    Генератор уникальных client_id (int32) для EXMO.
    Устойчив к множественным вызовам в один и тот же миллисекундный тик.
    """
    def __init__(self) -> None:
        self.counter = 0
        self.last_timestamp = 0
        self.lock = threading.Lock()

    def generate(self) -> int:
        with self.lock:
            current_ms = int(time.time() * 1000)
            if current_ms == self.last_timestamp:
                self.counter = (self.counter + 1) % 1000  # 0..999
            else:
                self.counter = 0
                self.last_timestamp = current_ms

            base = (current_ms % 10_000_000) * 1000 + self.counter  # 7 цифр времени + 3 цифры счетчика
            client_id = base % 2_147_483_647  # int32 max
            return int(client_id)


class ImprovedOrderManager:
    """
    Менеджер ордеров с генерацией уникального client_id и retry-логикой.
    Требует exchange_api с методами:
      - order_create(pair, quantity, price, side, client_id)
      - user_open_orders()
      - order_trades(order_id)
      - order_cancel(order_id)
    """

    def __init__(self, exchange_api) -> None:
        self.exchange = exchange_api
        self.id_generator = OrderIDGenerator()
        self.active_orders: Dict[str, OrderInfo] = {}
        self.order_history: List[OrderInfo] = []
        self.lock = threading.Lock()

    def place_order_with_retry(
        self,
        pair: str,
        side: str,
        price: float,
        quantity: float,
        max_retries: int = 3,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        last_error: Optional[str] = None

        for attempt in range(max_retries):
            try:
                client_id = self.id_generator.generate()
                price_str = f"{price:.10f}".rstrip("0").rstrip(".")
                qty_str = f"{quantity:.10f}".rstrip("0").rstrip(".")

                logger.info(
                    "Placing order attempt %s/%s: %s %s @ %s, client_id=%s",
                    attempt + 1, max_retries, side, qty_str, price_str, client_id
                )

                resp = self.exchange.order_create(
                    pair=pair,
                    quantity=qty_str,
                    price=price_str,
                    side=side,
                    client_id=client_id,
                )

                order_id = str(resp.get("order_id") or resp.get("order_id_str") or "")
                if order_id:
                    info = OrderInfo(
                        order_id=order_id,
                        client_id=client_id,
                        pair=pair,
                        side=side,
                        price=price,
                        quantity=quantity,
                        status="open",
                    )
                    with self.lock:
                        self.active_orders[order_id] = info
                    logger.info("Order placed successfully: %s", order_id)
                    return True, order_id, None

            except Exception as e:
                last_error = str(e)
                logger.warning("Order attempt %s failed: %s", attempt + 1, last_error)

                low = last_error.lower()
                if "nonce" in low:
                    time.sleep(1.0 * (attempt + 1))
                elif "client_id" in low:
                    time.sleep(0.5)
                elif "insufficient" in low:
                    break
                else:
                    time.sleep(2 ** attempt)

        return False, None, last_error

    def check_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            open_orders = self.exchange.user_open_orders()
            if isinstance(open_orders, dict):
                for pair_orders in open_orders.values():
                    if isinstance(pair_orders, list):
                        for order in pair_orders:
                            if str(order.get("order_id")) == order_id:
                                return {"status": "open", "filled": 0, "remaining": float(order.get("quantity", 0))}

            try:
                trades = self.exchange.order_trades(order_id)
                if trades and trades.get("trades"):
                    total_filled = sum(float(t.get("quantity", 0)) for t in trades["trades"])
                    avg_price = (
                        sum(float(t.get("quantity", 0)) * float(t.get("price", 0)) for t in trades["trades"])
                        / total_filled
                        if total_filled > 0
                        else 0.0
                    )
                    return {"status": "filled", "filled": total_filled, "avg_price": avg_price}
            except Exception:
                pass

            return {"status": "cancelled", "filled": 0}

        except Exception as e:
            logger.error("Failed to check order status %s: %s", order_id, e)
            return {"status": "unknown", "error": str(e)}

    def cancel_order_safe(self, order_id: str) -> bool:
        try:
            status = self.check_order_status(order_id)
            if status.get("status") == "open":
                self.exchange.order_cancel(order_id)
                with self.lock:
                    if order_id in self.active_orders:
                        self.active_orders[order_id].status = "cancelled"
                        self.order_history.append(self.active_orders[order_id])
                        del self.active_orders[order_id]
                logger.info("Order %s cancelled", order_id)
                return True
            logger.info("Order %s not cancellable: %s", order_id, status.get("status"))
            return False
        except Exception as e:
            logger.error("Failed to cancel %s: %s", order_id, e)
            return False

    def wait_for_fill(self, order_id: str, timeout: float = 5.0) -> Dict[str, Any]:
        start = time.time()
        last_status: Dict[str, Any] = {"status": "unknown"}

        while time.time() - start < timeout:
            status = self.check_order_status(order_id)
            last_status = status

            if status["status"] in ("filled", "cancelled"):
                with self.lock:
                    if order_id in self.active_orders:
                        info = self.active_orders[order_id]
                        info.status = status["status"]
                        if status["status"] == "filled":
                            info.filled_qty = status.get("filled", 0.0) or 0.0
                            info.avg_fill_price = status.get("avg_price", 0.0) or 0.0
                        self.order_history.append(info)
                        del self.active_orders[order_id]
                return status

            time.sleep(0.5)

        if last_status.get("status") == "open":
            self.cancel_order_safe(order_id)
            last_status["status"] = "timeout_cancelled"
        return last_status

    def cleanup_old_orders(self, max_age_minutes: int = 5) -> None:
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        with self.lock:
            old = [oid for oid, info in self.active_orders.items() if info.created_at < cutoff]
        for oid in old:
            logger.info("Auto-cancelling old order: %s", oid)
            self.cancel_order_safe(oid)

    def get_active_orders_summary(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "count": len(self.active_orders),
                "orders": [
                    {
                        "order_id": info.order_id,
                        "pair": info.pair,
                        "side": info.side,
                        "price": info.price,
                        "quantity": info.quantity,
                        "age_seconds": (datetime.now() - info.created_at).total_seconds(),
                    }
                    for info in self.active_orders.values()
                ],
            }
