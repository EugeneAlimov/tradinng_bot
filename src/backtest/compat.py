# src/backtest/compat.py
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, is_dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Union

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# =========================================================
# Dataclasses / configs
# =========================================================

@dataclass(frozen=True)
class SimConfig:
    """Минимальный контракт для совместимости бэктеста."""
    pair: str
    resample: Optional[str] = None
    fee_bps: int = 10
    slip_bps: int = 2
    cooldown_bars: int = 0
    hysteresis_bps: int = 0
    qty_eur: float = 0.0


# =========================================================
# Индекс и ресэмплинг
# =========================================================

def ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """Гарантируем DatetimeIndex(UTC)."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("expected DataFrame with DatetimeIndex")
    if df.index.tz is None:
        df = df.tz_localize("UTC")
    return df


def normalize_resample_rule(rule: Optional[str]) -> Optional[str]:
    """Возвращаем нормализованную строку правила ресэмплинга либо None."""
    if rule is None:
        return None
    r = str(rule).strip()
    return r if r else None


def _ensure_ohlc_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Если в входном df нет open/high/low — заполним их копией close.
    Это нужно для совместимости с тестами, где бывает только close.
    """
    out = df.copy()
    if "close" not in out.columns:
        raise KeyError("DataFrame must contain 'close' column")
    for col in ("open", "high", "low"):
        if col not in out.columns:
            out[col] = out["close"]
    # volume опционален
    return out


def resample_ohlc(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    """
    Унифицированный ресэмплинг OHLCV. Если rule=None — возвращаем df как есть.
    Требует колонок: open/high/low/close (volume — опционально).
    """
    if rule is None:
        return ensure_datetime_index(_ensure_ohlc_columns(df))

    df = ensure_datetime_index(_ensure_ohlc_columns(df))

    agg: Dict[str, Any] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"

    out = (
        df.resample(normalize_resample_rule(rule))
        .agg(agg)
        .dropna(how="any")
    )
    return out


# =========================================================
# Данные EXMO (кэш)
# =========================================================

def fetch_exmo_candles_cached(pair: str, span: str, cache_dir: Optional[str] = None) -> pd.DataFrame:
    """
    Обёртка с отложенным импортом во избежание циклов.
    Реальную реализацию берём из src.backtest.walkforward.
    """
    from src.backtest.walkforward import fetch_exmo_candles_cached as _impl
    df = _impl(pair=pair, span=span, cache_dir=cache_dir)
    if not isinstance(df, pd.DataFrame):
        raise TypeError("fetch_exmo_candles_cached: expected pandas.DataFrame")
    return df


# =========================================================
# Сборка конфига/симуляция/метрики
# =========================================================

def build_bt_config(
        *,
        pair: str,
        resample: Optional[str],
        fee_bps: int = 10,
        slip_bps: int = 2,
        max_daily_loss_bps: int = 0,
        hysteresis_bps: int = 0,
        cooldown_bars: int = 0,
        qty_eur: float = 0.0,
        **extras: Any,
) -> Dict[str, Any]:
    """
    Универсальный dict-конфиг. Extras пробрасываются как есть.
    """
    cfg: Dict[str, Any] = {
        "pair": pair,
        "resample": normalize_resample_rule(resample),
        "fee_bps": int(fee_bps),
        "slip_bps": int(slip_bps),
        "max_daily_loss_bps": int(max_daily_loss_bps),
        "hysteresis_bps": int(hysteresis_bps),
        "cooldown_bars": int(cooldown_bars),
        "qty_eur": float(qty_eur),
    }
    cfg.update(extras or {})
    return cfg


def _coerce_py(val: Any) -> Any:
    """Нормализация числовых типов (numpy/Decimal -> python)."""
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.integer,)):
        return int(val)
    return val


def normalize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Мягкая нормализация метрик к «обычным» питоновским типам."""
    out: Dict[str, Any] = {}
    for k, v in (metrics or {}).items():
        if is_dataclass(v):
            v = asdict(v)
        if isinstance(v, dict):
            out[k] = {kk: _coerce_py(vv) for kk, vv in v.items()}
        else:
            out[k] = _coerce_py(v)
    return out


def simulate_on_df(df: pd.DataFrame, bt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Точка вызова симулятора: пытаемся взять «боевую» реализацию, иначе фолбэк.
    """
    df = ensure_datetime_index(df)
    try:
        # если у тебя есть реальный движок — экспортируй simulate_on_df отсюда
        from src.backtest.vectorized_bt import simulate_on_df as _impl  # type: ignore
        return _impl(df, bt_cfg)
    except Exception:
        pass

    bars = int(len(df))
    return {
        "bars": bars,
        "bars_per_year": 0.0,
        "trades": 0,
        "total_return_pct": 0.0,
        "winrate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe": 0.0,
        "profit_factor": 0.0,
        "avg_trade_eur": 0.0,
        "exposure_pct": 0.0,
        "start_equity_eur": float(bt_cfg.get("qty_eur", 0.0) or 0.0),
        "final_equity_eur": float(bt_cfg.get("qty_eur", 0.0) or 0.0),
    }


# =========================================================
# Совместимая обёртка бэктеста
# =========================================================

def run_backtest_compat(
        df: pd.DataFrame,
        *,
        config: Union[SimConfig, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Унифицированный раннер бэктеста, который ожидают разные части проекта.
    """
    bt_cfg = asdict(config) if is_dataclass(config) else dict(config)
    rr = normalize_resample_rule(bt_cfg.get("resample"))
    df_rs = resample_ohlc(df, rr)
    metrics = simulate_on_df(df_rs, bt_cfg)
    return normalize_metrics(metrics)


__all__ = [
    # dataclass/config
    "SimConfig",
    # индексы/ресэмплинг
    "ensure_datetime_index",
    "normalize_resample_rule",
    "resample_ohlc",
    # данные
    "fetch_exmo_candles_cached",
    # симуляция/метрики/раннер
    "build_bt_config",
    "simulate_on_df",
    "normalize_metrics",
    "run_backtest_compat",
]
