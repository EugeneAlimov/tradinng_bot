# src/domain/strategy/adx_trend.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


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


def _rma_float(vals: List[float], length: int) -> List[float]:
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


def _adx(high: List[float], low: List[float], close: List[float], length: int):
    n = max(2, int(length))
    tr = _tr(high, low, close)

    plus_dm = [0.0] * len(close)
    minus_dm = [0.0] * len(close)
    for i in range(1, len(close)):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0

    tr_rma = _rma_float(tr, n)
    plus_rma = _rma_float(plus_dm, n)
    minus_rma = _rma_float(minus_dm, n)

    plus_di = [0.0 if tr_rma[i] == 0 else 100.0 * plus_rma[i] / tr_rma[i] for i in range(len(close))]
    minus_di = [0.0 if tr_rma[i] == 0 else 100.0 * minus_rma[i] / tr_rma[i] for i in range(len(close))]
    dx = [0.0 if (plus_di[i] + minus_di[i]) == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i]) for i in range(len(close))]
    adx = _rma_float(dx, n)
    return plus_di, minus_di, adx


def generate_signals(
    close: List[float],
    high: List[float],
    low: List[float],
    adx_len: int = 14,
    min_adx: float = 20.0,
) -> List[int]:
    """
    +1 — пересечение DI+ вверх DI− при ADX>=min_adx
    -1 — пересечение DI− вверх DI+ при ADX>=min_adx
    """
    pdi, mdi, adx = _adx(high, low, close, adx_len)
    signals = [0] * len(close)
    last_rel = 0
    for i in range(len(close)):
        rel = 1 if pdi[i] > mdi[i] else (-1 if pdi[i] < mdi[i] else 0)
        if adx[i] >= min_adx:
            if rel == 1 and last_rel != 1:
                signals[i] = +1
            elif rel == -1 and last_rel != -1:
                signals[i] = -1
        last_rel = rel
    return signals


def status(
    close: List[float],
    high: List[float],
    low: List[float],
    adx_len: int = 14,
    min_adx: float = 20.0,
) -> Tuple[str, int]:
    pdi, mdi, adx = _adx(high, low, close, adx_len)
    i = len(close) - 1
    if i < 0:
        return f"ADX(len={adx_len}) adx=?, +di=?, -di=?", 0
    a = float(adx[i])
    p = float(pdi[i])
    m = float(mdi[i])
    state = 1 if (a >= min_adx and p > m) else (-1 if (a >= min_adx and m > p) else 0)
    return f"ADX(len={adx_len}) adx={a:.2f} +di={p:.2f} -di={m:.2f} min={min_adx}", state


register(StrategyDef(
    name="adx",
    generate_signals=generate_signals,
    status=status,
    defaults={"adx_len": 14, "min_adx": 20.0},
))
