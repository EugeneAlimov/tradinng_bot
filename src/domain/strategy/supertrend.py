# src/domain/strategy/supertrend.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _tr(high: List[float], low: List[float], close: List[float]) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(close)
    for i in range(len(close)):
        if i == 0:
            out[i] = high[i] - low[i]
        else:
            out[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
    return out


def _rma(values: List[Optional[float]], length: int) -> List[Optional[float]]:
    """Wilder's RMA (EMA с alpha=1/len) поверх Optional."""
    n = max(1, int(length))
    out: List[Optional[float]] = [None] * len(values)
    avg = None
    cnt = 0
    for i, v in enumerate(values):
        if v is None:
            out[i] = None
            continue
        cnt += 1
        if avg is None:
            # старт — простая средняя первых n значений
            # аккумулируем, пока не наберём n
            if cnt < n:
                out[i] = None
                avg = (avg or 0.0) + v
            else:
                total = (avg or 0.0) + v
                avg = total / n
                out[i] = avg
        else:
            alpha = 1.0 / n
            avg = alpha * v + (1 - alpha) * avg
            out[i] = avg
    return out


def _atr(high: List[float], low: List[float], close: List[float], length: int) -> List[Optional[float]]:
    tr = _tr(high, low, close)
    return _rma(tr, length)


def generate_signals(
        close: List[float],
        high: List[float],
        low: List[float],
        atr_len: int = 10,
        mult: float = 3.0,
) -> List[int]:
    """
    Supertrend: сигналы по развороту направления (dir -1→+1 => +1; +1→-1 => -1).
    """
    n = max(1, int(atr_len))
    m = float(mult)

    atr = _atr(high, low, close, n)
    mid = [(h + l) / 2.0 for h, l in zip(high, low)]
    ub = [None if atr[i] is None else mid[i] + m * atr[i] for i in range(len(close))]
    lb = [None if atr[i] is None else mid[i] - m * atr[i] for i in range(len(close))]

    fub: List[Optional[float]] = [None] * len(close)
    flb: List[Optional[float]] = [None] * len(close)
    dir_arr: List[int] = [0] * len(close)

    for i in range(len(close)):
        if i == 0 or ub[i] is None or lb[i] is None:
            fub[i] = ub[i]
            flb[i] = lb[i]
            dir_arr[i] = 0
            continue

        # финальные линии
        fub[i] = min(ub[i], fub[i - 1] if fub[i - 1] is not None else ub[i])
        flb[i] = max(lb[i], flb[i - 1] if flb[i - 1] is not None else lb[i])

        # направление
        if close[i] > (fub[i - 1] if fub[i - 1] is not None else ub[i]):
            dir_arr[i] = +1
        elif close[i] < (flb[i - 1] if flb[i - 1] is not None else lb[i]):
            dir_arr[i] = -1
        else:
            dir_arr[i] = dir_arr[i - 1]

        # при up-тренде верхняя линия не растёт, при down — нижняя не падает
        if dir_arr[i] == +1 and flb[i] is not None and flb[i - 1] is not None:
            flb[i] = max(flb[i], flb[i - 1])
        if dir_arr[i] == -1 and fub[i] is not None and fub[i - 1] is not None:
            fub[i] = min(fub[i], fub[i - 1])

    signals = [0] * len(close)
    for i in range(1, len(close)):
        if dir_arr[i - 1] <= 0 and dir_arr[i] > 0:
            signals[i] = +1
        elif dir_arr[i - 1] >= 0 and dir_arr[i] < 0:
            signals[i] = -1
    return signals


def status(
        close: List[float],
        high: List[float],
        low: List[float],
        atr_len: int = 10,
        mult: float = 3.0,
) -> Tuple[str, int]:
    n = max(1, int(atr_len))
    m = float(mult)

    atr = _atr(high, low, close, n)
    i = len(close) - 1
    if i < 0 or atr[i] is None:
        return f"ST(atr={n}, m={m}) dir=?, st=?", 0

    # приблизим текущую линию через серединку — достаточно для статуса
    mid = (high[i] + low[i]) / 2.0
    ub = mid + m * atr[i]
    lb = mid - m * atr[i]
    # direction по сравнению с предыдущим баром
    dir_val = 0
    if i >= 1:
        prev_mid = (high[i - 1] + low[i - 1]) / 2.0
        prev_ub = (atr[i - 1] is not None) and (prev_mid + m * atr[i - 1]) or ub
        prev_lb = (atr[i - 1] is not None) and (prev_mid - m * atr[i - 1]) or lb
        if close[i] > (prev_ub if isinstance(prev_ub, float) else ub):
            dir_val = +1
        elif close[i] < (prev_lb if isinstance(prev_lb, float) else lb):
            dir_val = -1
    return f"ST(atr={n}, m={m}) UB={ub:.6f} LB={lb:.6f}", dir_val


register(StrategyDef(
    name="supertrend",
    generate_signals=generate_signals,
    status=status,
    defaults={"atr_len": 10, "mult": 3.0},
))
