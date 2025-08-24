# src/infrastructure/exchange/order_manager.py
from __future__ import annotations

import os
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta

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
    Быстрый генератор уникальных client_id в пределах int32.
    Формула: (ms % 10_000_000)*1024 + pid_low10 + counter_low6 + urandom_low10  -> mod 2^31-1
    """
    def __init__(self):
        self._last_ms: int = 0
        self._counter: int = 0
        self._lock = threading.Lock()
        self._pid_low = os.getpid() & 0x3FF  # 10 бит

    def generate(self) -> int:
        with self._lock:
            ms = int(time.time() * 1000)
            if ms == self._last_ms:
                self._counter = (self._counter + 1) & 0x3F  # 6 бит
            else:
                self._counter = 0
                self._last_ms = ms
            urand = int.from_bytes(os.urandom(2), "little") & 0x3FF  # 10 бит
            base = ((ms % 10_000_000) << 10) | self._pid_low
            base = (base << 6) | self._counter
            base = (base << 10) | urand
            return base % 2_147_483_647


class ImprovedOrderManager:
    """
    Высокоуровневый менеджер ордеров: генерация client_id, размещение с retry,
    отслеживание и безопасная отмена.
    """
    def __init__(self, exchange_api):
        self.exchange = exchange_api
        self.id_gen = OrderIDGenerator()
        self.active: Dict[str, OrderInfo] = {}
        self.history: List[OrderInfo] = []
        self._lock = threading.Lock()

    def place_order_with_retry(
        self, pair: str, side: str, price: float, quantity: float, max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        last_error: Optional[str] = None
        for attempt in range(max_retries):
            try:
                client_id = self.id_gen.generate()
                price_str = f"{price:.10f}".rstrip("0").rstrip(".")
                qty_str = f"{quantity:.10f}".rstrip("0").rstrip(".")
                logger.info(
                    "place attempt %d/%d: %s %s @ %s (client_id=%s)",
                    attempt + 1, max_retries, side, qty_str, price_str, client_id
                )
                resp = self.exchange.order_create(
                    pair=pair, quantity=qty_str, price=price_str, side=side, client_id=client_id
                )
                order_id = str(resp.get("order_id") or resp.get("order_id_str") or "").strip()
                if order_id:
                    info = OrderInfo(
                        order_id=order_id, client_id=client_id,
                        pair=pair, side=side, price=float(price), quantity=float(quantity),
                        status="open"
                    )
                    with self._lock:
                        self.active[order_id] = info
                    return True, order_id, None
                last_error = "empty_order_id"
            except Exception as e:
                last_error = str(e)
                logger.warning("order attempt %d failed: %s", attempt + 1, last_error)
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
            open_map = self.exchange.user_open_orders()
            for pair, orders in (open_map or {}).items():
                for ord_ in orders or []:
                    if str(ord_.get("order_id")) == order_id:
                        return {"status": "open", "filled": 0.0, "remaining": float(ord_.get("quantity", 0.0))}
            # try fills
            try:
                tr = self.exchange.order_trades(order_id)
                trades = tr.get("trades") if isinstance(tr, dict) else None
                if trades:
                    total_q = sum(float(t.get("quantity", 0.0)) for t in trades)
                    if total_q > 0:
                        avg = sum(float(t.get("quantity", 0.0)) * float(t.get("price", 0.0)) for t in trades) / total_q
                    else:
                        avg = 0.0
                    return {"status": "filled", "filled": total_q, "avg_price": avg}
            except Exception:
                pass
            return {"status": "cancelled", "filled": 0.0}
        except Exception as e:
            logger.error("status check failed: %s", e)
            return {"status": "unknown", "error": str(e)}

    def cancel_order_safe(self, order_id: str) -> bool:
        try:
            st = self.check_order_status(order_id)
            if st.get("status") == "open":
                self.exchange.order_cancel(order_id)
                with self._lock:
                    if order_id in self.active:
                        self.active[order_id].status = "cancelled"
                        self.history.append(self.active[order_id])
                        del self.active[order_id]
                return True
            return False
        except Exception as e:
            logger.error("cancel %s failed: %s", order_id, e)
            return False

    def wait_for_fill(self, order_id: str, timeout: float = 5.0) -> Dict[str, Any]:
        start = time.time()
        last = {"status": "unknown"}
        while time.time() - start < timeout:
            st = self.check_order_status(order_id)
            last = st
            if st["status"] in ("filled", "cancelled"):
                with self._lock:
                    if order_id in self.active:
                        info = self.active[order_id]
                        info.status = st["status"]
                        if st["status"] == "filled":
                            info.filled_qty = float(st.get("filled", 0.0))
                            info.avg_fill_price = float(st.get("avg_price", 0.0))
                        self.history.append(info)
                        del self.active[order_id]
                return st
            time.sleep(0.5)
        if last.get("status") == "open":
            self.cancel_order_safe(order_id)
            last["status"] = "timeout_cancelled"
        return last

    def cleanup_old_orders(self, max_age_minutes: int = 5) -> None:
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        with self._lock:
            old = [oid for oid, info in self.active.items() if info.created_at < cutoff]
        for oid in old:
            self.cancel_order_safe(oid)

    def get_active_orders_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "count": len(self.active),
                "orders": [
                    {
                        "order_id": i.order_id,
                        "pair": i.pair,
                        "side": i.side,
                        "price": i.price,
                        "quantity": i.quantity,
                        "age_seconds": (datetime.now() - i.created_at).total_seconds(),
                    } for i in self.active.values()
                ]
            }
