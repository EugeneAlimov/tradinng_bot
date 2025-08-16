# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any
import os
import pandas as pd

from src.core.metrics import parse_range, needs_equity
from src.core.backtest import run_backtest_sma


def optimize_sma_grid(
        df: pd.DataFrame,
        fast_range: str, slow_range: str,
        fee_bps: float, slip_bps: float,
        start_eur: float, qty_eur: float,
        out_csv: str, metric: str = "sharpe",
        warmup_bars: int = 0, inventory_method: str = "FIFO",
) -> pd.DataFrame:
    f_vals = parse_range(fast_range)
    s_vals = parse_range(slow_range)
    rows = []
    need_eq = needs_equity(metric)
    for f in f_vals:
        for s in s_vals:
            if f >= s:
                continue
            _, _, rep = run_backtest_sma(
                df, fast=f, slow=s,
                start_eur=start_eur, qty_eur=qty_eur,
                fee_bps=fee_bps, slip_bps=slip_bps,
                inventory_method=inventory_method, warmup_bars=warmup_bars,
                collect_trades=False, collect_equity=need_eq,
            )
            m = rep["metrics"]
            rows.append({
                "fast": f, "slow": s,
                "end": m.get("end", 0.0),
                "total_pnl": m.get("total_pnl", 0.0),
                "sharpe": m.get("sharpe", 0.0),
                "trades": m.get("trades", 0),
                "dd": m.get("max_drawdown", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "pf": m.get("profit_factor", 0),
            })
    res = pd.DataFrame(rows)
    if out_csv:
        os.makedirs(os.path.dirname(out_csv), exist_ok=True)
        res.to_csv(out_csv, index=False)
    return res


def optimize_sma_grid_oos(
        df: pd.DataFrame,
        fast_range: str, slow_range: str,
        fee_bps: float, slip_bps: float,
        start_eur: float, qty_eur: float,
        metric: str = "sharpe", train_ratio: float = 0.7,
        warmup_bars: int = 0, inventory_method: str = "FIFO",
) -> Dict[str, Any]:
    assert 0.0 < train_ratio < 1.0
    dfx = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    k = max(1, int(len(dfx) * train_ratio))
    train_df, test_df = dfx.iloc[:k].reset_index(drop=True), dfx.iloc[k:].reset_index(drop=True)

    grid = optimize_sma_grid(
        train_df, fast_range, slow_range,
        fee_bps, slip_bps, start_eur, qty_eur,
        out_csv="", metric=metric, warmup_bars=warmup_bars,
        inventory_method=inventory_method,
    )
    key = "dd" if metric.lower() == "dd" else metric
    maximize = metric.lower() in ("sharpe", "end", "total_pnl")
    g = grid.copy()
    g[key] = pd.to_numeric(g[key], errors="coerce")
    g = g.dropna(subset=[key])
    best = g.sort_values(key, ascending=not maximize).iloc[0]
    f, s = int(best["fast"]), int(best["slow"])

    _, _, rep = run_backtest_sma(
        test_df, fast=f, slow=s,
        start_eur=start_eur, qty_eur=qty_eur,
        fee_bps=fee_bps, slip_bps=slip_bps,
        inventory_method=inventory_method, warmup_bars=warmup_bars,
        collect_trades=False, collect_equity=True,
    )

    return {
        "best": {"fast": f, "slow": s, "metric_train": float(best[key])},
        "train_len": len(train_df), "test_len": len(test_df),
        "test_metrics": rep["metrics"],
    }


def walk_forward_sma(
        df: pd.DataFrame,
        fast_range: str, slow_range: str,
        fee_bps: float, slip_bps: float,
        start_eur: float, qty_eur: float,
        window_bars: int = 2000, step_bars: int = 500,
        metric: str = "sharpe", warmup_bars: int = 0,
        inventory_method: str = "FIFO",
) -> pd.DataFrame:
    dfx = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    n = len(dfx);
    rows = []
    need = max(parse_range(slow_range) or [1] + parse_range(fast_range) or [1])

    i = 0
    while True:
        tr_a, tr_b = i, min(i + window_bars, n)
        te_a, te_b = tr_b, min(tr_b + step_bars, n)
        if te_a >= te_b or (tr_b - tr_a) < need:
            break

        train_df = dfx.iloc[tr_a:tr_b].reset_index(drop=True)
        test_df = dfx.iloc[te_a:te_b].reset_index(drop=True)
        grid = optimize_sma_grid(
            train_df, fast_range, slow_range,
            fee_bps, slip_bps, start_eur, qty_eur,
            out_csv="", metric=metric, warmup_bars=warmup_bars,
            inventory_method=inventory_method,
        )
        key = "dd" if metric.lower() == "dd" else metric
        maximize = metric.lower() in ("sharpe", "end", "total_pnl")
        g = grid.copy()
        g[key] = pd.to_numeric(g[key], errors="coerce")
        g = g.dropna(subset=[key])
        best = g.sort_values(key, ascending=not maximize).iloc[0]
        f, s = int(best["fast"]), int(best["slow"])

        _, _, rep = run_backtest_sma(
            test_df, fast=f, slow=s,
            start_eur=start_eur, qty_eur=qty_eur,
            fee_bps=fee_bps, slip_bps=slip_bps,
            inventory_method=inventory_method, warmup_bars=warmup_bars,
            collect_trades=False, collect_equity=True,
        )
        m = rep["metrics"]
        rows.append({
            "train_start": train_df["time"].iloc[0], "train_end": train_df["time"].iloc[-1],
            "test_start": test_df["time"].iloc[0], "test_end": test_df["time"].iloc[-1],
            "fast": f, "slow": s, "end": m["end"], "pnl": m["total_pnl"], "sharpe": m["sharpe"],
            "dd": m["max_drawdown"], "pf": m["profit_factor"], "trades": m["trades"],
        })
        i += step_bars
        if te_b >= n: break

    return pd.DataFrame(rows)


def optimize_risk_grid(
        df: pd.DataFrame,
        fast: int, slow: int,
        fee_bps: float, slip_bps: float,
        start_eur: float, qty_eur: float,
        atr_range: str = "0.0:3.0:0.5",
        tp_range: str = "0:120:10",
        metric: str = "sharpe",
        warmup_bars: int = 0,
        inventory_method: str = "FIFO",
) -> pd.DataFrame:
    def _frange(spec: str) -> list[float]:
        a, b, s = [float(x) for x in str(spec).split(":")]
        cur = a;
        out = []
        while cur <= b + 1e-12:
            out.append(round(cur, 10))
            cur += s
        return out

    need_eq = needs_equity(metric)
    atr_vals = _frange(atr_range)
    tp_vals = [int(x) for x in _frange(tp_range)]
    rows = []
    for am in atr_vals:
        for tp in tp_vals:
            _, _, rep = run_backtest_sma(
                df, fast=fast, slow=slow,
                start_eur=start_eur, qty_eur=qty_eur,
                fee_bps=fee_bps, slip_bps=slip_bps,
                inventory_method=inventory_method, warmup_bars=warmup_bars,
                atr_period=14, atr_mult=am, tp_bps=tp,
                collect_trades=False, collect_equity=need_eq,
            )
            m = rep["metrics"]
            rows.append({"atr_mult": am, "tp_bps": tp, "end": m["end"],
                         "pnl": m["total_pnl"], "sharpe": m["sharpe"],
                         "dd": m["max_drawdown"], "pf": m["profit_factor"], "trades": m["trades"]})
    return pd.DataFrame(rows)
