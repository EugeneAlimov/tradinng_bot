from __future__ import annotations

import math
from typing import Optional

import pandas as pd


def apply_wf_filters(
    df: pd.DataFrame,
    min_pf: float = 1.0,
    min_return: float = 0.0,
    max_dd: float = 1.0,
    min_winrate: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    min_cagr: Optional[float] = None,
    min_calmar: Optional[float] = None,
    min_folds: int = 0,
    min_trades: int = 0,
    max_exposure: float = 1.0,
) -> pd.Series:
    """Ожидаются метрики с префиксом 'oos_' и суффиксом '_mean' или '_agg'."""
    m = pd.Series(True, index=df.index)

    def col(name: str) -> pd.Series:
        return df[name] if name in df.columns else pd.Series([math.nan]*len(df), index=df.index)

    m &= col("oos_profit_factor_mean") >= float(min_pf)
    m &= col("oos_total_return_pct_mean") >= float(min_return)
    m &= col("oos_max_drawdown_pct_mean") >= -float(max_dd)  # drawdown отрицательный

    if min_winrate is not None:
        m &= col("oos_winrate_pct_mean") >= float(min_winrate)
    if min_sharpe is not None:
        m &= col("oos_sharpe_mean") >= float(min_sharpe)
    if min_cagr is not None:
        m &= col("oos_cagr_pct_mean") >= float(min_cagr)
    if min_calmar is not None:
        m &= col("oos_calmar_mean") >= float(min_calmar)

    if min_folds > 0 and "oos_folds_ok" in df.columns:
        m &= col("oos_folds_ok") >= int(min_folds)

    if min_trades > 0 and "oos_trades_total" in df.columns:
        m &= col("oos_trades_total") >= int(min_trades)

    if "oos_exposure_pct_mean" in df.columns:
        m &= col("oos_exposure_pct_mean") <= float(max_exposure * 100.0)

    return m
