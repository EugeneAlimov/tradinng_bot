# src/application/order_manager.py
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
    """Информация об ордере, которую отслеживаем локально."""
    order_id: str
    client_id: int
    pair: str
    side: str  # "buy" / "sell"
    price: float
    quantity: float
    status: str = "pending"  # pending | open | filled | cancelled | timeout_cancelled | unknown
    created_at: datetime = field(default_factory=datetime.now)
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0


class OrderIDGenerator:
    """
    Генератор устойчивых client_id для EXMO.
    Обеспечивает уникальность в рамках int32 при высокой частоте вызовов.
    """
    __slots__ = ("counter", "last_ms", "lock")

    def __init__(self) -> None:
        self.counter: int = 0
        self.last_ms: int = 0
        self.lock = threading.Lock()

    def generate(self) -> int:
        with self.lock:
            now_ms = int(time.time() * 1000)
            if now_ms == self.last_ms:
                self.counter = (self.counter + 1) % 1000  # 0..999
            else:
                self.counter = 0
                self.last_ms = now_ms
            base = (now_ms % 10_000_000) * 1000 + self.counter
            # int32 safe
            return base % 2_147_483_647


class ImprovedOrderManager:
    """
    Улучшенный менеджер ордеров.
    Требует exchange api с методами:
      - order_create(pair, quantity, price, side, client_id=...)
      - user_open_orders(pair: Optional[str]=None) -> Dict[str, List[Dict]]
      - order_trades(order_id) -> Dict
      - order_cancel(order_id) -> Any
    """

    def __init__(self, exchange_api: Any):
        self.exchange = exchange_api
        self.idgen = OrderIDGenerator()
        self.active_orders: Dict[str, OrderInfo] = {}
        self.order_history: List[OrderInfo] = []
        self.lock = threading.Lock()

    @staticmethod
    def _fmt_num(x: float) -> str:
        s = f"{x:.10f}".rstrip("0").rstrip(".")
        return s if s else "0"

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
                client_id = self.idgen.generate()
                price_str = self._fmt_num(price)
                qty_str = self._fmt_num(quantity)

                logger.info(
                    "Placing order attempt %s/%s: %s %s @ %s (client_id=%s)",
                    attempt + 1, max_retries, side, qty_str, price_str, client_id,
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
                    logger.info("Order placed: %s", order_id)
                    return True, order_id, None

            except Exception as e:  # noqa: BLE001
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
                    time.sleep(min(2 ** attempt, 5))

        return False, None, last_error

    def check_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            open_orders = self.exchange.user_open_orders()
            if isinstance(open_orders, dict):
                for orders in open_orders.values():
                    if not isinstance(orders, list):
                        continue
                    for o in orders:
                        if str(o.get("order_id")) == order_id:
                            # EXMO хранит quantity как остаток к исполнению
                            remaining = float(o.get("quantity", 0) or 0)
                            return {"status": "open", "filled": 0.0, "remaining": remaining}

            # если не нашли — пробуем получить трейды ордера
            try:
                tr = self.exchange.order_trades(order_id)
                trades = (tr or {}).get("trades") or []
                if trades:
                    total_qty = sum(float(t.get("quantity", 0) or 0) for t in trades)
                    vw_price = (
                        sum(float(t.get("quantity", 0) or 0) * float(t.get("price", 0) or 0) for t in trades)
                        / total_qty if total_qty > 0 else 0.0
                    )
                    return {"status": "filled", "filled": total_qty, "avg_price": vw_price}
            except Exception:
                pass

            return {"status": "cancelled", "filled": 0.0}
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to check order %s: %s", order_id, e)
            return {"status": "unknown", "error": str(e)}

    def cancel_order_safe(self, order_id: str) -> bool:
        try:
            st = self.check_order_status(order_id)
            if st.get("status") == "open":
                self.exchange.order_cancel(order_id)
                with self.lock:
                    if order_id in self.active_orders:
                        self.active_orders[order_id].status = "cancelled"
                        self.order_history.append(self.active_orders[order_id])
                        del self.active_orders[order_id]
                logger.info("Order %s cancelled", order_id)
                return True
            logger.info("Order %s is not cancellable (status=%s)", order_id, st.get("status"))
            return False
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to cancel %s: %s", order_id, e)
            return False

    def wait_for_fill(self, order_id: str, timeout: float = 5.0) -> Dict[str, Any]:
        start = time.time()
        last = {"status": "unknown"}
        while time.time() - start < timeout:
            st = self.check_order_status(order_id)
            last = st
            if st["status"] in ("filled", "cancelled"):
                with self.lock:
                    if order_id in self.active_orders:
                        info = self.active_orders[order_id]
                        info.status = st["status"]
                        if st["status"] == "filled":
                            info.filled_qty = float(st.get("filled", 0.0) or 0.0)
                            info.avg_fill_price = float(st.get("avg_price", 0.0) or 0.0)
                        self.order_history.append(info)
                        del self.active_orders[order_id]
                return st
            time.sleep(0.5)

        if last.get("status") == "open":
            self.cancel_order_safe(order_id)
            last["status"] = "timeout_cancelled"
        return last

    def cleanup_old_orders(self, max_age_minutes: int = 5) -> None:
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        with self.lock:
            old = [oid for oid, info in self.active_orders.items() if info.created_at < cutoff]
        for oid in old:
            logger.info("Auto-cancel old order: %s", oid)
            self.cancel_order_safe(oid)

    def get_active_orders_summary(self) -> Dict[str, Any]:
        with self.lock:
            items = list(self.active_orders.values())
        return {
            "count": len(items),
            "orders": [
                {
                    "order_id": i.order_id,
                    "pair": i.pair,
                    "side": i.side,
                    "price": i.price,
                    "quantity": i.quantity,
                    "age_seconds": (datetime.now() - i.created_at).total_seconds(),
                }
                for i in items
            ],
        }
