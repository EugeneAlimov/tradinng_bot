# src/backtest/compat.py
from __future__ import annotations

"""
Совместимый слой для backtest/walkforward.

Задача модуля — предоставить стабильные ИМЕНА функций:
  - fetch_exmo_candles_cached
  - resample_ohlc
  - simulate_on_df
  - normalize_resample_rule

Фактическая реализация делегируется в существующие приватные хелперы sweep.py,
чтобы не дублировать код и не ломать текущую логику.
"""

from typing import Any, Dict, Optional

# ленивые импорты, чтобы избежать циклических зависимостей
def _sweep() -> Any:
    from . import sweep  # type: ignore
    return sweep


# ----- Public API expected by walkforward.py -----

def fetch_exmo_candles_cached(pair: str, span: str, cache_dir: Optional[str] = None) -> Any:
    s = _sweep()
    # в sweep.py функции именованы с "_", реэкспортируем под публичными именами
    return s._fetch_exmo_candles_cached(pair=pair, span=span, cache_dir=cache_dir)


def resample_ohlc(df: Any, rule: str) -> Any:
    s = _sweep()
    return s._resample_ohlc(df, rule)


def simulate_on_df(df: Any, bt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    s = _sweep()
    return s._simulate_on_df(df, bt_cfg)


def normalize_resample_rule(rule: str) -> str:
    s = _sweep()
    return s._normalize_resample_rule(rule)
