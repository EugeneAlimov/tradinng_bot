# src/backtest/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

# Мы делегируем логику стратегиям из src/strategies/*
try:
    from src.strategies.ema_adx import build_trades as _ema_adx_build
except Exception:  # pragma: no cover
    _ema_adx_build = None  # type: ignore

try:
    from src.strategies.ema_adx_atr import build_trades as _ema_adx_atr_build
except Exception:  # pragma: no cover
    _ema_adx_atr_build = None  # type: ignore


@dataclass(frozen=True)
class StrategyBuilder:
    name: str
    build: Callable[[Any, Dict[str, Any]], Tuple[Any, Any]]  # (trades_df, equity_like)


def _wrap(build_fn):
    """Унифицируем сигнатуру билдеров: (df, params) -> (trades, equity)."""
    def _builder(df, params):
        return build_fn(df, params=params)
    return _builder


def get_registry_builder() -> Dict[str, StrategyBuilder]:
    """
    Возвращает доступные стратегии {name: StrategyBuilder}.
    Подключаем только то, что реально импортируется без ошибок.
    """
    builders: Dict[str, StrategyBuilder] = {}

    if _ema_adx_build is not None:
        builders["ema_adx"] = StrategyBuilder(
            name="ema_adx",
            build=_wrap(_ema_adx_build),
        )

    if _ema_adx_atr_build is not None:
        builders["ema_adx_atr"] = StrategyBuilder(
            name="ema_adx_atr",
            build=_wrap(_ema_adx_atr_build),
        )

    return builders


def _grid_product(options: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Декартово произведение словаря списков -> список dict'ов параметров."""
    keys = list(options.keys())
    if not keys:
        return []
    result: List[Dict[str, Any]] = []

    def rec(i: int, cur: Dict[str, Any]):
        if i == len(keys):
            result.append(dict(cur))
            return
        k = keys[i]
        for v in options[k]:
            cur[k] = v
            rec(i + 1, cur)

    rec(0, {})
    return result


def get_default_grid(strategy: str) -> List[Dict[str, Any]]:
    """
    Разумные сетки по умолчанию для стратегий.
    Используются в optimize/robustness/walk-forward, если пользователь сам не задал свою сетку.
    """
    s = strategy.lower()

    if s == "ema_adx":
        # То, что у тебя реально работает по логам optimize
        return _grid_product({
            "fast": [8, 12, 16],
            "slow": [21, 34, 55],
            "adx_len": [14],
            "on": [20.0, 25.0, 30.0],
            "off": [14.0, 16.0, 18.0],
            "require_di": [False, True],
        })

    if s == "ema_adx_atr":
        # Та же сетка + параметры ATR-менеджмента
        return _grid_product({
            "fast": [8, 12, 16],
            "slow": [21, 34, 55],
            "adx_len": [14],
            "on": [20.0, 25.0, 30.0],
            "off": [14.0, 16.0, 18.0],
            "require_di": [False, True],
            "atr_len": [14],
            "sl_mult": [1.0, 1.5],
            "tp_mult": [2.0, 3.0],
            "trail_mult": [0.0, 1.0],
        })

    raise ValueError(f"Unknown strategy for default grid: {strategy}")
