# src/backtest/compat.py
from __future__ import annotations

"""
Совместимый слой для backtest/walkforward/sweep.

Экспортирует стабильные имена, которые ожидают другие модули:
  - fetch_exmo_candles_cached
  - resample_ohlc
  - simulate_on_df
  - normalize_resample_rule
  - build_bt_config
  - SimConfig

Реализацию базовых операций делегируем в приватные хелперы из sweep.py,
чтобы не дублировать логику.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


def _sweep() -> Any:
    # ленивый импорт во избежание циклических зависимостей
    from . import sweep  # type: ignore
    return sweep


# ---------- Публичные фасады к хелперам из sweep.py ----------

def fetch_exmo_candles_cached(pair: str, span: str, cache_dir: Optional[str] = None) -> Any:
    s = _sweep()
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


# ---------- Конфиг симуляции и сборка bt-конфига ----------

@dataclass(frozen=True)
class SimConfig:
    """
    Унифицированный конфиг для симуляции/бэктеста.
    Список полей покрывает потребности sweep/optimize/walkforward.
    """
    pair: str
    resample: str = "5m"
    fee_bps: int = 10
    slip_bps: int = 2
    max_daily_loss_bps: int = 0
    fast: int = 10
    slow: int = 20
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    qty_eur: float = 100.0

    def to_bt_config(self) -> Dict[str, Any]:
        return build_bt_config(**asdict(self))


def build_bt_config(
    *,
    pair: str,
    resample: str = "5m",
    fee_bps: int = 10,
    slip_bps: int = 2,
    max_daily_loss_bps: int = 0,
    fast: int = 10,
    slow: int = 20,
    hysteresis_bps: int = 0,
    cooldown_bars: int = 0,
    qty_eur: float = 100.0,
    **extras: Any,
) -> Dict[str, Any]:
    """
    Собирает dict-конфиг бэктеста в формате, который ожидают наши симуляторы.
    Любые дополнительные поля из **extras пролетают сквозь — это безопасно.
    """
    # Нормализуем правило ресемплинга через общий хелпер (поддержка '5m'/'5T' и т.п.)
    rule = normalize_resample_rule(resample)

    bt_cfg: Dict[str, Any] = {
        "pair": pair,
        "resample": rule,
        "fee_bps": int(fee_bps),
        "slip_bps": int(slip_bps),
        "max_daily_loss_bps": int(max_daily_loss_bps),
        "fast": int(fast),
        "slow": int(slow),
        "hysteresis_bps": int(hysteresis_bps),
        "cooldown_bars": int(cooldown_bars),
        "qty_eur": float(qty_eur),
    }

    if extras:
        bt_cfg.update(extras)

    return bt_cfg


__all__ = [
    "fetch_exmo_candles_cached",
    "resample_ohlc",
    "simulate_on_df",
    "normalize_resample_rule",
    "build_bt_config",
    "SimConfig",
]
