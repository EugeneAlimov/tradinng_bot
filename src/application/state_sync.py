# src/application/state_sync.py
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExchangeState:
    balances: Dict[str, Decimal] = field(default_factory=dict)
    open_orders: List[Dict[str, Any]] = field(default_factory=list)
    positions: Dict[str, Decimal] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class LocalState:
    pos_qty: Decimal = Decimal("0")
    cash_eur: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    pnl_sum_pos: Decimal = Decimal("0")
    pnl_sum_neg: Decimal = Decimal("0")
    round_trips: int = 0
    wins: int = 0
    timestamp: float = 0.0


class StateSynchronizer:
    """Согласование локального состояния и состояния на бирже."""

    def __init__(self, exchange_api: Any, pair: str, state_path: str = "data/bot_state.json"):
        self.exchange = exchange_api
        self.pair = pair
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self.local = LocalState()
        self.remote = ExchangeState()
        self._last_sync = 0.0
        self._sync_interval = 30.0
        self._lock = threading.Lock()

        self._load_local_state()
        self._start_background_sync()

    # ---------- persistence ----------

    def _load_local_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
            self.local = LocalState(
                pos_qty=Decimal(str(data.get("pos_qty", 0))),
                cash_eur=Decimal(str(data.get("cash_eur", 0))),
                avg_price=Decimal(str(data.get("avg_price", 0))),
                pnl_sum_pos=Decimal(str(data.get("pnl_sum_pos", 0))),
                pnl_sum_neg=Decimal(str(data.get("pnl_sum_neg", 0))),
                round_trips=int(data.get("round_trips", 0)),
                wins=int(data.get("wins", 0)),
                timestamp=float(data.get("timestamp", 0.0)),
            )
            logger.info("Loaded local state: pos=%s", self.local.pos_qty)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to load state %s: %s", self.state_path, e)

    def _save_local_state(self) -> None:
        with self._lock:
            tmp = self.state_path.with_suffix(".tmp")
            try:
                payload = {
                    "pos_qty": str(self.local.pos_qty),
                    "cash_eur": str(self.local.cash_eur),
                    "avg_price": str(self.local.avg_price),
                    "pnl_sum_pos": str(self.local.pnl_sum_pos),
                    "pnl_sum_neg": str(self.local.pnl_sum_neg),
                    "round_trips": self.local.round_trips,
                    "wins": self.local.wins,
                    "timestamp": time.time(),
                }
                tmp.write_text(json.dumps(payload, indent=2))
                tmp.replace(self.state_path)
            except Exception as e:  # noqa: BLE001
                logger.error("Failed to save state %s: %s", self.state_path, e)
                if tmp.exists():
                    tmp.unlink(missing_ok=True)

    # ---------- sync ----------

    def sync_with_exchange(self, force: bool = False) -> ExchangeState:
        now = time.time()
        if not force and (now - self._last_sync) < self._sync_interval:
            return self.remote

        try:
            info = self.exchange.user_info() or {}
            balances = info.get("balances") or info.get("balance") or {}

            base, quote = self.pair.split("_", 1)

            open_orders = self.exchange.user_open_orders()
            po = open_orders.get(self.pair, []) if isinstance(open_orders, dict) else []

            self.remote = ExchangeState(
                balances={
                    base: Decimal(str(balances.get(base, 0))),
                    quote: Decimal(str(balances.get(quote, 0))),
                },
                open_orders=list(po) if isinstance(po, list) else [],
                positions={base: Decimal(str(balances.get(base, 0)))},
                timestamp=now,
            )
            self._last_sync = now
            self._validate_consistency()
            return self.remote
        except Exception as e:  # noqa: BLE001
            logger.error("Exchange sync failed: %s", e)
            return self.remote

    def _validate_consistency(self) -> None:
        base, _ = self.pair.split("_", 1)
        exch_pos = self.remote.positions.get(base, Decimal("0"))
        local_pos = self.local.pos_qty
        tol = Decimal("0.00001")
        if abs(exch_pos - local_pos) > tol:
            logger.warning("Position mismatch. Exchange=%s, Local=%s -> reconcile to exchange.",
                           exch_pos, local_pos)
            self.local.pos_qty = exch_pos
            if exch_pos < tol:
                self.local.avg_price = Decimal("0")
            self._save_local_state()

    # ---------- live updates ----------

    def update_after_trade(self, side: str, qty: Decimal, price: Decimal, fee: Decimal = Decimal("0")) -> None:
        with self._lock:
            if side.upper() == "BUY":
                total_cost = self.local.pos_qty * self.local.avg_price + qty * price
                self.local.pos_qty += qty
                if self.local.pos_qty > 0:
                    self.local.avg_price = total_cost / self.local.pos_qty
                self.local.cash_eur -= (qty * price + fee)
            else:  # SELL
                if self.local.pos_qty > 0:
                    pnl = (price - self.local.avg_price) * qty - fee
                    if pnl > 0:
                        self.local.pnl_sum_pos += pnl
                        self.local.wins += 1
                    else:
                        self.local.pnl_sum_neg += pnl
                    self.local.round_trips += 1

                self.local.pos_qty -= qty
                self.local.cash_eur += (qty * price - fee)

                if self.local.pos_qty <= Decimal("0.00001"):
                    self.local.pos_qty = Decimal("0")
                    self.local.avg_price = Decimal("0")

            self._save_local_state()

        # запланировать жёсткую сверку
        threading.Timer(5.0, lambda: self.sync_with_exchange(force=True)).start()

    # ---------- helpers ----------

    def get_current_state(self) -> Dict[str, Any]:
        base, quote = self.pair.split("_", 1)
        return {
            "local": {
                "position": str(self.local.pos_qty),
                "avg_price": str(self.local.avg_price),
                "cash": str(self.local.cash_eur),
                "total_pnl": str(self.local.pnl_sum_pos + self.local.pnl_sum_neg),
                "win_rate": f"{(self.local.wins / max(1, self.local.round_trips)) * 100:.2f}%",
                "round_trips": self.local.round_trips,
            },
            "exchange": {
                base: str(self.remote.balances.get(base, 0)),
                quote: str(self.remote.balances.get(quote, 0)),
                "open_orders": len(self.remote.open_orders),
                "last_sync": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.remote.timestamp)),
            },
        }

    def reconcile_after_restart(self) -> None:
        logger.info("Reconcile after restart...")
        self.sync_with_exchange(force=True)
        for o in self.remote.open_orders:
            logger.info("Open order on restart: %s", o.get("order_id"))

    # ---------- background ----------

    def _start_background_sync(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self._sync_interval)
                try:
                    self.sync_with_exchange()
                except Exception as e:  # noqa: BLE001
                    logger.error("Background sync error: %s", e)

        threading.Thread(target=loop, daemon=True).start()
