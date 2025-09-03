# src/strategies/donchian.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from .utils import build_trades_from_signals


@dataclass
class Params:
    ch_len: int = 20
    atr_len: int = 14
    atr_mult_sl: float = 1.0  # множитель ATR для SL (None -> не использовать)
    atr_mult_tp: float | None = None
    trail_mult: float | None = None


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    """Простой ATR (среднее True Range)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = np.maximum.reduce([tr1.values, tr2.values, tr3.values])
    tr = pd.Series(tr, index=df.index)
    return tr.rolling(n, min_periods=n).mean()


def signals(df: pd.DataFrame, p: Params) -> Tuple[pd.Series, pd.Series]:
    """Donchian breakout: long_on при пробое верхней границы; long_off при пробое нижней."""
    hi = df["high"].rolling(p.ch_len, min_periods=p.ch_len).max()
    lo = df["low"].rolling(p.ch_len, min_periods=p.ch_len).min()
    close = df["close"]

    long_on = close > hi.shift(1)
    long_off = close < lo.shift(1)
    return long_on.fillna(False), long_off.fillna(False)


def build(df: pd.DataFrame, p: Params, **exec_kwargs: Any):
    """
    Поддержка волатильностных стопов/тейков через ATR.
    vol_series прокидываем в build_trades_from_signals.
    """
    long_on, long_off = signals(df, p)
    vol_series = _atr(df, p.atr_len)

    # Проброс vol_series + множители, если вызывающая сторона их использует.
    kwargs = dict(exec_kwargs)
    kwargs.setdefault("vol_series", vol_series)
    if p.atr_mult_sl is not None:
        kwargs.setdefault("sl_mult", p.atr_mult_sl)
    if p.atr_mult_tp is not None:
        kwargs.setdefault("tp_mult", p.atr_mult_tp)
    if p.trail_mult is not None:
        kwargs.setdefault("trail_mult", p.trail_mult)

    trades, pnl = build_trades_from_signals(df, long_on, long_off, **kwargs)
    extra: Dict[str, Any] = {"atr": vol_series}
    return trades, pnl, extra


def default_grid() -> Dict[str, List[Any]]:
    return {
        "ch_len": [20, 30, 55],
        "atr_len": [10, 14, 20],
        "atr_mult_sl": [1.0, 1.5, 2.0],
        "atr_mult_tp": [None, 2.0, 3.0],
        "trail_mult": [None, 1.0, 1.5],
    }


def name() -> str:
    return "donchian"
