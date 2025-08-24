# src/backtest/walkforward.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

import pandas as pd
import numpy as np

from .sweep import _fetch_exmo_candles_cached, _resample_ohlc, _simulate_on_df, _normalize_resample_rule


@dataclass
class WFConfig:
    pair: str
    span: str
    resample: Optional[str]
    fast: int
    slow: int
    hysteresis_bps: int
    cooldown_bars: int
    fee_bps: int
    slip_bps: int
    qty_eur: float
    max_daily_loss_bps: int = 0
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100
    enter_on_start: bool = False


def _split_folds(n: int, folds: int, min_train: int, min_valid: int) -> List[tuple[slice, slice]]:
    out = []
    i = 0
    while True:
        tr_a = i
        tr_b = i + min_train
        va_a = tr_b
        va_b = va_a + min_valid
        if va_b > n:
            break
        out.append((slice(tr_a, tr_b), slice(va_a, va_b)))
        i += max(1, (n - va_b) // max(1, folds))
        if len(out) >= folds:
            break
    return out


def run_walkforward(cfg: WFConfig) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    raw = _fetch_exmo_candles_cached(cfg.pair, cfg.span, retries=3).sort_index()
    ohlc = _resample_ohlc(raw, cfg.resample)
    if ohlc.empty:
        raise RuntimeError("Empty OHLC for WF")

    splits = _split_folds(len(ohlc), cfg.folds, cfg.min_train_bars, cfg.min_valid_bars)
    if not splits:
        raise RuntimeError("Not enough bars for requested folds/train/valid")

    rows = []
    for i, (tr_sl, va_sl) in enumerate(splits, start=1):
        va_df = ohlc.iloc[va_sl]
        if va_df.empty:
            continue
        metrics, _, _ = _simulate_on_df(
            va_df,
            fast=cfg.fast, slow=cfg.slow,
            hysteresis_bps=cfg.hysteresis_bps,
            cooldown_bars=cfg.cooldown_bars,
            fee_bps=cfg.fee_bps, slip_bps=cfg.slip_bps,
            qty_eur=cfg.qty_eur,
            resample_rule=_normalize_resample_rule(cfg.resample),
            pair_name=cfg.pair,
        )
        rows.append({"fold": i, **metrics})

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("WF produced no folds (all empty)")

    agg = {
        "oos_total_return_pct_mean": df["total_return_pct"].mean(),
        "oos_total_return_pct_std": df["total_return_pct"].std(ddof=0),
        "oos_max_drawdown_pct_mean": df["max_drawdown_pct"].mean(),
        "oos_winrate_pct_mean": df["winrate_pct"].mean(),
        "oos_profit_factor_mean": df["profit_factor"].replace([np.inf, -np.inf], np.nan).mean(),
        "oos_sharpe_mean": df["sharpe"].mean(),
        "oos_cagr_pct_mean": df["cagr_pct"].mean(),
        "oos_calmar_mean": df["calmar"].replace([np.inf, -np.inf], np.nan).mean(),
    }
    return df, agg
