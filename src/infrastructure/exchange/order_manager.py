# -*- coding: utf-8 -*-
"""
OrderID generation + high-level order manager with simple retry orchestration.
Designed for EXMO's client_id uniqueness requirement.
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import logging

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
    Unique client_id generator (int32 safe).
    Combines ms timestamp + per-ms counter.
    """
    def __init__(self) -> None:
        self._counter = 0
        self._last_ms = 0
        self._lock = threading.Lock()

    def generate(self) -> int:
        with self._lock:
            now_ms = int(time.time() * 1000)
            if now_ms == self._last_ms:
                self._counter = (self._counter + 1) % 1000
            else:
                self._counter = 0
                self._last_ms = now_ms
            base = (now_ms % 10_000_000) * 1000 + self._counter
            return base % 2_147_483_647  # int32 range


class ImprovedOrderManager:
    """
    High level order management with:
      - unique client_id
      - basic retry policy
      - local state of active orders
    Expects exchange object with methods:
      order_create(pair, quantity, price, side, client_id)
      user_open_orders()
      order_trades(order_id)
      order_cancel(order_id)
    """
    def __init__(self, exchange_api: Any) -> None:
        self.exchange = exchange_api
        self.id_gen = OrderIDGenerator()
        self.active: Dict[str, OrderInfo] = {}
        self.history: List[OrderInfo] = []
        self._lock = threading.Lock()

    @staticmethod
    def _fmt_num(x: float) -> str:
        s = f"{x:.10f}".rstrip("0").rstrip(".")
        return s or "0"

    def place_order_with_retry(
        self,
        *,
        pair: str,
        side: str,
        price: float,
        quantity: float,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        last_error: Optional[str] = None

        for attempt in range(max_retries):
            try:
                cid = self.id_gen.generate()
                price_str = self._fmt_num(price)
                qty_str = self._fmt_num(quantity)
                logger.info(
                    "placing order %s/%s: %s %s @ %s (client_id=%s)",
                    attempt + 1, max_retries, side, qty_str, price_str, cid
                )
                resp = self.exchange.order_create(
                    pair=pair, quantity=qty_str, price=price_str, side=side, client_id=cid
                )
                order_id = str(resp.get("order_id") or resp.get("order_id_str") or "")
                if order_id:
                    info = OrderInfo(
                        order_id=order_id, client_id=cid, pair=pair,
                        side=side, price=price, quantity=quantity, status="open"
                    )
                    with self._lock:
                        self.active[order_id] = info
                    logger.info("order placed: %s", order_id)
                    return True, order_id, None
                last_error = "empty order_id in response"
                logger.warning("order_create returned no id, response=%s", resp)
            except Exception as e:
                last_error = str(e).strip()
                logger.warning("order attempt %s failed: %s", attempt + 1, last_error)
                low = last_error.lower()
                if "nonce" in low:
                    time.sleep(1.0 * (attempt + 1))
                elif "client_id" in low:
                    time.sleep(0.4)
                elif "insufficient" in low:
                    break
                else:
                    time.sleep(2 ** attempt)

        return False, None, last_error

    # ---- status/cancel helpers ----

    def _snapshot_open(self) -> List[Dict[str, Any]]:
        try:
            raw = self.exchange.user_open_orders()
            out: List[Dict[str, Any]] = []
            if isinstance(raw, dict):
                for _, arr in raw.items():
                    if isinstance(arr, list):
                        out.extend(arr)
            return out
        except Exception as e:
            logger.error("user_open_orders failed: %s", e)
            return []

    def check_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            for o in self._snapshot_open():
                if str(o.get("order_id")) == order_id:
                    return {"status": "open", "filled": 0.0, "remaining": float(o.get("quantity", 0.0))}
            try:
                tr = self.exchange.order_trades(order_id)
                if tr and tr.get("trades"):
                    filled = sum(float(t.get("quantity", 0.0)) for t in tr["trades"])
                    avg = 0.0
                    if filled > 0:
                        total = sum(float(t.get("quantity", 0.0)) * float(t.get("price", 0.0)) for t in tr["trades"])
                        avg = total / filled
                    return {"status": "filled", "filled": filled, "avg_price": avg}
            except Exception:
                pass
            return {"status": "cancelled", "filled": 0.0}
        except Exception as e:
            logger.error("check_order_status error: %s", e)
            return {"status": "unknown", "error": str(e)}

    def cancel_order_safe(self, order_id: str) -> bool:
        try:
            st = self.check_order_status(order_id)
            if st["status"] == "open":
                self.exchange.order_cancel(order_id)
                with self._lock:
                    if order_id in self.active:
                        info = self.active[order_id]
                        info.status = "cancelled"
                        self.history.append(info)
                        del self.active[order_id]
                logger.info("order %s cancelled", order_id)
                return True
            logger.info("order %s not cancellable (status %s)", order_id, st.get("status"))
            return False
        except Exception as e:
            logger.error("cancel_order_safe error: %s", e)
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
            old_ids = [oid for oid, info in self.active.items() if info.created_at < cutoff]
        for oid in old_ids:
            logger.info("cleaning up stale order %s", oid)
            self.cancel_order_safe(oid)

    def get_active_orders_summary(self) -> Dict[str, Any]:
        with self._lock:
            arr = list(self.active.values())
        return {
            "count": len(arr),
            "orders": [
                {
                    "order_id": x.order_id,
                    "pair": x.pair,
                    "side": x.side,
                    "price": x.price,
                    "quantity": x.quantity,
                    "age_seconds": (datetime.now() - x.created_at).total_seconds(),
                }
                for x in arr
            ],
        }
