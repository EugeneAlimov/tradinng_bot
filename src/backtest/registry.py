# src/backtest/registry.py
from __future__ import annotations
from typing import Any, Dict, List, Callable

# подключаем ваши реализации ema_adx / ema_adx_atr, если они в проекте
_builders: Dict[str, Callable[..., Any]] = {}

try:
    from src.backtest.strategies.ema_adx import build as _ema_adx_build  # type: ignore
    _builders["ema_adx"] = _ema_adx_build
except Exception:
    pass

try:
    from src.backtest.strategies.ema_adx_atr import build as _ema_adx_atr_build  # type: ignore
    _builders["ema_adx_atr"] = _ema_adx_atr_build
except Exception:
    pass

# добавленные стратегии
from src.backtest.strategies.rsi2 import build as _rsi2_build
from src.backtest.strategies.bbands import build as _bb_build

_builders["rsi2"] = _rsi2_build
_builders["bb_breakout"] = _bb_build


def get_registry_builder() -> Dict[str, Any]:
    """Вернуть карту: strategy_name -> builder(df, params) -> (trades, pnls)."""
    return dict(_builders)


def get_default_grid() -> Dict[str, List[Dict[str, Any]]]:
    """Сетки по умолчанию (скромные, но рабочие)."""
    out: Dict[str, List[Dict[str, Any]]] = {}

    if "ema_adx" in _builders:
        out["ema_adx"] = [
            {"fast": 10, "slow": 26, "adx_len": 14, "on": 22.0, "off": 16.0, "require_di": True},
            {"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": False},
            {"fast": 14, "slow": 30, "adx_len": 14, "on": 22.0, "off": 18.0, "require_di": True},
        ]
    if "ema_adx_atr" in _builders:
        out["ema_adx_atr"] = [
            {"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": False, "atr_len": 14},
            {"fast": 10, "slow": 26, "adx_len": 14, "on": 22.0, "off": 16.0, "require_di": True, "atr_len": 14},
        ]

    out["rsi2"] = [
        {"rsi_len": 2, "buy_below": 10.0, "sell_above": 70.0},
        {"rsi_len": 2, "buy_below": 10.0, "sell_above": 90.0},
        {"rsi_len": 3, "buy_below": 15.0, "sell_above": 85.0},
    ]
    out["bb_breakout"] = [
        {"bb_len": 20, "bb_k": 2.0},
        {"bb_len": 20, "bb_k": 2.5},
        {"bb_len": 30, "bb_k": 2.0},
    ]

    return out
