# src/backtest/wf_filters.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class WFFilterCfg:
    min_pf: Optional[float] = None
    min_return: Optional[float] = None           # в долях (0.02 = +2%)
    max_dd: Optional[float] = None               # в долях (0.3 = -30% → пишем 0.3)
    min_winrate: Optional[float] = None          # 0.25 = 25%
    min_sharpe: Optional[float] = None
    min_cagr: Optional[float] = None             # доли годовых
    min_calmar: Optional[float] = None
    min_folds: Optional[int] = None
    min_trades: Optional[int] = None
    max_exposure: Optional[float] = None         # 0.7 = 70%

    # какие колонки использовать (mean или agg)
    use_mean: bool = True

    def col(self, base: str) -> str:
        return f"{base}_mean" if self.use_mean else f"{base}_agg"


def _ensure_cols(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"WF dataframe misses columns: {missing}")


def apply_wf_filters(df: pd.DataFrame, cfg: WFFilterCfg) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Возвращает (passed_df, failed_df) с колонкой '_filter_reason' во втором.
    Не мутирует исходный df.
    """
    if df.empty:
        return df.copy(), df.copy()

    work = df.copy()
    reasons = pd.Series([""] * len(work), index=work.index, dtype=object)

    # Сопоставление фильтра с (проверкой, человекочитаемым именем)
    checks: List[Tuple[Callable[[pd.Series], pd.Series], str]] = []

    if cfg.min_pf is not None:
        col = cfg.col("oos_profit_factor")
        _ensure_cols(work, [col])
        checks.append((lambda s, c=col: s[c] >= cfg.min_pf, f"{col} >= {cfg.min_pf}"))

    if cfg.min_return is not None:
        col = cfg.col("oos_total_return_pct")
        _ensure_cols(work, [col])
        checks.append((lambda s, c=col: s[c] >= cfg.min_return, f"{col} >= {cfg.min_return:.3f}"))

    if cfg.max_dd is not None:
        col = cfg.col("oos_max_drawdown_pct")
        _ensure_cols(work, [col])
        # dd отрицательный → -0.20 >= -max_dd
        checks.append((lambda s, c=col: s[c] >= -cfg.max_dd, f"{col} >= {-cfg.max_dd:.3f}"))

    if cfg.min_winrate is not None:
        col = cfg.col("oos_winrate_pct")
        _ensure_cols(work, [col])
        checks.append((lambda s, c=col: s[c] >= 100.0 * cfg.min_winrate if work[c].max() <= 100 else s[c] >= cfg.min_winrate,
                       f"{col} >= {cfg.min_winrate}"))

    if cfg.min_sharpe is not None:
        col = cfg.col("oos_sharpe")
        _ensure_cols(work, [col])
        checks.append((lambda s, c=col: s[c] >= cfg.min_sharpe, f"{col} >= {cfg.min_sharpe}"))

    if cfg.min_cagr is not None:
        col = cfg.col("oos_cagr_pct")
        _ensure_cols(work, [col])
        checks.append((lambda s, c=col: s[c] >= cfg.min_cagr, f"{col} >= {cfg.min_cagr}"))

    if cfg.min_calmar is not None:
        col = cfg.col("oos_calmar")
        _ensure_cols(work, [col])
        checks.append((lambda s, c=col: s[c] >= cfg.min_calmar, f"{col} >= {cfg.min_calmar}"))

    if cfg.min_trades is not None and "oos_trades_mean" in work.columns:
        checks.append((lambda s: s["oos_trades_mean"] >= cfg.min_trades, f"oos_trades_mean >= {cfg.min_trades}"))

    if cfg.max_exposure is not None and "oos_exposure_pct_mean" in work.columns:
        thr = 100.0 * cfg.max_exposure if work["oos_exposure_pct_mean"].max() <= 100 else cfg.max_exposure
        checks.append((lambda s, t=thr: s["oos_exposure_pct_mean"] <= t, f"oos_exposure_pct_mean <= {thr}"))

    mask = pd.Series(True, index=work.index)
    for check, reason in checks:
        ok = check(work)
        mask &= ok
        reasons = reasons.where(ok, other=(reasons.str.cat(pd.Series([reason]*len(work), index=work.index), sep="; ", na_rep="").str.strip("; ")))

    passed = work[mask].copy()
    failed = work[~mask].copy()
    if not failed.empty:
        failed["_filter_reason"] = reasons[~mask]
    return passed, failed
