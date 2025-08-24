# src/strategy/filters.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable
import numpy as np
import pandas as pd


def volatility_mask(close: pd.Series, window: int = 30, max_bps: float = 50.0) -> pd.Series:
    """
    Пропускаем бары, где rolling-вола (стд.откл. доходности на бар) ниже max_bps (в bps).
    Если вола выше порога — маска False (торговлю отключаем).
    """
    rets = close.pct_change()
    vol = rets.rolling(window, min_periods=window).std().fillna(0.0)
    vol_bps = vol * 1e4
    allow = vol_bps <= max_bps
    return pd.Series(allow.astype(int), index=close.index, name="vol_mask")


def session_mask(index: pd.DatetimeIndex, allowed_hours: Iterable[int], tz: Optional[str] = "UTC") -> pd.Series:
    """
    Маска по часам (например, не торговать ночью).
    allowed_hours — список часов [0..23], в которых торговля разрешена.
    """
    if tz:
        idx = index.tz_convert(tz) if index.tz is not None else index.tz_localize(tz)
    else:
        idx = index
    hours = idx.hour
    allow = pd.Series([int(h in set(allowed_hours)) for h in hours], index=index, name="sess_mask")
    return allow


def apply_masks(position_01: pd.Series, *masks_01: pd.Series) -> pd.Series:
    """
    Перемножаем бинарные маски (0/1), отключая торговлю, где маска=0.
    """
    out = position_01.astype(int).copy()
    for m in masks_01:
        aligned = m.reindex(out.index).fillna(0).astype(int)
        out = out * aligned
    return out


def daily_loss_killswitch(equity: pd.Series, max_daily_loss_bps: int = 0) -> pd.Series:
    """
    Возвращает маску 0/1: 0 — если в течение данного дня достигнут лимит потерь (в bps от стартового equity дня).
    Предполагается использовать для «обнуления» позиционной маски на остаток дня.
    """
    if max_daily_loss_bps <= 0:
        return pd.Series(1, index=equity.index, name="dd_kill")

    df = equity.to_frame("eq")
    df["day"] = df.index.tz_convert("UTC").date if equity.index.tz is not None else df.index.date
    groups = df.groupby("day", sort=False)
    mask = pd.Series(1, index=equity.index, name="dd_kill")
    bps = max_daily_loss_bps / 1e4

    for day, g in groups:
        start = float(g["eq"].iloc[0])
        thr = start * (1.0 - bps)
        # если equity падает ниже thr — до конца дня маска = 0
        breach = g["eq"] < thr
        if breach.any():
            first_i = breach.idxmax()  # первый True
            mask.loc[first_i:] = mask.loc[first_i:].where(g.index.max() < mask.index, 0)
            # точнее: «внутри дня до конца дня»:
            mask.loc[g.index[g.index.get_loc(first_i):].tolist()] = 0
    return mask
