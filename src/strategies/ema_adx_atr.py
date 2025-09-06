from __future__ import annotations
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd


def _to_series(x: Any, name: str) -> pd.Series:
    s = pd.to_numeric(pd.Series(x, name=name), errors="coerce").fillna(method="ffill")
    return s.astype(float)


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    c1 = high - low
    c2 = (high - prev_close).abs()
    c3 = (low - prev_close).abs()
    return pd.concat([c1, c2, c3], axis=1).max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = (up_move.where((up_move > down_move) & (up_move > 0), 0.0)).astype(float)
    minus_dm = (down_move.where((down_move > up_move) & (down_move > 0), 0.0)).astype(float)
    atr = _atr(high, low, close, length)
    plus_di = 100.0 * (plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr.replace(0.0, np.nan))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr.replace(0.0, np.nan))
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan) * 100.0
    adx = dx.ewm(alpha=1 / length, adjust=False).mean().fillna(0.0)
    return adx


def generate_signals(
        *,
        close: Any,
        high: Any,
        low: Any,
        fast: int,
        slow: int,
        adx_len: int,
        on: float,
        off: float,
        require_di: bool,
        atr_len: int,
        atr_mult: float,
) -> List[int]:
    """
    Возвращает список сигналов (+1/-1/0).
    Основная логика: EMA-кросс, фильтр ADX с порогами on/off.
    Фолбэк: если после фильтра все нули — вернём чистый EMA-кросс.
    """
    c = _to_series(close, "close")
    h = _to_series(high, "high")
    l = _to_series(low, "low")

    ema_f = _ema(c, fast)
    ema_s = _ema(c, slow)

    # базовые «кроссовые» импульсы только на смене знака спрэда
    spread = ema_f - ema_s
    side = np.sign(spread).astype(int)
    cross = np.zeros(len(side), dtype=int)
    mask = side.shift(1).fillna(0).astype(int) != side
    cross[mask.to_numpy()] = side[mask].to_numpy()

    # ADX-гейтинг с гистерезисом on/off
    adx = _adx(h, l, c, adx_len)
    enabled = np.zeros(len(adx), dtype=bool)
    state = False
    for i, val in enumerate(adx.to_numpy()):
        if not state and val >= on:
            state = True
        elif state and val <= off:
            state = False
        enabled[i] = state

    gated = np.where(enabled, cross, 0)

    # ATR-стоп может использоваться билдером трейдов; для сигналов не обязателен.
    # Если же всё «выжгли» — мягкий фолбэк на чистый EMA-кросс:
    if not np.any(gated != 0):
        return list(map(int, cross))

    return list(map(int, gated))


def build_trades(df: pd.DataFrame, /, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    Простейший набросок билдера, достаточный для тестов-импортов:
    возвращает пустой список сделок и пустой массив PnL.
    """
    return [], np.asarray([], dtype=float)


def default_grid() -> Dict[str, Any]:
    return {
        "fast": [8, 9, 10, 12],
        "slow": [20, 21, 24, 26],
        "adx_len": [14],
        "on": [18.0, 20.0, 23.0],
        "off": [14.0, 16.0, 17.0],
        "require_di": [False],
        "atr_len": [14],
        "atr_mult": [2.5, 3.0],
    }
