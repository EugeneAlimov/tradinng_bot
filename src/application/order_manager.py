# src/application/order_manager.py
from typing import Dict, Any, List
from .sync import is_our_order

class OrderManager:
    def __init__(self, api):
        self.api = api

    def filter_available_balance(self, balances: Dict[str, float], open_orders: List[Dict[str, Any]], quote: str, base: str):
        """Вычитаем из доступного баланса объёмы, уже занятые ВНЕШНИМИ лимитами пользователя."""
        reserved_quote = 0.0
        reserved_base  = 0.0
        for o in open_orders:
            if is_our_order(o):
                continue
            if o.get("symbol") in (f"{base}_{quote}", f"{base}/{quote}"):
                side = (o.get("side") or "").lower()
                if side == "buy":
                    # внешняя лимитка buy — резервируем котируемую валюту
                    reserved_quote += float(o.get("amount_quote") or o.get("quote_amount") or 0.0)
                elif side == "sell":
                    # внешняя лимитка sell — резервируем базовую валюту
                    reserved_base  += float(o.get("amount_base") or o.get("base_amount") or o.get("quantity") or 0.0)

        free_quote = max(0.0, float(balances.get(quote, 0.0)) - reserved_quote)
        free_base  = max(0.0, float(balances.get(base, 0.0))  - reserved_base)
        return free_quote, free_base

    def place_if_allowed(self, mode_should_trade: bool, **order_kwargs):
        """Не посылаем ордера, если режим не TRADE."""
        if not mode_should_trade:
            return {"status": "skipped", "reason": "observe mode"}
        return self.api.place_order(**order_kwargs)
