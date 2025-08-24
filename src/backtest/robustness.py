# src/backtest/robustness.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Tuple, Dict, Any

import numpy as np
import pandas as pd


RankMetric = Literal["calmar", "profit_factor", "total_return_pct", "sharpe", "cagr_pct"]


@dataclass
class StabilityConfig:
    metric: RankMetric = "calmar"
    min_trades: int = 0
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2


def _neighbors(df: pd.DataFrame, row: pd.Series, cfg: StabilityConfig) -> pd.DataFrame:
    mask = (
        (df["fast"].between(row["fast"] - cfg.d_fast, row["fast"] + cfg.d_fast)) &
        (df["slow"].between(row["slow"] - cfg.d_slow, row["slow"] + cfg.d_slow)) &
        (df["hysteresis_bps"].between(row["hysteresis_bps"] - cfg.d_hyst, row["hysteresis_bps"] + cfg.d_hyst)) &
        (df["cooldown_bars"].between(row["cooldown_bars"] - cfg.d_cd, row["cooldown_bars"] + cfg.d_cd))
    )
    return df[mask]


def _score_by_metric(df: pd.DataFrame, metric: RankMetric) -> pd.Series:
    if metric not in df.columns:
        raise RuntimeError(f"Metric '{metric}' is absent in sweep CSV.")
    return df[metric].astype(float)


def compute_stability(
    csv_path: Path,
    min_trades: int = 0,
    metric: RankMetric = "calmar",
    d_fast: int = 2, d_slow: int = 5, d_hyst: int = 5, d_cd: int = 2,
) -> pd.DataFrame:
    """
    Возвращает входную таблицу с добавленными колонками:
      - stability_mean / stability_median / neighbors
    """
    if isinstance(csv_path, (str, Path)):
        csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"Sweep CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty or "fast" not in df.columns or "trades" not in df.columns:
        raise RuntimeError("Sweep CSV contains no successful rows (all with errors).")

    df = df.copy()
    df = df[df["trades"] >= int(min_trades)]
    if df.empty:
        raise RuntimeError("No rows pass 'min_trades' filter.")

    score = _score_by_metric(df, metric)
    stab_mean = []
    stab_med = []
    neigh_cnt = []

    for _, row in df.iterrows():
        neigh = _neighbors(df, row, StabilityConfig(metric, min_trades, d_fast, d_slow, d_hyst, d_cd))
        neigh_cnt.append(int(len(neigh)))
        if len(neigh) == 0:
            stab_mean.append(np.nan)
            stab_med.append(np.nan)
            continue
        vals = _score_by_metric(neigh, metric).values
        stab_mean.append(float(np.mean(vals)))
        stab_med.append(float(np.median(vals)))

    df["stability_mean"] = stab_mean
    df["stability_median"] = stab_med
    df["neighbors"] = neigh_cnt

    # сортировать по stability_mean у выбранной метрики и самой метрике
    df = df.sort_values(by=["stability_mean", metric], ascending=[False, False]).reset_index(drop=True)
    return df


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--sweep-csv", required=True)
    p.add_argument("--metric", default="calmar", choices=["calmar", "profit_factor", "total_return_pct", "sharpe", "cagr_pct"])
    p.add_argument("--min-trades", type=int, default=0)
    p.add_argument("--d-fast", type=int, default=2)
    p.add_argument("--d-slow", type=int, default=5)
    p.add_argument("--d-hyst", type=int, default=5)
    p.add_argument("--d-cd", type=int, default=2)
    p.add_argument("--out-csv", required=True)
    args = p.parse_args()

    ranked = compute_stability(
        csv_path=Path(args.sweep_csv),
        min_trades=int(args.min_trades), metric=str(args.metric),
        d_fast=int(args.d_fast), d_slow=int(args.d_slow), d_hyst=int(args.d_hyst), d_cd=int(args.d_cd),
    )
    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(args.out_csv, index=False)
    print("\n", ranked.head(20).to_string(index=False))
    print(f"\nSaved ranked table to: {args.out_csv}")


if __name__ == "__main__":
    main()
