# src/backtest/metrics.py
from __future__ import annotations

from math import sqrt, isfinite
from typing import Iterable, Mapping, Tuple, Dict, Any, Optional, Sequence, List

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None


def _to_list(x: Iterable[float]) -> List[float]:
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


def _returns_from_equity(equity: Sequence[float]) -> List[float]:
    if len(equity) < 2:
        return []
    r = []
    prev = float(equity[0])
    for cur in equity[1:]:
        cur = float(cur)
        r.append(cur / prev - 1.0 if prev > 0 else 0.0)
        prev = cur
    return r


def _max_drawdown_pct(equity: Sequence[float]) -> Tuple[float, float, float]:
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
    trade_pnls: Optional[Iterable[float]] = None,
    n_wins: Optional[int] = None,
    n_trades: Optional[int] = None,
    exposure_pct: Optional[float] = None,
    start_equity: Optional[float] = None,
    risk_free: float = 0.0,
    bars_per_year: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Универсальный расчёт метрик по кривой equity. Расширенная сигнатура (совм. с тестами).
    """
    eq = _to_list(equity)
    n = max(0, len(eq) - 1)

    if len(eq) == 0:
        return {
            "bars": 0, "start_equity": 0.0, "final_equity": 0.0,
            "total_return_pct": 0.0, "max_drawdown_pct": 0.0,
            "sharpe": 0.0, "cagr_pct": 0.0, "calmar": 0.0,
            "profit_factor": 0.0, "bars_per_year": bars_per_year or 0.0,
            "n_trades": int(n_trades or 0), "n_wins": int(n_wins or 0),
            "exposure_pct": float(exposure_pct or 0.0),
        }

    start = float(eq[0] if start_equity is None else start_equity)
    end = float(eq[-1]) if len(eq) else 0.0

    total_return_pct = (_safe_div(end, start, 1.0) - 1.0) * 100.0
    max_dd_pct, _peak, _trough = _max_drawdown_pct(eq)

    rets = _returns_from_equity(eq)

    bpy = float(bars_per_year) if bars_per_year else 252.0
    mean_ret = (sum(rets) / len(rets)) if rets else 0.0
    if rets:
        if _np is not None:
            std_ret = float(_np.std(_np.asarray(rets, dtype=float), ddof=1)) if len(rets) > 1 else 0.0
        else:
            m = mean_ret
            var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
            std_ret = var ** 0.5
    else:
        std_ret = 0.0

    # Sharpe (без rf; параметр risk_free оставляем для совместимости)
    sharpe = 0.0
    if std_ret > 0:
        sharpe = ((mean_ret - risk_free) / std_ret) * sqrt(bpy)

    cagr_pct = 0.0
    if n > 0 and bpy > 0 and start > 0 and end > 0:
        years = n / bpy
        if years > 0:
            cagr_pct = ((end / start) ** (1.0 / years) - 1.0) * 100.0

    calmar = 0.0
    if max_dd_pct < 0:
        calmar = _safe_div(cagr_pct, abs(max_dd_pct), 0.0)

    # Profit factor — если передали по сделкам, используем его
    profit_factor = 0.0
    if trade_pnls is not None:
        gp = sum(x for x in trade_pnls if x > 0)
        gn = abs(sum(x for x in trade_pnls if x < 0))
        profit_factor = _safe_div(gp, gn, 0.0)
    else:
        gp = sum(x for x in rets if x > 0)
        gn = abs(sum(x for x in rets if x < 0))
        profit_factor = _safe_div(gp, gn, 0.0)

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
        "n_trades": int(n_trades or 0),
        "n_wins": int(n_wins or 0),
        "exposure_pct": float(exposure_pct or 0.0),
    }
    return out


__all__ = ["compute_equity_metrics"]
