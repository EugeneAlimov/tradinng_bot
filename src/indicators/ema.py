# src/indicators/ema.py
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    """Стандартная EMA с adjust=False. На невалидном span возвращает NaN-серию."""
    span = int(span)
    if span <= 0:
        return pd.Series([float("nan")] * len(series), index=series.index)
    return series.ewm(span=span, adjust=False).mean()
