# src/backtest/robustness.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Tuple
import pandas as pd
import numpy as np


MetricName = Literal[
    "total_return_pct", "profit_factor", "calmar", "sharpe", "cagr_pct",
]

@dataclass
class RobustCfg:
    csv_path: Path
    min_trades: int = 4
    metric: MetricName = "calmar"
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2


def _load_sweep(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"Sweep CSV not found: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        raise RuntimeError("Sweep CSV is empty (no data).")
    return df


def _neighbors_mask(df: pd.DataFrame, row: pd.Series, d: Tuple[int, int, int, int]) -> pd.Series:
    d_fast, d_slow, d_hyst, d_cd = d
    return (
        (df["fast"].sub(row["fast"]).abs() <= d_fast) &
        (df["slow"].sub(row["slow"]).abs() <= d_slow) &
        (df["hysteresis_bps"].sub(row["hysteresis_bps"]).abs() <= d_hyst) &
        (df["cooldown_bars"].sub(row["cooldown_bars"]).abs() <= d_cd) &
        (df["qty_eur"] == row["qty_eur"])
    )


def compute_stability(
    csv_path: Path,
    min_trades: int = 4,
    metric: MetricName = "calmar",
    d_fast: int = 2, d_slow: int = 5, d_hyst: int = 5, d_cd: int = 2,
) -> pd.DataFrame:
    """
    Возвращает таблицу с колонками `stability_mean`, `stability_median`, `neighbors`,
    отсортированную по stability_mean убыв.
    """
    df = _load_sweep(csv_path)

    # Важно: оставляем только успешные строки
    if "error" in df.columns:
        df = df[(df["error"].isna()) | (df["error"] == "")]
    # Нужные колонки должны существовать
    needed_cols = {"fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur", "trades"}
    for c in needed_cols:
        if c not in df.columns:
            raise RuntimeError(f"Sweep CSV missing required column: '{c}'")

    df = df[df["trades"].fillna(0).astype(int) >= int(min_trades)].copy()
    if df.empty:
        raise RuntimeError("Sweep CSV contains no successful rows (all with errors).")

    # Числовая метрика
    if metric not in df.columns:
        raise RuntimeError(f"Metric '{metric}' not found in sweep CSV.")
    vals = pd.to_numeric(df[metric], errors="coerce")
    df = df[~vals.isna()].copy()

    # Расчёт стабильности по соседям ±d
    stab_mean = []
    stab_median = []
    neigh_count = []
    for _, r in df.iterrows():
        mask = _neighbors_mask(df, r, (d_fast, d_slow, d_hyst, d_cd))
        neighborhood = df.loc[mask, metric].astype(float)
        neigh_count.append(int(neighborhood.shape[0]))
        if neighborhood.empty:
            stab_mean.append(np.nan)
            stab_median.append(np.nan)
        else:
            stab_mean.append(float(neighborhood.mean()))
            stab_median.append(float(neighborhood.median()))

    df["stability_mean"] = stab_mean
    df["stability_median"] = stab_median
    df["neighbors"] = neigh_count

    df = df.sort_values(["stability_mean", "stability_median"], ascending=False).reset_index(drop=True)
    return df
