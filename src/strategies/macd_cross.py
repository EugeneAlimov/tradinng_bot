# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.indicators.ema import ema
from src.strategies.utils import build_trades_from_signals

name = "macd_cross"


def signals(
    df: pd.DataFrame,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    MACD пересечка.
    Возвращает: long_on, long_off, macd, macd_signal
    """
    close = df["close"]
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)

    macd = ema_fast - ema_slow
    macd_signal = ema(macd, signal)

    long_on = (macd > macd_signal).fillna(False)
    long_off = (macd < macd_signal).fillna(False)

    idx = df.index
    return (
        long_on.reindex(idx, fill_value=False),
        long_off.reindex(idx, fill_value=False),
        macd.reindex(idx),
        macd_signal.reindex(idx),
    )


def build(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]:
    fees_bps: float = float(params.get("fees_bps", 0.0))
    slippage_bps: float = float(params.get("slippage_bps", 0.0))
    size: float = float(params.get("size", 100.0))
    sl_mult: float = float(params.get("sl_mult", 0.0))
    tp_mult: float = float(params.get("tp_mult", 0.0))
    trail_mult: float = float(params.get("trail_mult", 0.0))

    allowed = {"fast", "slow", "signal"}
    sig_cfg = {k: params[k] for k in allowed if k in params}
    long_on, long_off, macd, macd_sig = signals(df, **sig_cfg)

    trades, pnls = build_trades_from_signals(
        df=df,
        long_on=long_on,
        long_off=long_off,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        size=size,
        sl_mult=sl_mult,
        tp_mult=tp_mult,
        trail_mult=trail_mult,
        vol_series=None,
    )
    return trades, pnls, {"macd": macd, "macd_signal": macd_sig}
