# src/domain/strategy/ema_crossover.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _ema(series: List[float], period: int) -> List[Optional[float]]:
    period = max(2, int(period))
    out: List[Optional[float]] = [None] * len(series)
    k = 2.0 / (period + 1.0)
    ema_val: Optional[float] = None
    for i, px in enumerate(series):
        if ema_val is None:
            ema_val = px  # простая инициализация
        else:
            ema_val = px * k + ema_val * (1 - k)
        out[i] = ema_val
    return out


def generate_signals(prices: List[float], fast: int = 12, slow: int = 26) -> List[int]:
    """
    EMA crossover:
      +1 — когда EMA_fast пересекает EMA_slow вверх,
      -1 — когда пересекает вниз.
    """
    fast = max(2, int(fast))
    slow = max(fast + 1, int(slow))
    ema_f = _ema(prices, fast)
    ema_s = _ema(prices, slow)

    signals = [0] * len(prices)
    last_state = 0
    for i in range(len(prices)):
        if ema_f[i] is None or ema_s[i] is None:
            continue
        state = 1 if ema_f[i] > ema_s[i] else (-1 if ema_f[i] < ema_s[i] else 0)
        if state == 1 and last_state != 1:
            signals[i] = +1
        elif state == -1 and last_state != -1:
            signals[i] = -1
        if state != 0:
            last_state = state
    return signals


def status(prices: List[float], fast: int = 12, slow: int = 26) -> Tuple[str, int]:
    ema_f = _ema(prices, max(2, fast))
    ema_s = _ema(prices, max(max(2, fast) + 1, slow))
    i = len(prices) - 1
    if i < 0 or ema_f[i] is None or ema_s[i] is None:
        return "EMAf=?, EMAs=?", 0
    f = float(ema_f[i])
    s = float(ema_s[i])
    state = 1 if f > s else (-1 if f < s else 0)
    return f"EMAf={f:.6f} EMAs={s:.6f}", state


register(StrategyDef(
    name="ema",
    generate_signals=generate_signals,
    status=status,
    defaults={"fast": 12, "slow": 26},
))
