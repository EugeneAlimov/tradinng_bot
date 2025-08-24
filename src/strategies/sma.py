# src/strategy/sma.py
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
from .base import Strategy, apply_cooldown


@dataclass
class SMACrossParams:
    fast: int
    slow: int
    hysteresis_bps: int = 0
    cooldown_bars: int = 0


class SMACrossStrategy(Strategy):
    """
    Простой SMA crossover:
    - позиция 1, если (fast - slow)/slow > +hysteresis_bps
    - позиция 0, если (fast - slow)/slow < -hysteresis_bps
    - иначе удерживаем предыдущее состояние
    """
    def __init__(self, params: SMACrossParams):
        self.p = params

    def generate_position(self, close: pd.Series) -> pd.Series:
        fma = close.rolling(self.p.fast, min_periods=self.p.fast).mean()
        sma = close.rolling(self.p.slow, min_periods=self.p.slow).mean()
        diff_bps = (fma - sma) / sma.replace(0, np.nan) * 1e4
        diff_bps = diff_bps.fillna(0.0)

        pos = np.zeros(len(close), dtype=np.int8)
        state = 0
        for i in range(len(close)):
            if state == 0 and diff_bps.iat[i] > self.p.hysteresis_bps:
                state = 1
            elif state == 1 and diff_bps.iat[i] < -self.p.hysteresis_bps:
                state = 0
            pos[i] = state

        raw = pd.Series(pos, index=close.index, name="position")
        return apply_cooldown(raw, self.p.cooldown_bars)
