# src/backtest/robustness.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List
import numpy as np
import pandas as pd


@dataclass
class StabilityCfg:
    csv_path: Path
    metric: str = "calmar"
    min_trades: int = 0
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2
    top_n: int = 20


def _coerce_numeric(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _load_csv_maybe_glob(path: Path) -> pd.DataFrame:
    if any(ch in str(path) for ch in "*?[]"):
        parts = sorted(path.parent.glob(path.name))
        dfs = []
        for p in parts:
            try:
                dfs.append(pd.read_csv(p))
            except Exception:
                pass
        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    else:
        return pd.read_csv(path)


def compute_stability(
    *, csv_path: Path, metric: str, min_trades: int,
    d_fast: int, d_slow: int, d_hyst: int, d_cd: int,
    top_n: int = 20,
) -> pd.DataFrame:
    try:
        df = _load_csv_maybe_glob(csv_path)
    except Exception as e:
        return pd.DataFrame(columns=["error"]).assign(error=f"load_failed: {e}")

    if df.empty:
        return pd.DataFrame(columns=["error"]).assign(error="empty_sweep")

    num_cols = [
        "bars", "trades", "winrate_pct", "total_return_pct", "max_drawdown_pct",
        "final_equity_eur", "start_equity_eur", "profit_factor", "avg_trade_eur",
        "exposure_pct", "sharpe", "cagr_pct", "calmar",
        "fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur",
        "fee_bps", "slip_bps", "max_daily_loss_bps",
    ]
    df = _coerce_numeric(df, num_cols)

    df_ok = df.copy()
    if "error" in df_ok.columns:
        df_ok = df_ok[(df_ok["error"].isna()) | (df_ok["error"].astype(str).str.strip() == "")]

    if "trades" in df_ok.columns:
        df_ok = df_ok[df_ok["trades"].fillna(0) >= int(min_trades)]

    if df_ok.empty:
        return pd.DataFrame(columns=["error"]).assign(error="no_success_rows_after_filtering")

    # соседство/устойчивость
    for c in ["fast", "slow", "hysteresis_bps", "cooldown_bars"]:
        if c not in df_ok.columns:
            df_ok[c] = np.nan

    if metric not in df_ok.columns:
        df_ok[metric] = np.nan

    rows = []
    arr = df_ok[["fast", "slow", "hysteresis_bps", "cooldown_bars", metric]].to_numpy()
    for i in range(len(df_ok)):
        f, s, h, c, m = arr[i]
        fast_ok = (np.abs(arr[:, 0] - f) <= d_fast)
        slow_ok = (np.abs(arr[:, 1] - s) <= d_slow)
        hyst_ok = (np.abs(arr[:, 2] - h) <= d_hyst)
        cd_ok = (np.abs(arr[:, 3] - c) <= d_cd)
        mask = fast_ok & slow_ok & hyst_ok & cd_ok
        vals = df_ok.loc[mask, metric].dropna().to_numpy()
        neigh_cnt = int(vals.size)
        neigh_mean = float(np.nanmean(vals)) if neigh_cnt else np.nan
        neigh_med = float(np.nanmedian(vals)) if neigh_cnt else np.nan
        rows.append((neigh_mean, neigh_med, neigh_cnt))

    df_ok = df_ok.copy()
    df_ok["stability_mean"] = [r[0] for r in rows]
    df_ok["stability_median"] = [r[1] for r in rows]
    df_ok["neighbors"] = [r[2] for r in rows]

    df_ok = df_ok.sort_values(by=["stability_mean", metric], ascending=[False, False], kind="mergesort")

    if top_n and top_n > 0:
        df_ok = df_ok.head(int(top_n)).reset_index(drop=True)

    return df_ok
