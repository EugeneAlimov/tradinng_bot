# src/backtest/registry.py

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

BuildTrades = Tuple[List[Dict[str, Any]], np.ndarray]


@dataclass(frozen=True)
class Strategy:
    key: str
    build: Callable[..., Any]          # build(df, Params, **kwargs) -> (trades, pnl) | (trades, pnl, extra)
    params_type: type                  # dataclass Params
    default_grid: Optional[Callable[[], Dict[str, List[Any]]]] = None


_REGISTRY: Dict[str, Strategy] = {}


def _register(key: str, build: Callable[..., Any], params_type: type,
              default_grid: Optional[Callable[[], Dict[str, List[Any]]]] = None) -> None:
    _REGISTRY[key] = Strategy(key=key, build=build, params_type=params_type, default_grid=default_grid)


def _try_register(module_path: str, key: str) -> None:
    """
    Унифицированная загрузка стратегий из src.strategies.*
    Ожидаем, что в модуле есть: build, Params (dataclass), default_grid (опционально).
    """
    try:
        mod = __import__(module_path, fromlist=["build", "Params", "default_grid"])
        build = getattr(mod, "build")
        params_type = getattr(mod, "Params")
        default_grid = getattr(mod, "default_grid", None)
        _register(key, build, params_type, default_grid)
    except Exception:
        # Тихо пропускаем — стратегия необязательная.
        pass


# --- регистрируем доступные стратегии из src/strategies/* ---
_try_register("src.strategies.ema_adx", "ema_adx")
_try_register("src.strategies.ema_adx_atr", "ema_adx_atr")
_try_register("src.strategies.rsi2", "rsi2")
_try_register("src.strategies.bbands", "bb_breakout")
_try_register("src.strategies.donchian", "donchian")
_try_register("src.strategies.macd_cross", "macd_cross")


def _expand_grid(spec: Dict[str, List[Any]] | None) -> List[Dict[str, Any]]:
    """
    Преобразует сетку вида {"a":[1,2], "b":[10,20]} в список комбинаций:
    [{"a":1,"b":10}, {"a":1,"b":20}, {"a":2,"b":10}, {"a":2,"b":20}]
    """
    if not spec:
        return [{}]
    keys = list(spec.keys())
    values_lists = [v if isinstance(v, (list, tuple)) else [v] for v in (spec[k] for k in keys)]
    combos: List[Dict[str, Any]] = []
    for vals in product(*values_lists):
        combos.append(dict(zip(keys, vals)))
    return combos


def get_registry_builder() -> Dict[str, Callable[[pd.DataFrame, Dict[str, Any]], BuildTrades]]:
    """
    Возвращает mapping: strategy_key -> builder(df, params_dict) -> (trades, pnl)
    Унифицируем вызов всех стратегий: dict -> dataclass Params.
    """
    out: Dict[str, Callable[[pd.DataFrame, Dict[str, Any]], BuildTrades]] = {}

    for s in _REGISTRY.values():
        def make_builder(build_fn: Callable[..., Any], P: type) -> Callable[[pd.DataFrame, Dict[str, Any]], BuildTrades]:
            def builder(df: pd.DataFrame, params: Dict[str, Any]) -> BuildTrades:
                p = P(**params)  # преобразуем dict в dataclass Params
                result = build_fn(df, p)  # допускаем (trades, pnl) или (trades, pnl, extra)
                if not isinstance(result, tuple) or len(result) < 2:
                    raise RuntimeError(f"Strategy '{s.key}' build() must return at least (trades, pnl)")
                trades, pnl = result[0], result[1]
                return trades, pnl
            return builder

        out[s.key] = make_builder(s.build, s.params_type)

    return out


def get_default_grid() -> Dict[str, List[Dict[str, Any]]]:
    """
    Возвращает mapping: strategy_key -> list[params_dict]
    """
    grids: Dict[str, List[Dict[str, Any]]] = {}
    for s in _REGISTRY.values():
        if s.default_grid:
            try:
                grids[s.key] = _expand_grid(s.default_grid())
            except Exception:
                # Если дефолтная сетка сломана — пропустим стратегию
                continue
    return grids
