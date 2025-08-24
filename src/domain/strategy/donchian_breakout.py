# src/domain/strategy/donchian_breakout.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _rolling_max(series: List[float], window: int) -> List[Optional[float]]:
    if window <= 1:
        raise ValueError("window must be > 1")
    out: List[Optional[float]] = [None] * len(series)
    dq = []
    for i, x in enumerate(series):
        # удаляем индексы вне окна (предыдущие N значений, без текущего)
        while dq and dq[0] <= i - window:
            dq.pop(0)
        # поддерживаем монотонную очередь
        while dq and series[dq[-1]] <= x:
            dq.pop()
        dq.append(i)
        # max по окну предшествующих баров (исключаем текущий бар)
        if i >= window:
            # верхняя граница — максимум предыдущих 'window' значений
            # dq[0] — индекс максимума, но может равняться i (текущий бар) — не допускаем
            # поэтому когда i >= window, гарантировано есть достаточное предыдущее окно
            # если dq[0] == i, снимаем его на время оценки
            if dq[0] == i:
                # ищем второй максимум в окне
                best = max(series[i - window:i])  # O(window), окно обычно небольшое
                out[i] = best
            else:
                out[i] = series[dq[0]]
    return out


def _rolling_min(series: List[float], window: int) -> List[Optional[float]]:
    if window <= 1:
        raise ValueError("window must be > 1")
    out: List[Optional[float]] = [None] * len(series)
    dq = []
    for i, x in enumerate(series):
        while dq and dq[0] <= i - window:
            dq.pop(0)
        while dq and series[dq[-1]] >= x:
            dq.pop()
        dq.append(i)
        if i >= window:
            if dq[0] == i:
                best = min(series[i - window:i])
                out[i] = best
            else:
                out[i] = series[dq[0]]
    return out


def generate_signals(prices: List[float], n: int = 20) -> List[int]:
    """
    Donchian breakout (по close):
      +1 — пересечение вверх верхней границы (rolling max предыдущих n),
      -1 — пересечение вниз нижней границы (rolling min предыдущих n).
    Примечание: используем Close вместо High/Low для простоты; при наличии H/L лучше заменить.
    """
    n = max(2, int(n))
    upper = _rolling_max(prices, n)
    lower = _rolling_min(prices, n)

    signals = [0] * len(prices)
    prev_close = None
    for i in range(len(prices)):
        u = upper[i]
        l = lower[i]
        c = prices[i]
        if u is None or l is None:
            prev_close = c
            continue
        # breakout вверх
        if prev_close is not None and prev_close <= u and c > u:
            signals[i] = +1
        # breakdown вниз
        elif prev_close is not None and prev_close >= l and c < l:
            signals[i] = -1
        prev_close = c
    return signals


def status(prices: List[float], n: int = 20) -> Tuple[str, int]:
    n = max(2, int(n))
    upper = _rolling_max(prices, n)
    lower = _rolling_min(prices, n)
    i = len(prices) - 1
    if i < 0 or upper[i] is None or lower[i] is None:
        return f"DON(n={n}) U=?, L=?", 0
    u = float(upper[i])
    l = float(lower[i])
    c = float(prices[i])
    state = 1 if c > u else (-1 if c < l else 0)
    return f"DON(n={n}) U={u:.6f} L={l:.6f}", state


register(StrategyDef(
    name="donchian",
    generate_signals=generate_signals,
    status=status,
    defaults={"n": 20},
))
