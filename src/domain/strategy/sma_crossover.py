# src/domain/strategy/sma_crossover.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _sma(series: List[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("window must be > 0")
    out: List[Optional[float]] = [None] * len(series)
    s = 0.0
    for i, x in enumerate(series):
        s += x
        if i >= window:
            s -= series[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def generate_signals(prices: List[float], fast: int = 6, slow: int = 25) -> List[int]:
    """
    Кроссы SMA: +1 при пересечении fast вверх slow, -1 при пересечении вниз, 0 — иначе.
    """
    fast = max(2, int(fast))
    slow = max(fast + 1, int(slow))
    sma_f = _sma(prices, fast)
    sma_s = _sma(prices, slow)

    signals = [0] * len(prices)
    last_state = 0
    for i in range(len(prices)):
        if sma_f[i] is None or sma_s[i] is None:
            continue
        state = 1 if sma_f[i] > sma_s[i] else (-1 if sma_f[i] < sma_s[i] else 0)
        if state == 1 and last_state != 1:
            signals[i] = +1
        elif state == -1 and last_state != -1:
            signals[i] = -1
        if state != 0:
            last_state = state
    return signals


def status(prices: List[float], fast: int = 6, slow: int = 25) -> Tuple[str, int]:
    """Возвращает строку статуса и текущий state (1/-1/0)."""
    fast = max(2, int(fast))
    slow = max(fast + 1, int(slow))
    sma_f = _sma(prices, fast)
    sma_s = _sma(prices, slow)
    i = len(prices) - 1
    if i < 0 or sma_f[i] is None or sma_s[i] is None:
        return "SMAf=?, SMAs=?", 0
    f = float(sma_f[i])
    s = float(sma_s[i])
    state = 1 if f > s else (-1 if f < s else 0)
    return f"SMAf={f:.6f} SMAs={s:.6f}", state


# регистрация
register(StrategyDef(
    name="sma",
    generate_signals=generate_signals,
    status=status,
    defaults={"fast": 6, "slow": 25},
))
