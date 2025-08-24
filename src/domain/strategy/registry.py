# src/domain/strategy/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple, Any

SignalFn = Callable[[List[float]], List[int]]
StatusFn = Callable[[List[float]], Tuple[str, int]]

@dataclass(frozen=True)
class StrategyDef:
    name: str
    generate_signals: Callable[..., List[int]]  # (prices, **params) -> signals
    status: Callable[..., Tuple[str, int]]      # (prices, **params) -> (text, state)
    defaults: Dict[str, Any]                    # дефолтные параметры

_REGISTRY: Dict[str, StrategyDef] = {}

def register(defn: StrategyDef) -> None:
    _REGISTRY[defn.name.lower()] = defn

def get(name: str) -> StrategyDef:
    key = (name or "").lower()
    if key not in _REGISTRY:
        raise KeyError(f"Unknown strategy: {name}. Available: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[key]

def names() -> List[str]:
    return sorted(_REGISTRY.keys())

# ---- автоподхват стратегий ----
from . import sma_crossover      # noqa: E402,F401
from . import rsi2_meanrev       # noqa: E402,F401
from . import donchian_breakout  # noqa: E402,F401
from . import ema_crossover      # noqa: E402,F401
from . import macd_cross         # noqa: E402,F401
from . import bbands_meanrev     # noqa: E402,F401
from . import roc_momentum       # noqa: E402,F401
