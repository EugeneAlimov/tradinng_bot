# src/application/research/strategies.py
"""
Совместимость после объединения логики:
старые импорты вида
    from src.application.research.strategies import strat_registry
продолжают работать.

Мы прозрачно реэкспортируем актуальный реестр стратегий.
"""

from __future__ import annotations

_strat_registry = None

# Вариант 1: актуальный путь (domain/strategy/registry.py)
try:
    from src.domain.strategy.registry import strat_registry as _sr  # type: ignore

    _strat_registry = _sr
except Exception:
    pass

# Вариант 2: если когда-либо вернётся старое расположение — тоже поддержим
if _strat_registry is None:
    try:
        from src.application.research.strategies import strat_registry as _sr  # type: ignore

        _strat_registry = _sr  # type: ignore[assignment]
    except Exception:
        pass

if _strat_registry is None:
    class _DummyRegistry:
        def __getattr__(self, name):
            raise ImportError(
                "Cannot locate 'strat_registry'. Ensure it exists (e.g., "
                "src/domain/strategy/registry.py) and is importable."
            )


    strat_registry = _DummyRegistry()  # type: ignore
else:
    strat_registry = _strat_registry  # type: ignore

__all__ = ["strat_registry"]
