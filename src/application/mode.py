# src/application/mode.py
from enum import Enum

class LiveMode(str, Enum):
    DISABLED = "disabled"   # Ничего не делать c биржей
    OBSERVE  = "observe"    # Считать сигналы, НО не выставлять ордера
    TRADE    = "trade"      # Полноценная торговля

def should_place_orders(mode: "LiveMode") -> bool:
    return mode == LiveMode.TRADE
