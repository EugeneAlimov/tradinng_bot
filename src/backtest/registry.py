# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple, Optional

import numpy as np
import pandas as pd


# Тип билда стратегии
BuildFn = Callable[[pd.DataFrame, Dict[str, Any]],
                   Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]]


@dataclass
class StrategyBuilder:
    name: str
    build: BuildFn
    default_grid: Optional[Callable[[], List[Dict[str, Any]]]] = None


# Локальный реестр
_builders: Dict[str, StrategyBuilder] = {}


def _safe_register(mod_path: str, name: Optional[str] = None,
                   grid_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None) -> None:
    """
    Импортирует модуль стратегии и регистрирует её,
    но не падает, если модуль отсутствует.
    """
    try:
        module = __import__(mod_path, fromlist=["*"])
        build_fn: BuildFn = getattr(module, "build")
        strat_name: str = getattr(module, "name", name or mod_path.rsplit(".", 1)[-1])
        _builders[strat_name] = StrategyBuilder(strat_name, build_fn, grid_fn)
    except Exception:  # noqa: BLE001 – реестр не должен падать от частных ошибок
        pass


# === default grids ==============================================================

def _grid_ema_adx() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for fast in (8, 12, 16):
        for slow in (21, 34, 55):
            for on in (20.0, 25.0, 30.0):
                for off in (14.0, 16.0, 18.0):
                    for require_di in (False, True):
                        out.append(
                            {"fast": fast, "slow": slow, "adx_len": 14,
                             "on": on, "off": off, "require_di": require_di}
                        )
    return out


def _grid_macd() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for fast in (8, 12):
        for slow in (21, 26):
            for signal in (9, 12):
                out.append({"fast": fast, "slow": slow, "signal": signal})
    return out


def _grid_donchian() -> List[Dict[str, Any]]:
    return [{"ch_len": n} for n in (20, 30, 55)]


# === наполнение реестра =========================================================

def _init_registry() -> None:
    # базовые стратегии (есть в проекте)
    _safe_register("src.strategies.ema_adx", name="ema_adx", grid_fn=_grid_ema_adx)
    _safe_register("src.strategies.ema_adx_atr", name="ema_adx_atr")  # билдер уже есть
    _safe_register("src.strategies.macd_cross", name="macd_cross", grid_fn=_grid_macd)
    _safe_register("src.strategies.donchian", name="donchian", grid_fn=_grid_donchian)

    # подключим, если присутствуют в репо
    _safe_register("src.strategies.rsi2", name="rsi2")
    _safe_register("src.strategies.bbands", name="bb_breakout")


# инициализируем один раз при импорте
_init_registry()


# === публичный API ==============================================================

def get_registry_builder() -> Dict[str, StrategyBuilder]:
    """
    Вернёт карту: strategy_name -> StrategyBuilder(build, default_grid)
    """
    return dict(_builders)


def get_default_grid(strategy: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]] | List[Dict[str, Any]]:
    """
    Если strategy is None -> вернёт карту strategy -> grid.
    Если указано имя стратегии -> вернёт список её сетки (или [] если не найдено).
    """
    grid_map: Dict[str, List[Dict[str, Any]]] = {}
    for k, b in _builders.items():
        if b.default_grid is not None:
            try:
                grid_map[k] = list(b.default_grid())
            except Exception:
                grid_map[k] = []
        else:
            grid_map[k] = []

    if strategy is None:
        return grid_map
    return grid_map.get(strategy, [])
