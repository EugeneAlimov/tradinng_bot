# src/indicators/atr.py
from __future__ import annotations

import pandas as pd


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    """
    Wilder ATR с alpha=1/length. Требуются колонки: high/low/close.
    """
    length = max(1, int(length))
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    prev_close = close.shift()
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).fillna(0.0)

    alpha = 1.0 / float(length)
    return tr.ewm(alpha=alpha, adjust=False).mean()
