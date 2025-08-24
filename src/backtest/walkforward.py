# src/backtest/walkforward.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd

from .compat import (
    normalize_resample_rule,
    fetch_exmo_candles_cached,
    resample_ohlc,
    SimConfig,
    simulate_on_df as _simulate_on_df,  # re-exported for sweep.py compatibility
)


@dataclass
class WFConfig:
    pair: str
    span: str  # e.g. "1m:5000"
    resample: str = "5m"  # "5m" or "5T" etc.
    fast: int = 10
    slow: int = 20
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    fee_bps: int = 0
    slip_bps: int = 0
    qty_eur: float = 100.0
    max_daily_loss_bps: int = 0

    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    out_dir: str | Path | None = None


def _split_folds(n_bars: int, min_train: int, min_valid: int, folds: int) -> List[Tuple[int, int]]:
    """
    Produce list of (train_end_idx, valid_end_idx], where valid segment is (train_end; valid_end]
    """
    segments: List[Tuple[int, int]] = []
    train_end = min_train
    for _ in range(folds):
        valid_end = train_end + min_valid
        if valid_end > n_bars:
            break
        segments.append((train_end, valid_end))
        train_end += min_valid
    return segments


def run_walkforward(cfg: WFConfig) -> Dict[str, Any]:
    """
    Walk-forward validation over resampled candles for a fixed strategy config.
    Returns dict with OOS means/stds and writes CSV/JSON if out_dir is set.
    """
    rr_user = cfg.resample
    rr = normalize_resample_rule(rr_user)

    full = fetch_exmo_candles_cached(cfg.pair, cfg.span)
    full_rs = resample_ohlc(full, rr)
    if len(full_rs) < (cfg.min_train_bars + cfg.min_valid_bars):
        raise RuntimeError(
            f"Not enough bars after resample: have {len(full_rs)}, need at least "
            f"{cfg.min_train_bars + cfg.min_valid_bars}"
        )

    # Build WF folds
    segments = _split_folds(len(full_rs), cfg.min_train_bars, cfg.min_valid_bars, cfg.folds)
    if not segments:
        raise RuntimeError("Could not create any walk-forward segments with given parameters.")

    # Simulate on each validation segment OOS
    oos_rows: List[Dict[str, Any]] = []
    for train_end, valid_end in segments:
        valid = full_rs.iloc[train_end:valid_end].reset_index(drop=True)
        scfg = SimConfig(
            fast=cfg.fast,
            slow=cfg.slow,
            hysteresis_bps=cfg.hysteresis_bps,
            cooldown_bars=cfg.cooldown_bars,
            fee_bps=cfg.fee_bps,
            slip_bps=cfg.slip_bps,
            qty_eur=cfg.qty_eur,
            resample=rr,
        )
        trades_df, equity_df, metrics = _simulate_on_df(valid, scfg)
        # stamp pair and resample for parity with project style
        metrics.update({"pair": cfg.pair})

        oos_rows.append(
            {
                "pair": cfg.pair,
                "resample": rr_user,
                "fast": cfg.fast,
                "slow": cfg.slow,
                "hysteresis_bps": cfg.hysteresis_bps,
                "cooldown_bars": cfg.cooldown_bars,
                "fee_bps": cfg.fee_bps,
                "slip_bps": cfg.slip_bps,
                "qty_eur": cfg.qty_eur,
                "max_daily_loss_bps": cfg.max_daily_loss_bps,
                "oos_total_return_pct": metrics["total_return_pct"],
                "oos_max_drawdown_pct": metrics["max_drawdown_pct"],
                "oos_winrate_pct": metrics["winrate_pct"],
                "oos_profit_factor": metrics["profit_factor"],
                "oos_sharpe": metrics["sharpe"],
                "oos_cagr_pct": metrics["cagr_pct"],
                "oos_calmar": metrics["calmar"],
                "oos_trades": metrics["trades"],
            }
        )

    oos = pd.DataFrame(oos_rows)

    def _safe_mean(col: str) -> float:
        s = pd.to_numeric(oos[col], errors="coerce").dropna()
        return float(s.mean()) if len(s) else 0.0

    def _safe_std(col: str) -> float:
        s = pd.to_numeric(oos[col], errors="coerce").dropna()
        return float(s.std(ddof=0)) if len(s) else 0.0

    out_summary = {
        "pair": cfg.pair,
        "resample": rr_user,
        "fast": cfg.fast,
        "slow": cfg.slow,
        "hysteresis_bps": cfg.hysteresis_bps,
        "cooldown_bars": cfg.cooldown_bars,
        "fee_bps": cfg.fee_bps,
        "slip_bps": cfg.slip_bps,
        "qty_eur": cfg.qty_eur,
        "max_daily_loss_bps": cfg.max_daily_loss_bps,
        "folds": len(oos_rows),
        "oos_total_return_pct_mean": _safe_mean("oos_total_return_pct"),
        "oos_total_return_pct_std": _safe_std("oos_total_return_pct"),
        "oos_max_drawdown_pct_mean": _safe_mean("oos_max_drawdown_pct"),
        "oos_winrate_pct_mean": _safe_mean("oos_winrate_pct"),
        "oos_profit_factor_mean": _safe_mean("oos_profit_factor"),
        "oos_sharpe_mean": _safe_mean("oos_sharpe"),
        "oos_cagr_pct_mean": _safe_mean("oos_cagr_pct"),
        "oos_calmar_mean": _safe_mean("oos_calmar"),
    }

    # Write artifacts if requested
    out_csv = None
    out_json = None
    if cfg.out_dir:
        out_root = Path(cfg.out_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        out_csv = out_root / f"wf_{cfg.pair}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.csv"
        oos.to_csv(out_csv, index=False)

        out_json = out_root / f"wf_summary_{cfg.pair}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(out_summary, f, ensure_ascii=False, indent=2)

    # Return summary (mimic previous shape)
    return out_summary


# Re-exports for legacy imports (some modules import these from walkforward)
def _normalize_resample_rule(rule: str) -> str:
    return normalize_resample_rule(rule)


def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return resample_ohlc(df, rule)


def _simulate_on_df(df: pd.DataFrame, fast: int, slow: int,
                    hysteresis_bps: int, cooldown_bars: int,
                    fee_bps: int, slip_bps: int, qty_eur: float,
                    enter_on_start: bool = False, max_daily_loss_bps: int = 0,
                    resample: str = "5m"):
    """
    Legacy-compatible wrapper that matches the old signature expected by sweep.py.
    Returns (trades_df, equity_df, metrics_dict).
    """
    scfg = SimConfig(
        fast=fast,
        slow=slow,
        hysteresis_bps=hysteresis_bps,
        cooldown_bars=cooldown_bars,
        fee_bps=fee_bps,
        slip_bps=slip_bps,
        qty_eur=qty_eur,
        enter_on_start=enter_on_start,
        max_daily_loss_bps=max_daily_loss_bps,
        resample=normalize_resample_rule(resample),
    )
    return _simulate_on_df.__wrapped__(df, scfg) if hasattr(_simulate_on_df, "__wrapped__") else _simulate_on_df(df, scfg)
