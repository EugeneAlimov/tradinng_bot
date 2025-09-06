# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.strategies.utils import build_trades_from_signals

name = "donchian"


def signals(
    df: pd.DataFrame,
    *,
    ch_len: int = 20,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Donchian channel breakout (close пробивает канал предыдущей свечи).
    Возвращает: long_on, long_off, hi, lo
    """
    hi = df["high"].rolling(ch_len, min_periods=1).max()
    lo = df["low"].rolling(ch_len, min_periods=1).min()

    # Пробой прошлых границ
    long_on = (df["close"] > hi.shift(1)).fillna(False)
    long_off = (df["close"] < lo.shift(1)).fillna(False)

    idx = df.index
    return (
        long_on.reindex(idx, fill_value=False),
        long_off.reindex(idx, fill_value=False),
        hi.reindex(idx),
        lo.reindex(idx),
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

    allowed = {"ch_len"}
    sig_cfg = {k: params[k] for k in allowed if k in params}
    long_on, long_off, hi, lo = signals(df, **sig_cfg)

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
    return trades, pnls, {"donchian_hi": hi, "donchian_lo": lo}
