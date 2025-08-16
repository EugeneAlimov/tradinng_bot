from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Literal


Signal = Literal["BUY", "SELL", "HOLD"]


@dataclass
class SmaCfg:
    """Конфиг SMA-crossover стратегии."""
    fast: int
    slow: int
    # Мёртвая зона в bps: |fast - slow| / price * 10_000 >= hysteresis_bps
    hysteresis_bps: float = 0.0


class SmaCrossover:
    """
    SMA crossover со встроенным гистерезисом в bps.
    Сигнал подаётся ТОЛЬКО если произошло пересечение И
    |fast - slow| / price * 10_000 >= hysteresis_bps на текущей свече.
    """
    def __init__(self, cfg: SmaCfg) -> None:
        if cfg.fast <= 0 or cfg.slow <= 0:
            raise ValueError("SMA lengths must be positive integers")
        self.cfg = cfg

    @staticmethod
    def _bps_delta(price: float, fast: float, slow: float) -> float:
        if price <= 0:
            return 0.0
        return abs(fast - slow) / price * 10_000.0

    @staticmethod
    def _crossed_up(prev_diff: float, curr_diff: float) -> bool:
        return prev_diff <= 0.0 and curr_diff > 0.0

    @staticmethod
    def _crossed_down(prev_diff: float, curr_diff: float) -> bool:
        return prev_diff >= 0.0 and curr_diff < 0.0

    def generate_signal(
        self,
        price_series: Sequence[float],
        fast_series: Sequence[float],
        slow_series: Sequence[float],
    ) -> Signal:
        """
        Ожидаем минимум по 2 значения в каждом ряду (предыдущая+текущая свечи).
        Возвращает: 'BUY' | 'SELL' | 'HOLD'
        """
        if (
            len(price_series) < 2
            or len(fast_series) < 2
            or len(slow_series) < 2
        ):
            return "HOLD"

        p_prev, p_curr = price_series[-2], price_series[-1]
        f_prev, f_curr = fast_series[-2], fast_series[-1]
        s_prev, s_curr = slow_series[-2], slow_series[-1]

        prev_diff = f_prev - s_prev
        curr_diff = f_curr - s_curr

        # сила сигнала на текущей свече
        delta_bps = self._bps_delta(p_curr, f_curr, s_curr)
        strong_enough = delta_bps >= (self.cfg.hysteresis_bps or 0.0)

        if self._crossed_up(prev_diff, curr_diff) and strong_enough:
            return "BUY"
        if self._crossed_down(prev_diff, curr_diff) and strong_enough:
            return "SELL"
        return "HOLD"
