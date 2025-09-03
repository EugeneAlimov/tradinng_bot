# src/strategies/macd_cross.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.indicators.ema import ema
from .utils import build_trades_from_signals


@dataclass
class Params:
    fast: int = 12
    slow: int = 26
    signal: int = 9


def signals(df: pd.DataFrame, p: Params) -> Tuple[pd.Series, pd.Series]:
    """Простое MACD пересечение signal."""
    macd_fast = ema(df["close"], p.fast)
    macd_slow = ema(df["close"], p.slow)
    macd = macd_fast - macd_slow
    macd_sig = ema(macd, p.signal)

    long_on = macd > macd_sig
    long_off = macd < macd_sig
    return long_on, long_off


def build(df: pd.DataFrame, p: Params, **exec_kwargs: Any):
    """
    Унифицированный build: возвращает (trades, pnl, extra?).
    Все торговые параметры (fees_bps, slippage_bps, size, sl_mult, tp_mult, trail_mult, vol_series и т.п.)
    пробрасываем через **exec_kwargs в build_trades_from_signals.
    """
    long_on, long_off = signals(df, p)
    trades, pnl = build_trades_from_signals(df, long_on, long_off, **exec_kwargs)
    extra: Dict[str, Any] = {}
    return trades, pnl, extra


def default_grid() -> Dict[str, List[int]]:
    return {
        "fast": [8, 12, 16],
        "slow": [21, 26, 34],
        "signal": [7, 9, 12],
    }


def name() -> str:
    return "macd_cross"
