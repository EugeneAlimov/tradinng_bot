# src/domain/strategy/rsi2_meanrev.py
from __future__ import annotations

from typing import List, Tuple, Optional

from .registry import StrategyDef, register


def _rsi(prices: List[float], length: int = 2) -> List[Optional[float]]:
    """
    Простой RSI: среднее приростов/снижений по окну length (без Wilder сглаживания).
    Для length=2 — «RSI-2 Коннорса».
    """
    if length <= 0:
        raise ValueError("length must be > 0")
    if len(prices) < length + 1:
        return [None] * len(prices)

    deltas = [0.0] * len(prices)
    for i in range(1, len(prices)):
        deltas[i] = prices[i] - prices[i - 1]

    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    # скользящее среднее по окну length (простое)
    def _sma(arr: List[float], win: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * len(arr)
        s = 0.0
        for i, x in enumerate(arr):
            s += x
            if i >= win:
                s -= arr[i - win]
            if i >= win:
                out[i] = s / win
        return out

    avg_gain = _sma(gains, length)
    avg_loss = _sma(losses, length)

    rsi: List[Optional[float]] = [None] * len(prices)
    for i in range(len(prices)):
        ag = avg_gain[i]
        al = avg_loss[i]
        if ag is None or al is None or (ag == 0 and al == 0):
            rsi[i] = None
        elif al == 0:
            rsi[i] = 100.0
        else:
            rs = ag / al
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def generate_signals(
        prices: List[float],
        rsi_len: int = 2,
        low: float = 10.0,
        high: float = 90.0,
) -> List[int]:
    """
    Mean Reversion (RSI-2): +1 при пересечении RSI ниже low, -1 при пересечении выше high.
    """
    rsi = _rsi(prices, rsi_len)
    signals = [0] * len(prices)
    prev = None
    for i in range(len(prices)):
        x = rsi[i]
        if x is None:
            continue
        if prev is not None:
            # вход, когда падаем ниже low
            if prev >= low and x < low:
                signals[i] = +1
            # выход, когда поднимаемся выше high
            elif prev <= high and x > high:
                signals[i] = -1
        prev = x
    return signals


def status(prices: List[float], rsi_len: int = 2, low: float = 10.0, high: float = 90.0) -> Tuple[str, int]:
    r = _rsi(prices, rsi_len)
    i = len(prices) - 1
    if i < 0 or r[i] is None:
        return "RSI=?, L=?, H=?", 0
    x = float(r[i])
    state = 1 if x < low else (-1 if x > high else 0)
    return f"RSI={x:.2f} L={low:.2f} H={high:.2f}", state


register(StrategyDef(
    name="rsi2",
    generate_signals=generate_signals,
    status=status,
    defaults={"rsi_len": 2, "low": 10.0, "high": 90.0},
))
