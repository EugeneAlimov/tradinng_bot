# src/strategies/ema_adx_atr.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# В текущем варианте ATR не участвует в логике входа/выхода,
# чтобы сохранить поведение, идентичное прежнему коду.
from src.strategies.ema_adx import signals as ema_adx_signals
from src.strategies.utils import build_trades_from_signals


def build_trades(df: pd.DataFrame, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    Поддерживает параметры atr_len/atr_mult, но логика входа/выхода такая же, как в ema_adx.
    Это сохраняет обратную совместимость текущих исследований.
    """
    if df.empty:
        return [], np.asarray([], dtype=float)
    # извлекаем только общие параметры; лишние безопасно игнорируются
    shared = {k: params[k] for k in ("fast", "slow", "adx_len", "on", "off", "require_di") if k in params}
    long_on, long_off, ema_f, ema_s, adx = ema_adx_signals(df, **shared)
    return build_trades_from_signals(df, long_on, long_off, ema_fast=ema_f, ema_slow=ema_s, adx=adx)
