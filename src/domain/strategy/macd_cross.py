# src/domain/strategy/macd_cross.py
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
            ema_val = px
        else:
            ema_val = px * k + ema_val * (1 - k)
        out[i] = ema_val
    return out


def generate_signals(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> List[int]:
    """
    MACD(line) = EMA_fast - EMA_slow
    Signal = EMA(MACD, signal)
      +1 — когда MACD пересекает Signal вверх,
      -1 — когда вниз.
    """
    ema_f = _ema(prices, fast)
    ema_s = _ema(prices, slow)

    macd: List[Optional[float]] = [None] * len(prices)
    for i in range(len(prices)):
        if ema_f[i] is None or ema_s[i] is None:
            macd[i] = None
        else:
            macd[i] = float(ema_f[i]) - float(ema_s[i])

    # EMA по macd
    sig_arr = _ema([0.0 if v is None else float(v) for v in macd], signal)

    signals = [0] * len(prices)
    last_state = 0
    for i in range(len(prices)):
        m = macd[i]
        s = sig_arr[i]
        if m is None or s is None:
            continue
        state = 1 if m > s else (-1 if m < s else 0)
        if state == 1 and last_state != 1:
            signals[i] = +1
        elif state == -1 and last_state != -1:
            signals[i] = -1
        if state != 0:
            last_state = state
    return signals


def status(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[str, int]:
    ema_f = _ema(prices, fast)
    ema_s = _ema(prices, slow)
    macd = [None if (ema_f[i] is None or ema_s[i] is None) else float(ema_f[i]) - float(ema_s[i])
            for i in range(len(prices))]
    sig_arr = _ema([0.0 if v is None else float(v) for v in macd], signal)
    i = len(prices) - 1
    if i < 0 or macd[i] is None or sig_arr[i] is None:
        return "MACD=?, SIG=?, HIST=?", 0
    m = float(macd[i])
    s = float(sig_arr[i])
    hist = m - s
    state = 1 if m > s else (-1 if m < s else 0)
    return f"MACD={m:.6f} SIG={s:.6f} HIST={hist:.6f}", state


register(StrategyDef(
    name="macd",
    generate_signals=generate_signals,
    status=status,
    defaults={"fast": 12, "slow": 26, "signal": 9},
))
