# src/application/sync.py
from typing import Dict, Any, List, Tuple

BOT_TAG_PREFIX = "BOT_"  # clientOrderId будет начинаться с этого префикса

def make_client_order_id(strategy_name: str, salt: str) -> str:
    # salt = например timestamp или UUID
    return f"{BOT_TAG_PREFIX}{strategy_name}_{salt}"

def is_our_order(order: Dict[str, Any]) -> bool:
    cid = order.get("clientOrderId") or order.get("client_order_id") or ""
    return cid.startswith(BOT_TAG_PREFIX)

def sync_exchange_state(api) -> Tuple[Dict[str, float], List[Dict[str, Any]], Dict[str, float]]:
    """
    Возвращает (balances, open_orders, positions)
    - api обязан иметь методы: get_balances(), get_open_orders(), get_positions() (или соответствующие)
    - open_orders помечаются флагом 'ours' = True/False
    """
    balances = api.get_balances()               # {"EUR": 812.34, "DOGE": 5234.0, ...}
    open_orders = api.get_open_orders() or []   # список ордеров словарями
    for o in open_orders:
        o["ours"] = is_our_order(o)

    # Если у api нет get_positions(), собери «псевдопозиции» по балансу спот:
    try:
        positions = api.get_positions()
    except AttributeError:
        positions = {}
        # Например: позиции по споту — это просто текущие остатки
        for asset, amt in balances.items():
            if asset not in ("EUR", "USDT", "USD", "USDC"):
                positions[asset] = amt

    return balances, open_orders, positions
