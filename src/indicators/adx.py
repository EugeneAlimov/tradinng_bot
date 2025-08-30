# src/indicators/adx.py
from __future__ import annotations

import pandas as pd


def compute_adx(df: pd.DataFrame, length: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Возвращает (adx, pdi, mdi) с Wilder smoothing (alpha=1/length).
    Ожидает колонки high/low/close.
    """
    length = max(1, int(length))
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up_move = high.diff().clip(lower=0.0).fillna(0.0)
    down_move = (-low.diff()).clip(lower=0.0).fillna(0.0)

    tr1 = (high - low).abs()
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).fillna(0.0)

    alpha = 1.0 / float(length)
    atr = tr.ewm(alpha=alpha, adjust=False).mean()

    pdi = 100.0 * (up_move.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0.0, float("nan"))).fillna(0.0)
    mdi = 100.0 * (down_move.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0.0, float("nan"))).fillna(0.0)

    dx = (100.0 * (pdi - mdi).abs() / (pdi + mdi).replace(0.0, float("nan"))).fillna(0.0)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx, pdi, mdi
