# src/strategies/ema_adx.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.indicators.ema import ema
from src.indicators.adx import compute_adx
from src.strategies.utils import build_trades_from_signals


def signals(
        df: pd.DataFrame,
        *,
        fast: int,
        slow: int,
        adx_len: int,
        on: float,
        off: float,
        require_di: bool,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    close = df["close"].astype(float)
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    adx, pdi, mdi = compute_adx(df, adx_len)

    long_on = (ema_fast > ema_slow) & (adx >= float(on))
    if bool(require_di):
        long_on = long_on & (pdi > mdi)
    long_off = (ema_fast < ema_slow) | (adx <= float(off))
    return long_on, long_off, ema_fast, ema_slow, adx


def build_trades(df: pd.DataFrame, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    if df.empty:
        return [], np.asarray([], dtype=float)
    long_on, long_off, ema_f, ema_s, adx = signals(df, **params)
    return build_trades_from_signals(df, long_on, long_off, ema_fast=ema_f, ema_slow=ema_s, adx=adx)
