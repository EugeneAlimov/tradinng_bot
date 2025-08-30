# src/strategies/registry.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Protocol, cast

import numpy as np
import pandas as pd

from src.strategies import ema_adx, ema_adx_atr


class BuildTrades(Protocol):
    """
    Унифицированная сигнатура стратегий:
    принимает DataFrame и произвольные именованные параметры,
    возвращает (trades, pnls).
    """
    def __call__(self, df: pd.DataFrame, /, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]: ...


_REGISTRY: Dict[str, BuildTrades] = {
    "ema_adx": cast(BuildTrades, ema_adx.build_trades),
    "ema_adx_atr": cast(BuildTrades, ema_adx_atr.build_trades),
}


def get_strategy(name: str) -> BuildTrades:
    key = str(name).strip().lower()
    if key not in _REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Available: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[key]


def list_strategies() -> Dict[str, BuildTrades]:
    return dict(_REGISTRY)
