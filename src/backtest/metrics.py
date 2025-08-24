# src/backtest/metrics.py
from __future__ import annotations

from math import sqrt, isfinite
from typing import Iterable, Mapping, Tuple, Dict, Any, Optional, Sequence

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None


def _to_list(x: Iterable[float]) -> list[float]:
    if _np is not None and hasattr(x, "__array__"):
        return _np.asarray(x, dtype=float).tolist()
    return [float(v) for v in x]


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        if b == 0:
            return default
        v = a / b
        return v if isfinite(v) else default
    except Exception:
        return default


def _returns_from_equity(equity: Sequence[float]) -> list[float]:
    if len(equity) < 2:
        return []
    r = []
    prev = float(equity[0])
    for cur in equity[1:]:
        cur = float(cur)
        if prev > 0:
            r.append(cur / prev - 1.0)
        else:
            r.append(0.0)
        prev = cur
    return r


def _max_drawdown_pct(equity: Sequence[float]) -> Tuple[float, float, float]:
    """
    Возвращает: (max_drawdown_pct, peak, trough)
    """
    peak = -1e18
    max_dd = 0.0
    peak_val = 0.0
    trough_val = 0.0
    for v in equity:
        v = float(v)
        if v > peak:
            peak = v
            peak_val = v
            trough_val = v
        dd = _safe_div(v - peak, peak, 0.0)  # отрицательное
        if dd < max_dd:
            max_dd = dd
            trough_val = v
    return (max_dd * 100.0, peak_val, trough_val)


def compute_equity_metrics(
    equity: Iterable[float],
    bars_per_year: Optional[float] = None,
    start_equity: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Универсальный расчёт метрик по кривой equity.

    Возвращает словарь с ключами:
      - bars
      - start_equity
      - final_equity
      - total_return_pct
      - max_drawdown_pct
      - sharpe
      - cagr_pct
      - calmar
      - profit_factor
      - bars_per_year

    Параметры:
      equity: последовательность значений капитала по барам (>=2 значения)
      bars_per_year: годовая частота баров (для годовых метрик). Если None, пытаемся оценить.
      start_equity: если не задан — equity[0]
    """
    eq = _to_list(equity)
    n = max(0, len(eq) - 1)

    if len(eq) == 0:
        return {
            "bars": 0,
            "start_equity": 0.0,
            "final_equity": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "cagr_pct": 0.0,
            "calmar": 0.0,
            "profit_factor": 0.0,
            "bars_per_year": bars_per_year or 0.0,
        }

    start = float(eq[0] if start_equity is None else start_equity)
    end = float(eq[-1]) if len(eq) else 0.0

    total_return_pct = _safe_div(end, start, 0.0) - 1.0
    total_return_pct *= 100.0

    max_dd_pct, _peak, _trough = _max_drawdown_pct(eq)

    rets = _returns_from_equity(eq)

    # Sharpe по bar-ретёрнам (без rf), годовой через sqrt(bars_per_year)
    mean_ret = float(sum(rets) / len(rets)) if rets else 0.0
    if rets:
        if _np is not None:
            std_ret = float(_np.std(_np.asarray(rets, dtype=float), ddof=1)) if len(rets) > 1 else 0.0
        else:
            # несмещённая оценка
            m = mean_ret
            var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
            std_ret = var ** 0.5
    else:
        std_ret = 0.0

    # если частота баров не задана — примем условно 252 (торг. дни) как «разумный» дефолт
    bpy = float(bars_per_year) if bars_per_year else 252.0
    sharpe = 0.0
    if std_ret > 0:
        sharpe = (mean_ret / std_ret) * sqrt(bpy)

    # CAGR из начального и конечного капитала
    cagr_pct = 0.0
    if n > 0 and bpy > 0:
        years = n / bpy
        if years > 0 and start > 0 and end > 0:
            cagr = (end / start) ** (1.0 / years) - 1.0
            cagr_pct = cagr * 100.0

    # Calmar: CAGR / |MaxDD|
    calmar = 0.0
    if max_dd_pct < 0:
        calmar = _safe_div(cagr_pct, abs(max_dd_pct), 0.0)

    # Profit Factor (на основе bar-ретёрнов, т.к. сделки неизвестны)
    gross_pos = sum(x for x in rets if x > 0)
    gross_neg = sum(x for x in rets if x < 0)
    profit_factor = _safe_div(gross_pos, abs(gross_neg), 0.0)

    out = {
        "bars": n,
        "start_equity": start,
        "final_equity": end,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_dd_pct,
        "sharpe": sharpe,
        "cagr_pct": cagr_pct,
        "calmar": calmar,
        "profit_factor": profit_factor,
        "bars_per_year": bpy,
    }
    return out


__all__ = ["compute_equity_metrics"]
