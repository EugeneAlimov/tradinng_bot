# src/domain/strategy/sma_atr.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _sma(series: List[float], window: int) -> List[Optional[float]]:
    w = max(2, int(window))
    out: List[Optional[float]] = [None] * len(series)
    s = 0.0
    for i, x in enumerate(series):
        s += x
        if i >= w:
            s -= series[i - w]
        if i >= w - 1:
            out[i] = s / w
    return out


def _tr(high: List[float], low: List[float], close: List[float]) -> List[float]:
    out = [0.0] * len(close)
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


def _rma(vals: List[float], length: int) -> List[float]:
    n = max(1, int(length))
    out = [0.0] * len(vals)
    avg = None
    for i, v in enumerate(vals):
        if avg is None:
            if i < n:
                out[i] = 0.0
                avg = (avg or 0.0) + v
                if i == n - 1:
                    out[i] = avg / n
                    avg = out[i]
            else:
                out[i] = v
                avg = v
        else:
            alpha = 1.0 / n
            avg = alpha * v + (1 - alpha) * avg
            out[i] = avg
    return out


def _atr(high: List[float], low: List[float], close: List[float], length: int) -> List[float]:
    return _rma(_tr(high, low, close), length)


def generate_signals(
    close: List[float],
    high: List[float],
    low: List[float],
    fast: int = 6,
    slow: int = 25,
    atr_len: int = 14,
    atr_mult: float = 3.0,
    chandelier_len: int = 22,
) -> List[int]:
    """
    Вход: кросс SMA(fast) вверх SMA(slow).
    Выход: min(кросс вниз, ChandelierExit), где
      CE = max(High последних N) - atr_mult * ATR(atr_len).
    """
    fast = max(2, int(fast))
    slow = max(fast + 1, int(slow))
    atr_len = max(1, int(atr_len))
    ce_n = max(2, int(chandelier_len))
    k = float(atr_mult)

    sma_f = _sma(close, fast)
    sma_s = _sma(close, slow)
    atr = _atr(high, low, close, atr_len)

    # rolling highest High
    hh: List[Optional[float]] = [None] * len(high)
    for i in range(len(high)):
        if i >= ce_n - 1:
            hh[i] = max(high[i - ce_n + 1:i + 1])

    in_pos = False
    signals = [0] * len(close)
    for i in range(len(close)):
        sf = sma_f[i]
        ss = sma_s[i]
        if sf is None or ss is None or atr[i] == 0.0 or hh[i] is None:
            continue
        cross_up = (sma_f[i - 1] is not None and sma_s[i - 1] is not None and sma_f[i - 1] <= sma_s[i - 1] and sf > ss)
        cross_dn = (sma_f[i - 1] is not None and sma_s[i - 1] is not None and sma_f[i - 1] >= sma_s[i - 1] and sf < ss)
        ce = float(hh[i]) - k * float(atr[i])

        if not in_pos and cross_up:
            signals[i] = +1
            in_pos = True
        elif in_pos:
            if cross_dn or close[i] < ce:
                signals[i] = -1
                in_pos = False
    return signals


def status(
    close: List[float],
    high: List[float],
    low: List[float],
    fast: int = 6,
    slow: int = 25,
    atr_len: int = 14,
    atr_mult: float = 3.0,
    chandelier_len: int = 22,
) -> Tuple[str, int]:
    sma_f = _sma(close, max(2, fast))
    sma_s = _sma(close, max(max(2, fast) + 1, slow))
    atr = _atr(high, low, close, max(1, atr_len))
    i = len(close) - 1
    if i < 0 or sma_f[i] is None or sma_s[i] is None:
        return "SMA+ATR: SMAf=?, SMAs=?, CE=?", 0
    # approx CE через последние ce_n и atr
    ce_n = max(2, int(chandelier_len))
    if i < ce_n - 1:
        return "SMA+ATR: SMAf=?, SMAs=?, CE=?", 0
    hh = max(high[i - ce_n + 1:i + 1])
    ce = hh - float(atr_mult) * float(atr[i])
    f = float(sma_f[i]); s = float(sma_s[i]); c = float(close[i])
    state = 1 if f > s else (-1 if (c < ce or f < s) else 0)
    return f"SMAf={f:.6f} SMAs={s:.6f} CE={ce:.6f}", state


register(StrategyDef(
    name="sma_atr",
    generate_signals=generate_signals,
    status=status,
    defaults={"fast": 6, "slow": 25, "atr_len": 14, "atr_mult": 3.0, "chandelier_len": 22},
))
