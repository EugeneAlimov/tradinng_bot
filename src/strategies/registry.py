from __future__ import annotations
from typing import Any, Dict, List, Tuple, Protocol, cast
from types import SimpleNamespace
import numpy as np
import pandas as pd

from src.strategies import ema_adx, ema_adx_atr


class BuildTrades(Protocol):
    def __call__(self, df: pd.DataFrame, /, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]: ...


_REGISTRY: Dict[str, Any] = {
    "ema_adx_atr": SimpleNamespace(
        generate_signals=ema_adx_atr.generate_signals,
        build_trades=ema_adx_atr.build_trades,
        default_grid=ema_adx_atr.default_grid,
    ),
    "ema_adx": cast(BuildTrades, ema_adx.build_trades),
}


def get_strategy(name: str):
    return _REGISTRY[name]


def get(name: str):  # алиас для тестов
    return get_strategy(name)


def list_strategies() -> Dict[str, Any]:
    return dict(_REGISTRY)
