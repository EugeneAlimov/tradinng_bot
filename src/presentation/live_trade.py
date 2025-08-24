# -*- coding: utf-8 -*-
"""
Live trading runner with:
- SafeExmoWrapper for strict data validation
- ImprovedOrderManager for unique client_id
- ErrorRecoverySystem (circuit breaker + retry) around critical API calls
- Fixed 'dust_sweep' name error; safe EUR balance parsing; robust sold_qty fallback

This module intentionally keeps the execution model simple:
  run_live_trade(cfg) -> starts a bounded example loop (or single iteration) that demonstrates
  safe interactions with the exchange while being easy to extend.

Integrations:
  - expects EXMO API credentials in env or passed to ExmoPrivate
  - strategy signal calculation should be injected (see TODO: section)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from src.integrations.exmo_private import ExmoPrivate
from src.infrastructure.exchange.order_manager import ImprovedOrderManager
from src.infrastructure.exchange.validator import SafeExmoWrapper, ExchangeDataValidator
from src.infrastructure.resilience.circuit_breaker import (
    ErrorRecoverySystem,
    CircuitBreakerConfig,
    network_error_recovery,
    rate_limit_recovery,
)

logger = logging.getLogger(__name__)


# ---------------------------- config ----------------------------

@dataclass
class LiveTradeConfig:
    pair: str = "DOGE_EUR"
    max_notional_eur: Decimal = Decimal("100")
    maker: bool = False
    tick_ms: int = 1000
    # how many iterations (for demo). Use 0 or <0 for infinite loop.
    iterations: int = 1


# ---------------------------- utilities ----------------------------

def _safe_decimal(value: Any) -> Decimal:
    try:
        return ExchangeDataValidator.to_decimal(value, "value")
    except Exception:
        return Decimal("0")


def _mask(v: Optional[str]) -> str:
    if not v:
        return "<none>"
    return f"<len={len(v)}>"


# ---------------------------- live trading core ----------------------------

class LiveTrader:
    def __init__(self, exmo: ExmoPrivate, cfg: LiveTradeConfig):
        self.exmo = exmo
        self.safe = SafeExmoWrapper(self.exmo)
        self.orders = ImprovedOrderManager(self.exmo)
        self.cfg = cfg

        # resilience layer
        self.res = ErrorRecoverySystem()
        # register optional recovery strategies
        self.res.register_strategy("ConnectionError", network_error_recovery)
        self.res.register_strategy("HTTPError", rate_limit_recovery)

        # create circuits for different classes of calls
        self.cb_public_name = "exmo_public"
        self.cb_private_name = "exmo_private"
        self.res.circuit(self.cb_public_name, CircuitBreakerConfig(failure_threshold=5, recovery_timeout=10))
        self.res.circuit(self.cb_private_name, CircuitBreakerConfig(failure_threshold=3, recovery_timeout=15))

    # ---- API wrappers through circuit breaker & retry ----

    def _public(self, func, *a, **kw):
        return self.res.protected_call(func, self.cb_public_name, True, *a, **kw)

    def _private(self, func, *a, **kw):
        return self.res.protected_call(func, self.cb_private_name, True, *a, **kw)

    # ---- data fetchers ----

    def _get_balances(self) -> Dict[str, Any]:
        vals = self._private(self.safe.get_validated_balances)
        return vals

    def _get_ticker(self, pair: str) -> Optional[Any]:
        return self._public(self.safe.get_validated_ticker, pair)

    # ---- basic trading helpers ----

    def _can_buy(self, price: Decimal, eur_free: Decimal) -> Tuple[bool, Decimal]:
        if price <= 0:
            return False, Decimal("0")
        max_eur = min(self.cfg.max_notional_eur, eur_free)
        qty = (max_eur / price).quantize(Decimal("0.00000001"))
        return (qty > 0), qty

    def _can_sell(self, qty_free: Decimal) -> Tuple[bool, Decimal]:
        qty = min(qty_free, (self.cfg.max_notional_eur / Decimal("1")).quantize(Decimal("0.00000001")))
        return (qty > 0), qty

    # ---- dust sweep (fixed scope) ----

    def dust_sweep(self, min_qty: Decimal = Decimal("0.00000001")) -> None:
        """
        Cancel stale open orders and cleanup tiny positions if necessary.
        Implement your own logic if exchange supports explicit dust conversion.
        """
        try:
            summary = self.orders.get_active_orders_summary()
            if summary["count"] > 0:
                logger.info("Active orders before sweep: %s", summary["count"])
        except Exception as e:
            logger.warning("dust_sweep summary failed: %s", e)

        # Cancel old orders if any linger
        try:
            self.orders.cleanup_old_orders(max_age_minutes=5)
        except Exception as e:
            logger.warning("dust_sweep cleanup failed: %s", e)

        # No explicit EXMO dust endpoint; noop for now
        logger.debug("dust_sweep completed")

    # ---- main step ----

    def step(self) -> Optional[Dict[str, Any]]:
        pair = self.cfg.pair

        # balances & ticker (validated)
        balances = self._get_balances()
        eur_free = Decimal("0")
        base_free = Decimal("0")

        # balances dict → ValidatedBalance
        if balances:
            eur = balances.get("EUR") or balances.get("eur")
            if eur:
                eur_free = eur.free
            base_ccy = pair.split("_")[0].upper()
            base = balances.get(base_ccy)
            if base:
                base_free = base.free

        tkr = self._get_ticker(pair)
        if not tkr:
            logger.warning("No ticker for %s", pair)
            return None

        bid = tkr.bid
        ask = tkr.ask
        mid = (bid + ask) / 2

        # TODO: plug your strategy signal here, now we do a simple demo rule
        # demo signal: if no base, try to buy a tiny amount; if we have base, sell a tiny amount
        decision = "buy" if base_free <= Decimal("0") else "sell"

        if decision == "buy":
            can, qty = self._can_buy(ask, eur_free)
            if can and qty > Decimal("0"):
                ok, oid, err = self.orders.place_order_with_retry(
                    pair=pair, side="buy", price=float(ask), quantity=float(qty)
                )
                if ok and oid:
                    st = self.orders.wait_for_fill(oid, timeout=5.0)
                    return {"action": "buy", "order_id": oid, "status": st}
                return {"action": "buy", "error": err}
            logger.info("Skip buy: not enough balance (eur_free=%s, ask=%s)", eur_free, ask)
            return {"action": "skip_buy", "eur_free": str(eur_free), "ask": str(ask)}

        if decision == "sell":
            can, qty = self._can_sell(base_free)
            if can and qty > Decimal("0"):
                # sold_qty fallback fix: execute at bid, not negative, cap by base_free
                sell_qty = min(qty, base_free)
                if sell_qty <= 0:
                    return {"action": "skip_sell", "base_free": str(base_free)}
                ok, oid, err = self.orders.place_order_with_retry(
                    pair=pair, side="sell", price=float(bid), quantity=float(sell_qty)
                )
                if ok and oid:
                    st = self.orders.wait_for_fill(oid, timeout=5.0)
                    return {"action": "sell", "order_id": oid, "status": st}
                return {"action": "sell", "error": err}
            logger.info("Skip sell: not enough base (base_free=%s, bid=%s)", base_free, bid)
            return {"action": "skip_sell", "base_free": str(base_free), "bid": str(bid)}

        return None

    # ---- runner ----

    def run(self) -> None:
        iters = self.cfg.iterations
        i = 0
        while iters <= 0 or i < iters:
            i += 1
            try:
                report = self.step()
                if report:
                    logger.info("live step report: %s", report)
            except Exception as e:
                # Pass through the recovery system: raises if unrecoverable
                try:
                    self.res.handle(e, {"stage": "step", "pair": self.cfg.pair})
                except Exception as final_e:
                    logger.exception("Live step failed: %s", final_e)
            finally:
                time.sleep(max(0.05, self.cfg.tick_ms / 1000.0))


# ---------------------------- public API ----------------------------

def run_live_trade(cfg: Optional[LiveTradeConfig] = None) -> None:
    """Convenience entrypoint used by CLI/launcher."""
    cfg = cfg or LiveTradeConfig()
    exmo = ExmoPrivate()  # creds come from env
    try:
        LiveTrader(exmo, cfg).run()
    finally:
        exmo.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_live_trade()
