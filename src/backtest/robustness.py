# src/backtest/robustness.py
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, List

import numpy as np
import pandas as pd


def _neighbors_mask(df: pd.DataFrame, row, d_fast=2, d_slow=5, d_hyst=5, d_cd=2) -> pd.Series:
    return (
        (df["fast"].between(row["fast"] - d_fast, row["fast"] + d_fast))
        & (df["slow"].between(row["slow"] - d_slow, row["slow"] + d_slow))
        & (df["hysteresis_bps"].between(row["hysteresis_bps"] - d_hyst, row["hysteresis_bps"] + d_hyst))
        & (df["cooldown_bars"].between(row["cooldown_bars"] - d_cd, row["cooldown_bars"] + d_cd))
    )


def _resolve_csv(path_or_glob: str) -> Path:
    s = path_or_glob.strip()
    p = Path(s)
    if p.exists() and p.is_file():
        return p
    if p.exists() and p.is_dir():
        candidates = sorted(p.rglob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"No CSV files found in directory: {p}")
    if any(ch in s for ch in "*?[]"):
        globbed = sorted(Path().glob(s), key=lambda x: x.stat().st_mtime, reverse=True)
        if globbed:
            return globbed[0]
        if p.parent.exists():
            globbed = sorted(p.parent.glob(p.name), key=lambda x: x.stat().st_mtime, reverse=True)
            if globbed:
                return globbed[0]
        raise FileNotFoundError(f"Glob pattern did not match any files: {s}")
    raise FileNotFoundError(f"CSV not found: {s}.")


def compute_stability(
    csv_path: Path,
    min_trades: int = 4,
    metric: str = "calmar",
    d_fast=2,
    d_slow=5,
    d_hyst=5,
    d_cd=2,
) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # выкидываем явные ошибки, если есть столбец 'error'
    if "error" in df.columns:
        df = df[df["error"].isna()].copy()

    if df.empty:
        raise RuntimeError("Sweep CSV contains no successful rows (all with errors).")

    # фильтр по числу сделок — только если колонка есть
    if "trades" in df.columns:
        df = df[df["trades"].fillna(0) >= min_trades].copy()
        if df.empty:
            raise RuntimeError(f"No rows with trades >= {min_trades}.")
    else:
        # колонка отсутствует — продолжаем без фильтра, но предупредим через исключение,
        # если нет метрики для ранжирования
        pass

    if metric not in df.columns:
        raise RuntimeError(f"Metric '{metric}' not found in CSV. Available: {', '.join(df.columns)}")

    # приводим бесконечности к NaN
    for col in ("profit_factor", "calmar"):
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

    st_vals: List[float] = []
    st_med: List[float] = []
    neigh_cnt: List[int] = []

    for _, row in df.iterrows():
        mask = _neighbors_mask(df, row, d_fast, d_slow, d_hyst, d_cd)
        neigh = df[mask]
        neigh_cnt.append(int(len(neigh)))
        if metric in neigh.columns and len(neigh) > 0:
            st_vals.append(float(neigh[metric].mean()))
            st_med.append(float(neigh[metric].median()))
        else:
            st_vals.append(np.nan)
            st_med.append(np.nan)

    df["stability_mean"] = st_vals
    df["stability_median"] = st_med
    df["neighbors"] = neigh_cnt

    df = df.sort_values(
        by=["stability_median", "stability_mean", metric],
        ascending=[False, False, False],
        na_position="last",
    )
    return df


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("robustness", description="Neighborhood robustness ranking for sweep CSV")
    p.add_argument("--sweep-csv", required=True, type=str,
                   help="Path, directory, or glob (quote it!) e.g. 'data/sweep/sweep_*DOGE_EUR_5m_*.csv'")
    p.add_argument("--metric", default="calmar", type=str)
    p.add_argument("--min-trades", default=4, type=int)
    p.add_argument("--d-fast", default=2, type=int)
    p.add_argument("--d-slow", default=5, type=int)
    p.add_argument("--d-hyst", default=5, type=int)
    p.add_argument("--d-cd", default=2, type=int)
    p.add_argument("--out-csv", default=None, type=str)
    p.add_argument("--top-n", default=20, type=int)
    return p


def main(argv: Optional[list] = None) -> None:
    args = build_parser().parse_args(argv)
    resolved = _resolve_csv(args.sweep_csv)
    ranked = compute_stability(
        csv_path=resolved,
        min_trades=int(args.min_trades),
        metric=str(args.metric),
        d_fast=int(args.d_fast),
        d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst),
        d_cd=int(args.d_cd),
    )
    if args.out_csv:
        out_p = Path(args.out_csv)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        ranked.to_csv(out_p, index=False)

    print(f"\nUsing sweep CSV: {resolved}\n")
    top = ranked.head(int(args.top_n))
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(top.to_string(index=False))
    if args.out_csv:
        print(f"\nSaved ranked table to: {out_p}")


if __name__ == "__main__":
    main()
