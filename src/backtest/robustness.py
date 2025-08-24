from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class RobustParams:
    metric: str = "calmar"      # one of columns in sweep CSV
    min_trades: int = 0
    # neighborhood steps for stability (± d)
    d_fast: int = 1
    d_slow: int = 1
    d_hyst: int = 1
    d_cd: int = 1


def _read_sweep(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # normalize columns that may vary across versions
    for col in ("trades", "bars", "winrate_pct", "total_return_pct", "max_drawdown_pct"):
        if col not in df.columns:
            # try alternative capitalization or missing columns
            alt = col.upper()
            if alt in df.columns:
                df.rename(columns={alt: col}, inplace=True)
    # some versions save 'None' strings
    for col in ("trades_csv", "equity_csv"):
        if col in df.columns:
            df[col] = df[col].replace({"None": np.nan})
    return df


def compute_stability(
    *,
    csv_path: Path,
    min_trades: int,
    metric: str,
    d_fast: int,
    d_slow: int,
    d_hyst: int,
    d_cd: int,
) -> pd.DataFrame:
    df = _read_sweep(csv_path)
    if df.empty:
        raise RuntimeError("Sweep CSV contains no rows.")

    if "trades" in df.columns:
        df = df[df["trades"] >= int(min_trades)].copy()
    if df.empty:
        raise RuntimeError("Sweep CSV contains no successful rows (all with errors).")

    need_cols = {"fast", "slow", "hysteresis_bps", "cooldown_bars"}
    if not need_cols.issubset(df.columns):
        missing = ", ".join(sorted(need_cols - set(df.columns)))
        raise RuntimeError(f"Sweep CSV missing required columns: {missing}")

    if metric not in df.columns:
        raise RuntimeError(f"Metric '{metric}' not found in sweep CSV columns.")

    # Build a key -> metric index
    key_cols = ["fast", "slow", "hysteresis_bps", "cooldown_bars"]
    df["_key"] = list(zip(*(df[c].astype(int) for c in key_cols)))
    metric_vals = df[["_key", metric]].set_index("_key")[metric].to_dict()

    def neighborhood_score(key) -> float:
        f, s, h, cd = key
        acc = []
        for df_ in range(-d_fast, d_fast + 1):
            for ds_ in range(-d_slow, d_slow + 1):
                for dh_ in range(-d_hyst, d_hyst + 1):
                    for dcd_ in range(-d_cd, d_cd + 1):
                        if df_ == ds_ == dh_ == dcd_ == 0:
                            continue
                        k = (f + df_, s + ds_, h + dh_, cd + dcd_)
                        v = metric_vals.get(k, np.nan)
                        if not (isinstance(v, float) and math.isnan(v)):
                            acc.append(float(v))
        if not acc:
            return np.nan
        # median is robust to outliers
        return float(np.nanmedian(np.array(acc, dtype=float)))

    df["neighbors"] = df["_key"].apply(neighborhood_score)
    df["stability_mean"] = df[["neighbors", metric]].mean(axis=1, numeric_only=True)
    df["stability_median"] = df[["neighbors", metric]].median(axis=1, numeric_only=True)

    # rank by stability_mean first, then requested metric
    df = df.sort_values(by=["stability_mean", metric], ascending=False).reset_index(drop=True)
    # keep only essential columns near the user examples
    keep = [
        "pair", "bars", "trades", "winrate_pct", "total_return_pct", "max_drawdown_pct",
        "final_equity_eur", "start_equity_eur", "profit_factor", "avg_trade_eur", "exposure_pct",
        "sharpe", "cagr_pct", "calmar", "bars_per_year",
        "fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur",
        "fee_bps", "slip_bps", "max_daily_loss_bps",
        "trades_csv", "equity_csv",
        "stability_mean", "stability_median", "neighbors",
    ]
    existing = [c for c in keep if c in df.columns]
    return df[existing]
