# src/infrastructure/exchange/order_manager.py
from __future__ import annotations

import threading
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
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
    Потокобезопасный монотонный генератор client_id в пределах int32,
    без коллизий в рамках одного процесса (и точно для 50k+ вызовов).
    """
    _INT32_MAX = 2_147_483_647

    def __init__(self, seed: Optional[int] = None) -> None:
        self._lock = threading.Lock()
        # стартуем с «окна», зависящего от времени, чтобы не уткнуться в край INT32
        base = int(time.time() * 1000) % (self._INT32_MAX - 1_000_000)
        if seed is not None:
            base = int(seed) % (self._INT32_MAX - 1_000_000)
        self._counter = max(1, base)

    def generate(self) -> int:
        with self._lock:
            self._counter += 1
            if self._counter >= self._INT32_MAX:
                # избегаем нулевого/повторного значения
                self._counter = 1
            return self._counter


class ImprovedOrderManager:
    """
    Улучшенный менеджер ордеров с retry-логикой и внутренним реестром active_orders.
    Совместим с тестами: поле `active_orders` доступно и заполняется при размещении.
    """

    def __init__(self, exchange_api):
        self.exchange = exchange_api
        self.id_generator = OrderIDGenerator()
        self.active_orders: Dict[str, OrderInfo] = {}
        self.order_history: List[OrderInfo] = []
        self._lock = threading.Lock()

    def place_order_with_retry(
            self,
            pair: str,
            side: str,
            price: float,
            quantity: float,
            max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Размещает ордер с retry. Возвращает (success, order_id, error_message).
        При успехе кладёт запись в self.active_orders.
        """
        last_error = None

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
                    client_id=client_id
                )
                order_id = str(resp.get("order_id") or resp.get("order_id_str") or "")
                if order_id:
                    info = OrderInfo(
                        order_id=order_id,
                        client_id=client_id,
                        pair=pair,
                        side=side,
                        price=float(price),
                        quantity=float(quantity),
                        status="open",
                    )
                    with self._lock:
                        self.active_orders[order_id] = info
                    return True, order_id, None

            except Exception as e:
                last_error = str(e)
                logger.warning("Order attempt %s failed: %s", attempt + 1, last_error)
                # простая стратегия ожидания
                time.sleep(min(2 ** attempt, 1.0))

        return False, None, last_error

    def check_order_status(self, order_id: str) -> Dict[str, Any]:
        """Простая проверка статуса: ищем в открытых, иначе считаем отменён/исполнен."""
        try:
            open_orders = self.exchange.user_open_orders()
            for _pair, orders in (open_orders or {}).items():
                for o in orders or []:
                    if str(o.get("order_id")) == order_id:
                        return {"status": "open", "filled": 0.0, "remaining": float(o.get("quantity", 0.0))}
            # если не нашли в открытых — пробуем получить трейды
            try:
                trades = self.exchange.order_trades(order_id)
                if trades and trades.get("trades"):
                    total_filled = sum(float(t.get("quantity", 0)) for t in trades["trades"])
                    avg_price = (
                        sum(float(t.get("quantity", 0)) * float(t.get("price", 0)) for t in trades["trades"])
                        / total_filled if total_filled > 0 else 0.0
                    )
                    return {"status": "filled", "filled": total_filled, "avg_price": avg_price}
            except Exception:
                pass
            return {"status": "cancelled", "filled": 0.0}
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    def cancel_order_safe(self, order_id: str) -> bool:
        """Отмена с синхронизацией локального состояния."""
        try:
            st = self.check_order_status(order_id)
            if st.get("status") == "open":
                self.exchange.order_cancel(order_id)
                with self._lock:
                    if order_id in self.active_orders:
                        self.active_orders[order_id].status = "cancelled"
                        self.order_history.append(self.active_orders[order_id])
                        del self.active_orders[order_id]
                return True
            return False
        except Exception as e:
            logger.error("Failed to cancel %s: %s", order_id, e)
            return False

    def wait_for_fill(self, order_id: str, timeout: float = 5.0) -> Dict[str, Any]:
        start = time.time()
        last = {"status": "unknown"}
        while time.time() - start < timeout:
            st = self.check_order_status(order_id)
            last = st
            if st["status"] in ("filled", "cancelled"):
                with self._lock:
                    if order_id in self.active_orders:
                        oi = self.active_orders[order_id]
                        oi.status = st["status"]
                        if st["status"] == "filled":
                            oi.filled_qty = float(st.get("filled", 0.0))
                            oi.avg_fill_price = float(st.get("avg_price", 0.0))
                        self.order_history.append(oi)
                        del self.active_orders[order_id]
                return st
            time.sleep(0.25)
        # timeout — пробуем отменить
        if last.get("status") == "open":
            self.cancel_order_safe(order_id)
            last["status"] = "timeout_cancelled"
        return last

    def cleanup_old_orders(self, max_age_minutes: int = 5) -> None:
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        with self._lock:
            old = [oid for oid, info in self.active_orders.items() if info.created_at < cutoff]
        for oid in old:
            self.cancel_order_safe(oid)

    def get_active_orders_summary(self) -> Dict[str, Any]:
        with self._lock:
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
                        "client_id": info.client_id,
                    }
                    for info in self.active_orders.values()
                ],
            }
