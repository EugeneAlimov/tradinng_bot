# src/domain/strategy/roc_momentum.py
from __future__ import annotations

from typing import List, Tuple

from .registry import StrategyDef, register


def generate_signals(prices: List[float], length: int = 12) -> List[int]:
    """
    Momentum ROC:
      roc = price / price[-length] - 1
      +1 — пересечение 0 вверх, -1 — вниз.
    """
    n = max(1, int(length))
    signals = [0] * len(prices)
    prev_roc = None
    for i in range(len(prices)):
        if i < n:
            continue
        roc = (prices[i] / prices[i - n]) - 1.0 if prices[i - n] != 0 else 0.0
        if prev_roc is not None:
            if prev_roc <= 0 and roc > 0:
                signals[i] = +1
            elif prev_roc >= 0 and roc < 0:
                signals[i] = -1
        prev_roc = roc
    return signals


def status(prices: List[float], length: int = 12) -> Tuple[str, int]:
    n = max(1, int(length))
    i = len(prices) - 1
    if i < n:
        return f"ROC(len={length}) val=?", 0
    roc = (prices[i] / prices[i - n]) - 1.0 if prices[i - n] != 0 else 0.0
    state = 1 if roc > 0 else (-1 if roc < 0 else 0)
    return f"ROC(len={length}) {roc * 100:.2f}%", state


register(StrategyDef(
    name="roc",
    generate_signals=generate_signals,
    status=status,
    defaults={"length": 12},
))
