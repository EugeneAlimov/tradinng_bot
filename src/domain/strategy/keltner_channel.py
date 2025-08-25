# src/domain/strategy/keltner_channel.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _ema(series: List[float], period: int) -> List[Optional[float]]:
    p = max(2, int(period))
    out: List[Optional[float]] = [None] * len(series)
    k = 2.0 / (p + 1.0)
    v: Optional[float] = None
    for i, x in enumerate(series):
        v = x if v is None else x * k + v * (1 - k)
        out[i] = v
    return out


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
    return _rma(_tr(high, low, close), length)


def generate_signals(
        close: List[float],
        high: List[float],
        low: List[float],
        kc_len: int = 20,
        kc_mult: float = 2.0,
        mode: str = "breakout",  # 'breakout' | 'meanrev'
        exit_rule: str = "mid",  # для meanrev: 'mid'|'upper'
) -> List[int]:
    """
    Keltner Channels:
      Middle = EMA(close, kc_len)
      Upper/Lower = Middle ± kc_mult * ATR(kc_len)
    - breakout: +1 при пробое Upper, -1 при пробое Lower
    - meanrev:  +1 при падении ниже Lower (пересечение вниз), выход по 'mid' или 'upper'
    """
    m = _ema(close, kc_len)
    a = _atr(high, low, close, kc_len)
    upper = [None if m[i] is None or a[i] is None else m[i] + kc_mult * a[i] for i in range(len(close))]
    lower = [None if m[i] is None or a[i] is None else m[i] - kc_mult * a[i] for i in range(len(close))]

    mode = (mode or "breakout").lower()
    exit_rule = (exit_rule or "mid").lower()

    signals = [0] * len(close)
    prev = None
    for i, c in enumerate(close):
        u = upper[i]
        l = lower[i]
        mid = m[i]
        if u is None or l is None or mid is None:
            prev = c
            continue
        if mode == "breakout":
            if prev is not None and prev <= u and c > u:
                signals[i] = +1
            elif prev is not None and prev >= l and c < l:
                signals[i] = -1
        else:  # meanrev
            if prev is not None and prev >= l and c < l:
                signals[i] = +1
            else:
                if exit_rule == "mid":
                    if prev is not None and prev <= mid and c > mid:
                        signals[i] = -1
                else:  # 'upper'
                    if prev is not None and prev <= u and c > u:
                        signals[i] = -1
        prev = c
    return signals


def status(
        close: List[float],
        high: List[float],
        low: List[float],
        kc_len: int = 20,
        kc_mult: float = 2.0,
        mode: str = "breakout",
        exit_rule: str = "mid",
) -> Tuple[str, int]:
    m = _ema(close, kc_len)
    a = _atr(high, low, close, kc_len)
    i = len(close) - 1
    if i < 0 or m[i] is None or a[i] is None:
        return f"KC(len={kc_len}, mult={kc_mult}) mid=?, atr=?", 0
    mid = float(m[i])
    atr = float(a[i])
    u = mid + kc_mult * atr
    l = mid - kc_mult * atr
    c = float(close[i])
    # грубый state: выше U => -1 для meanrev, +1 для breakout; ниже L — наоборот
    if mode == "breakout":
        state = 1 if c > u else (-1 if c < l else 0)
    else:
        state = 1 if c < l else (-1 if c > u else 0)
    return f"KC(len={kc_len}, mult={kc_mult}) U={u:.6f} L={l:.6f}", state


register(StrategyDef(
    name="keltner",
    generate_signals=generate_signals,
    status=status,
    defaults={"kc_len": 20, "kc_mult": 2.0, "mode": "breakout", "exit_rule": "mid"},
))
