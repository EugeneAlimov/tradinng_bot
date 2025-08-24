# src/backtest/metrics.py
from __future__ import annotations

import math
import statistics as stats
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, Dict

import numpy as np
import pandas as pd


# ---------- Timeframe helpers ----------

_MINUTES_PER_YEAR = 365 * 24 * 60

def parse_resample_to_minutes(resample: str) -> int:
    """
    '5m' -> 5, '15m' -> 15, '1h' -> 60, '4h' -> 240, '1d' -> 1440.
    Бросает ValueError на неизвестном формате.
    """
    s = resample.strip().lower()
    if s.endswith('m'):
        return int(s[:-1])
    if s.endswith('h'):
        return int(s[:-1]) * 60
    if s.endswith('d'):
        return int(s[:-1]) * 1440
    raise ValueError(f"Unsupported resample string: '{resample}'")

def periods_per_year(resample: str) -> int:
    m = parse_resample_to_minutes(resample)
    # целое число баров в «рыночный год» (календарный для crypto ок)
    return int(round(_MINUTES_PER_YEAR / m))


# ---------- Drawdowns & returns ----------

def equity_to_returns(equity: pd.Series) -> pd.Series:
    """Преобразует капитал в бар-to-бар доходности (простые, не лог)."""
    r = equity.pct_change().fillna(0.0)
    # ограничим выбросы (защита от деления на ноль/битых баров)
    return r.replace([np.inf, -np.inf], 0.0).clip(lower=-1.0, upper=+1.0)

def max_drawdown(equity: pd.Series) -> float:
    """Возвращает maxDD как отрицательный процент, например -0.25 для -25%."""
    if equity.empty:
        return 0.0
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    return float(dd.min())  # отрицательное число

def profit_factor_from_pnls(pnls: Iterable[float]) -> float:
    pos = 0.0
    neg = 0.0
    for v in pnls:
        if v >= 0:
            pos += v
        else:
            neg += -v
    if neg == 0:
        return float('inf') if pos > 0 else 1.0
    return pos / neg


# ---------- Metric bundles ----------

@dataclass
class MetricConfig:
    resample: str = "5m"        # для annualize
    risk_free_rate: float = 0.0 # в долях годовых (0.02 = 2% годовых)


def _annualize_sharpe(per_bar_sharpe: float, resample: str) -> float:
    k = math.sqrt(periods_per_year(resample))
    return per_bar_sharpe * k


def compute_equity_metrics(
    equity: pd.Series,
    *,
    resample: str,
    risk_free_rate: float = 0.0,
    bars_per_year_override: Optional[int] = None,
    returns_cache: Optional[pd.Series] = None,
) -> Dict[str, float]:
    """
    Считает набор метрик на основе equity (индекс — таймстемпы или бары).
    Возвращает dict со значениями в ДОЛЯХ (0.12 = 12%), кроме 'bars', 'trades' и т.п.

    Важно: CAGR считается по фактическому времени между первым и последним индексом,
    если индекс — DatetimeIndex. Иначе — по количеству баров и resample.
    """
    if equity.empty:
        return {
            "bars": 0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0,
            "final_equity_eur": float('nan'), "start_equity_eur": float('nan'),
            "profit_factor": float('nan'), "sharpe": float('nan'),
            "cagr_pct": 0.0, "calmar": float('nan'),
        }

    eq = equity.astype(float)
    start_equity = float(eq.iloc[0])
    final_equity = float(eq.iloc[-1])
    bars = int(eq.size)

    total_return = (final_equity / start_equity) - 1.0
    dd = max_drawdown(eq)  # отрицательное число

    # пер-бар доходности
    rets = returns_cache if returns_cache is not None else equity_to_returns(eq)

    # Sharpe: средняя избыточная per-bar доходность / std, затем annualize
    rf_per_bar = risk_free_rate / (bars_per_year_override or periods_per_year(resample))
    excess = rets - rf_per_bar
    vol = float(np.std(excess, ddof=1)) if bars > 1 else 0.0
    per_bar_sharpe = float(np.mean(excess)) / vol if vol > 1e-12 else 0.0
    sharpe_ann = _annualize_sharpe(per_bar_sharpe, resample)

    # CAGR — строго по времени, если у equity есть временной индекс
    if isinstance(eq.index, pd.DatetimeIndex) and eq.index[0] != eq.index[-1]:
        years = (eq.index[-1] - eq.index[0]).total_seconds() / (365 * 24 * 3600)
        years = max(years, 1e-9)
    else:
        # fallback: по барам
        ppy = bars_per_year_override or periods_per_year(resample)
        years = bars / ppy
    cagr = (final_equity / start_equity) ** (1.0 / years) - 1.0

    calmar = (cagr / abs(dd)) if dd < 0 else float('inf')

    return {
        "bars": bars,
        "total_return_pct": float(total_return),
        "max_drawdown_pct": float(dd),
        "final_equity_eur": final_equity,
        "start_equity_eur": start_equity,
        "sharpe": float(sharpe_ann),
        "cagr_pct": float(cagr),
        "calmar": float(calmar),
    }


def aggregate_oos_folds(
    folds: Iterable[Tuple[pd.Series, pd.Series]],
    *,
    resample: str,
    risk_free_rate: float = 0.0,
) -> Dict[str, float]:
    """
    Агрегирует OOS фолды корректно:
      - _mean: среднее по фолдам
      - _agg: «склеенный» по времени эквити: берем первый equity первого фолда и последний equity последнего фолда,
              а также объединяем DatetimeIndex для времени → корректный CAGR/DD/Calmar.
    folds: итерируемый набор (equity_series, pnl_series) для каждого фолда.
    """
    metrics_per_fold = []
    equities_for_concat = []

    for eq, _pnl in folds:
        m = compute_equity_metrics(eq, resample=resample, risk_free_rate=risk_free_rate)
        metrics_per_fold.append(m)
        equities_for_concat.append(eq)

    # средние
    def mean_of(key: str) -> float:
        vals = [m[key] for m in metrics_per_fold if not pd.isna(m[key])]
        return float(np.mean(vals)) if vals else float('nan')

    # агрегированный по времени
    if equities_for_concat:
        eq_concat = pd.concat(equities_for_concat).sort_index()
        agg = compute_equity_metrics(eq_concat, resample=resample, risk_free_rate=risk_free_rate)
    else:
        agg = {k: float('nan') for k in ("total_return_pct", "max_drawdown_pct", "cagr_pct", "calmar")}

    return {
        "oos_total_return_pct_mean": mean_of("total_return_pct"),
        "oos_max_drawdown_pct_mean": mean_of("max_drawdown_pct"),
        "oos_sharpe_mean": mean_of("sharpe"),
        "oos_cagr_pct_mean": mean_of("cagr_pct"),
        "oos_calmar_mean": mean_of("calmar"),
        "oos_total_return_pct_agg": float(agg["total_return_pct"]),
        "oos_max_drawdown_pct_agg": float(agg["max_drawdown_pct"]),
        "oos_cagr_pct_agg": float(agg["cagr_pct"]),
        "oos_calmar_agg": float(agg["calmar"]),
    }
