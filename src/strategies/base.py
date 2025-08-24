# src/strategy/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Optional
import numpy as np
import pandas as pd


class Strategy(Protocol):
    """
    Контракт любой стратегии:
    на вход close (Series), на выход позиция по барам (Series из {0,1} или {-1,0,1}).
    """
    def generate_position(self, close: pd.Series) -> pd.Series:
        ...


@dataclass
class TradeFrictions:
    fee_bps: int = 10
    slip_bps: int = 0


@dataclass
class PositionSizing:
    qty_eur: float = 50.0


def apply_cooldown(position: pd.Series, cooldown_bars: int) -> pd.Series:
    """
    Применить cooldown к бинарной позиции 0/1.
    Если cooldown_bars > 0 — после смены состояния удерживаем его не меньше cooldown_bars баров.
    """
    if cooldown_bars <= 0:
        return position.astype(int)

    pos = position.astype(int).to_numpy()
    out = np.zeros_like(pos)
    state = 0
    cd = 0
    for i, v in enumerate(pos):
        if cd > 0:
            out[i] = state
            cd -= 1
            continue
        # смена?
        if v != state:
            state = v
            cd = cooldown_bars
        out[i] = state
    return pd.Series(out, index=position.index, name=position.name or "position")


def one_to_roundtrip_entries(position: pd.Series) -> pd.Series:
    """
    Превращает позицию 0/1 в массив входов (True в момент входа),
    удобно для оценки количества сделок.
    """
    prev = position.shift(1).fillna(0).astype(int)
    return (prev == 0) & (position == 1)
