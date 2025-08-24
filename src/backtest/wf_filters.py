from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Tuple

import pandas as pd


@dataclass
class WFFilterParams:
    min_pf: float = 0.0
    min_return: float = 0.0  # as fraction (0.05 == +5%)
    max_dd: float = 1.0      # as fraction (0.3 == -30%)
    min_sharpe: float = -999.0
    min_cagr: float = -999.0
    min_calmar: float = -999.0
    min_winrate: float = 0.0
    min_folds: int = 1
    min_trades: int = 0
    max_exposure: float = 1.0


def apply_wf_filters(df: pd.DataFrame, p: WFFilterParams) -> pd.DataFrame:
    """Applies inclusive filters to WF means. Accepts columns with suffix `_mean`."""
    if df.empty:
        return df

    out = df.copy()

    def have(col: str) -> bool:
        return col in out.columns

    if have("oos_profit_factor_mean"):
        out = out[out["oos_profit_factor_mean"] >= p.min_pf]
    if have("oos_total_return_pct_mean"):
        out = out[out["oos_total_return_pct_mean"] >= p.min_return]
    if have("oos_max_drawdown_pct_mean"):
        out = out[out["oos_max_drawdown_pct_mean"] >= -p.max_dd]  # dd is negative
    if have("oos_sharpe_mean"):
        out = out[out["oos_sharpe_mean"] >= p.min_sharpe]
    if have("oos_cagr_pct_mean"):
        out = out[out["oos_cagr_pct_mean"] >= p.min_cagr]
    if have("oos_calmar_mean"):
        out = out[out["oos_calmar_mean"] >= p.min_calmar]
    if have("oos_winrate_pct_mean"):
        out = out[out["oos_winrate_pct_mean"] >= (100.0 * p.min_winrate)]

    if have("folds"):
        out = out[out["folds"] >= p.min_folds]
    if have("trades"):
        out = out[out["trades"] >= p.min_trades]
    if have("exposure_pct"):
        out = out[out["exposure_pct"] <= 100.0 * p.max_exposure]

    return out
