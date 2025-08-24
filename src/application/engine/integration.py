# src/application/engine/integration.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.domain.risk.risk_service import RiskService, PositionSnapshot
from src.infrastructure.notify.telegram import TelegramNotifier


@dataclass
class EngineIntegration:
    """
    Связывает RiskService, TelegramNotifier и движок.
    Даёт готовые помощники для reconcile, pre-trade, on-fill и stop-loss.
    """
    notifier: TelegramNotifier
    risk: RiskService
    reconcile_threshold_qty: float = 0.0001

    # ---- Подключение к движку (мягкое) ----
    def attach(self, engine: Any) -> None:
        if hasattr(engine, "notifier"):
            setattr(engine, "notifier", self.notifier)
        if hasattr(engine, "risk_service"):
            setattr(engine, "risk_service", self.risk)
        if hasattr(engine, "reconcile_threshold_qty"):
            setattr(engine, "reconcile_threshold_qty", self.reconcile_threshold_qty)

    # ---- Reconcile ----
    def reconcile_positions(self, local_qty: float, exchange_qty: float) -> None:
        delta = abs(local_qty - exchange_qty)
        if delta > self.reconcile_threshold_qty:
            self.notifier.send(
                f"⚠️ Reconcile delta too high: |{local_qty:.8f} - {exchange_qty:.8f}| = {delta:.8f}"
            )

    # ---- Stop-loss ----
    def should_stop_out(self, qty: float, avg_price: float, mark_price: float) -> bool:
        if qty == 0:
            return False
        side = "LONG" if qty >= 0 else "SHORT"
        snap = PositionSnapshot(
            qty=qty,
            avg_price=avg_price,
            side=side,
            updated_at=datetime.now(timezone.utc),
        )
        return self.risk.should_stop_out(snap, mark_price)

    def notify_stop_and_close(self, qty: float, avg_price: float, mark_price: float) -> None:
        side = "LONG" if qty >= 0 else "SHORT"
        self.notifier.send(
            f"🛑 Stop-loss hit at {mark_price:.8f} (avg {avg_price:.8f}, side {side}) — closing position"
        )

    # ---- Pre-trade guard ----
    def pre_trade_guard(self, desired_qty: float, mark_price: float, equity: float) -> bool:
        ok, reason = self.risk.pre_trade_check(desired_qty, mark_price, equity)
        if not ok:
            self.notifier.send(f"⛔ Trade blocked: {reason}")
        return ok

    # ---- Post-fill ----
    def on_fill(self, qty: float, avg_price: float) -> None:
        side = "LONG" if qty >= 0 else "SHORT"
        snap = PositionSnapshot(
            qty=qty,
            avg_price=avg_price,
            side=side,
            updated_at=datetime.now(timezone.utc),
        )
        self.risk.on_fill(snap)
