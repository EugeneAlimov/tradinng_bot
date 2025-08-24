from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------
# Helpers
# -----------------------------

def _nan_to_none(x):
    if isinstance(x, (float, np.floating)) and (math.isnan(x) or np.isinf(x)):
        return None
    return x


def _pct(v: float) -> float:
    """
    Make sure percentage-like values are floats in [-inf, +inf] range,
    not NaN, but keep sign. NaN/inf -> 0.0 for safety in aggregation.
    """
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return 0.0
    return float(v)


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if b == 0 or math.isnan(b) or math.isinf(b):
        return default
    return a / b


def bars_per_year(resample: str) -> float:
    """
    Approximate bars/year for a pandas offset alias.
    Works for 'm' (minute), 'h' (hour), 'd', etc.
    """
    resample = resample.strip().lower()
    minutes_in_year = 365 * 24 * 60
    if resample.endswith("m"):
        step = int(resample[:-1])
        return minutes_in_year / step
    if resample.endswith("h"):
        step = int(resample[:-1])
        return minutes_in_year / (step * 60)
    if resample.endswith("d"):
        step = int(resample[:-1]) if len(resample) > 1 else 1
        return 365 / step
    # fallback: treat as 5m if unknown
    return minutes_in_year / 5


def max_drawdown_pct(equity: pd.Series) -> float:
    rolling_max = equity.cummax()
    dd = equity / rolling_max - 1.0
    return float(dd.min())


def sharpe_ratio(returns: pd.Series, eps: float = 1e-12) -> float:
    if returns.size == 0:
        return 0.0
    mean = float(returns.mean())
    std = float(returns.std(ddof=0))
    if std < eps:
        return 0.0
    # daily-ish Sharpe in "per-bar" terms; the caller may scale it if needed
    return mean / std


def profit_factor(gross_profit: float, gross_loss: float, eps: float = 1e-12) -> float:
    loss = abs(gross_loss)
    if loss < eps:
        return float("inf") if gross_profit > 0 else 0.0
    return _safe_div(gross_profit, loss, default=0.0)


def calmar(cagr_pct: float, max_dd_pct: float, eps: float = 1e-12) -> float:
    dd = abs(max_dd_pct)
    if dd < eps:
        # protect from insane blow-ups; treat as very small drawdown
        dd = 1e-4
    return _safe_div(cagr_pct, dd, default=0.0)


def cagr_from_equity(equity: pd.Series, bars_in_period: int, resample: str, eps: float = 1e-9) -> float:
    if equity.size < 2:
        return 0.0
    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start <= eps:
        return 0.0
    years = bars_in_period / max(bars_per_year(resample), eps)
    if years <= eps:
        return 0.0
    return (end / start) ** (1.0 / years) - 1.0


# -----------------------------
# Walk-forward aggregation
# -----------------------------

@dataclass
class OOSAgg:
    """Aggregated out-of-sample metrics across folds."""
    mean: Dict[str, float]
    aggregate: Dict[str, float]

    def as_dict(self) -> Dict[str, Dict[str, float]]:
        return {"mean": self.mean, "aggregate": self.aggregate}


def aggregate_oos_folds(
    folds: Iterable[Mapping[str, float]],
    *,
    resample: str,
    agg_equity: Optional[pd.Series] = None,
) -> OOSAgg:
    """
    folds: iterable of per-fold dicts with keys like:
        'oos_total_return_pct', 'oos_max_drawdown_pct',
        'oos_profit_factor', 'oos_winrate_pct', 'oos_sharpe',
        'oos_cagr_pct', 'oos_calmar'
    resample: pandas offset alias ('5m', '1h', '1d', ...)
    agg_equity: optional concatenated equity for aggregate metrics
    """
    df = pd.DataFrame(list(folds))
    if df.empty:
        return OOSAgg(mean={}, aggregate={})

    # Sanitize crazy values (legacy code sometimes produced unrealistic ones)
    def cap(series: pd.Series, name: str) -> pd.Series:
        s = series.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if name.endswith("_pct"):
            # keep in sensible absolute bounds
            s = s.clip(-5.0, 5.0)  # -500%..+500% per fold
        elif name.endswith("_cagr") or name.endswith("_cagr_pct"):
            s = s.clip(-1.0, 5.0)
        elif name.endswith("_calmar"):
            s = s.clip(0.0, 50.0)  # calmar up to 50 for fold means
        return s

    cols = {
        "oos_total_return_pct": "oos_total_return_pct",
        "oos_max_drawdown_pct": "oos_max_drawdown_pct",
        "oos_profit_factor": "oos_profit_factor",
        "oos_winrate_pct": "oos_winrate_pct",
        "oos_sharpe": "oos_sharpe",
        "oos_cagr_pct": "oos_cagr_pct",
        "oos_calmar": "oos_calmar",
    }

    mean: Dict[str, float] = {}
    for k, col in cols.items():
        if col in df.columns:
            s = cap(df[col], col)
            if col == "oos_profit_factor":
                # geometric-ish mean would be better; keep arithmetic for simplicity
                mean[k + "_mean"] = float(s.replace(np.inf, np.nan).fillna(10.0).mean())
            else:
                mean[k + "_mean"] = float(s.mean())
        else:
            mean[k + "_mean"] = 0.0

    aggregate: Dict[str, float] = {}
    if agg_equity is not None and isinstance(agg_equity, pd.Series) and agg_equity.size > 1:
        # Aggregate metrics: compute from concatenated equity (more faithful)
        total_ret = float(agg_equity.iloc[-1] / agg_equity.iloc[0] - 1.0)
        mdd = max_drawdown_pct(agg_equity)
        # per-bar returns for Sharpe
        rets = agg_equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        sr = sharpe_ratio(rets)
        cagr = cagr_from_equity(agg_equity, bars_in_period=agg_equity.size, resample=resample)
        cmr = calmar(cagr, mdd)
        aggregate.update(
            oos_total_return_pct_agg=total_ret,
            oos_max_drawdown_pct_agg=mdd,
            oos_sharpe_agg=sr,
            oos_cagr_pct_agg=cagr,
            oos_calmar_agg=cmr,
        )
    return OOSAgg(mean=mean, aggregate=aggregate)


# -----------------------------
# Pretty-print helpers
# -----------------------------

def format_metrics_row(row: Mapping[str, float]) -> Dict[str, float]:
    """
    Round & clean for CLI/JSON output.
    """
    out = {}
    for k, v in row.items():
        if isinstance(v, (int, np.integer)):
            out[k] = int(v)
        elif isinstance(v, (float, np.floating)):
            # 6 digits for ratios, 2 for pct-like
            if k.endswith("_pct") or k.endswith("_bps"):
                out[k] = round(float(v), 3)
            else:
                out[k] = round(float(v), 6)
        else:
            out[k] = v
    return out
