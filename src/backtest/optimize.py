from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from .robustness import RobustParams, compute_stability
from .wf_filters import WFFilterParams, apply_wf_filters
from .metrics import aggregate_oos_folds
from . import report as report_mod

# These come from existing project modules
from .sweep import SweepCfg, run_sweep
from .walkforward import WFConfig, run_walkforward
from .vectorized_bt import BtConfig, run_backtest_vectorized  # BtConfig exists in project


# -----------------------------
# Inputs
# -----------------------------

@dataclass
class OptimizeInput:
    pair: str
    span: str
    resample: str

    # sweep grids
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]

    # costs/risk
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int = 0

    # robustness
    robust_metric: str = "calmar"
    min_trades: int = 0
    d_fast: int = 1
    d_slow: int = 1
    d_hyst: int = 1
    d_cd: int = 1

    # walk-forward
    wf_top_n: int = 10
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    # wf filters
    wf_min_pf: float = 0.0
    wf_min_return: float = 0.0
    wf_max_dd: float = 1.0
    wf_min_winrate: float = 0.0
    wf_min_sharpe: float = -999.0
    wf_min_cagr: float = -999.0
    wf_min_calmar: float = -999.0
    wf_min_folds: int = 1
    wf_min_trades: int = 0
    wf_max_exposure: float = 1.0

    # selection & report
    rank_by: str = "oos_total_return_pct_mean"
    final_backtest: bool = False

    # IO
    out_dir: Path = Path("data/optimize")
    report_html: Optional[Path] = None


# -----------------------------
# Orchestrator
# -----------------------------

def _sweep_once(inp: OptimizeInput, out_root: Path) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sweep_csv = out_root / f"sweep_{inp.pair}_{inp.resample}_{stamp}.csv"

    scfg = SweepCfg(
        pair=inp.pair,
        span=inp.span,
        resample=inp.resample,
        fast_list=inp.fast_list,
        slow_list=inp.slow_list,
        hyst_list=inp.hyst_list,
        cooldown_list=inp.cooldown_list,
        qty_list=inp.qty_list,
        fee_bps=inp.fee_bps,
        slip_bps=inp.slip_bps,
        sort_by=inp.robust_metric,
        top_n=0,  # dump all; ranking later
        out_dir=sweep_csv.parent,  # ensure Path, not str
        write_artifacts=False,     # avoid thousands of files
    )
    # run_sweep returns path to created CSV
    result_csv_path = Path(run_sweep(scfg))
    # ensure it's at our expected name (older versions may choose their own)
    if result_csv_path != sweep_csv and result_csv_path.exists():
        # keep produced file; also copy as our canonical name for downstream
        try:
            df = pd.read_csv(result_csv_path)
            df.to_csv(sweep_csv, index=False)
        except Exception:
            sweep_csv = result_csv_path
    return sweep_csv


def _rank_robust(sweep_csv: Path, inp: OptimizeInput, out_root: Path) -> Path:
    ranked_csv = out_root / f"ranked_{inp.pair}_{inp.resample}_{sweep_csv.stem.split('_')[-1]}.csv"
    ranked = compute_stability(
        csv_path=Path(sweep_csv),
        min_trades=inp.min_trades,
        metric=inp.robust_metric,
        d_fast=inp.d_fast,
        d_slow=inp.d_slow,
        d_hyst=inp.d_hyst,
        d_cd=inp.d_cd,
    )
    ranked.to_csv(ranked_csv, index=False)
    return ranked_csv


def _wf_top_configs(ranked_csv: Path, inp: OptimizeInput, out_root: Path) -> Tuple[pd.DataFrame, Path]:
    ranked = pd.read_csv(ranked_csv)
    if ranked.empty:
        raise RuntimeError("Ranked table is empty after robustness step.")

    keep_cols = ["fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur"]
    for c in keep_cols:
        if c not in ranked.columns:
            # older sweeps may have 'qty' instead of 'qty_eur'
            if c == "qty_eur" and "qty" in ranked.columns:
                ranked.rename(columns={"qty": "qty_eur"}, inplace=True)
            else:
                raise RuntimeError(f"Ranked CSV is missing required column '{c}'.")

    top = ranked.head(int(inp.wf_top_n))[keep_cols].copy()

    # Run WF for each config and collect rows
    rows: List[Dict] = []
    equities: List[pd.Series] = []

    for _, r in top.iterrows():
        wcfg = WFConfig(
            pair=inp.pair,
            span=inp.span,
            resample=inp.resample,
            fast=int(r["fast"]),
            slow=int(r["slow"]),
            hysteresis_bps=int(r["hysteresis_bps"]),
            cooldown_bars=int(r["cooldown_bars"]),
            fee_bps=int(inp.fee_bps),
            slip_bps=int(inp.slip_bps),
            qty_eur=float(r["qty_eur"]),
            max_daily_loss_bps=int(inp.max_daily_loss_bps),
            folds=int(inp.folds),
            min_train_bars=int(inp.min_train_bars),
            min_valid_bars=int(inp.min_valid_bars),
            out_dir=None,  # disable per-WF artifacts
        )
        wf_out = run_walkforward(wcfg)  # returns dict with oos_*_mean fields (legacy compatible)
        rows.append(wf_out)

        # If run_walkforward returns concatenated_oos_equity path or series, try to read for aggregate
        eq_path = wf_out.get("oos_equity_csv") if isinstance(wf_out, dict) else None
        if isinstance(eq_path, str) and eq_path:
            try:
                eq_df = pd.read_csv(eq_path)
                if "equity" in eq_df.columns:
                    equities.append(eq_df["equity"].astype(float))
            except Exception:
                pass

    wf_df = pd.DataFrame(rows)
    wf_csv = out_root / f"wf_{inp.pair}_{inp.resample}_{ranked_csv.stem.split('_')[-1]}.csv"
    wf_df.to_csv(wf_csv, index=False)
    return wf_df, wf_csv


def _select_best(wf_df: pd.DataFrame, inp: OptimizeInput) -> Dict:
    if wf_df.empty:
        return {}

    # Apply WF filters if present
    filtered = apply_wf_filters(
        wf_df,
        WFFilterParams(
            min_pf=inp.wf_min_pf,
            min_return=inp.wf_min_return,
            max_dd=inp.wf_max_dd,
            min_sharpe=inp.wf_min_sharpe,
            min_cagr=inp.wf_min_cagr,
            min_calmar=inp.wf_min_calmar,
            min_winrate=inp.wf_min_winrate,
            min_folds=inp.wf_min_folds,
            min_trades=inp.wf_min_trades,
            max_exposure=inp.wf_max_exposure,
        ),
    )

    pool = filtered if not filtered.empty else wf_df
    rank_by = inp.rank_by if inp.rank_by in pool.columns else "oos_total_return_pct_mean"
    best = pool.sort_values(by=rank_by, ascending=False).iloc[0].to_dict()
    return best


def _final_backtest(best_cfg: Dict, inp: OptimizeInput, out_root: Path) -> Dict:
    if not best_cfg:
        return {}

    bcfg = BtConfig(
        pair=inp.pair,
        span=inp.span,
        fast=int(best_cfg["fast"]),
        slow=int(best_cfg["slow"]),
        hysteresis_bps=int(best_cfg.get("hysteresis_bps", 0)),
        cooldown_bars=int(best_cfg.get("cooldown_bars", 0)),
        fee_bps=int(inp.fee_bps),
        slip_bps=int(inp.slip_bps),
        qty_eur=float(best_cfg.get("qty_eur", 100.0)),
        max_daily_loss_bps=int(inp.max_daily_loss_bps),
        resample=inp.resample,
        out_dir=str(out_root),  # vectorized_bt handles None/str internally
        enter_on_start=False,
    )
    metrics = run_backtest_vectorized(bcfg)  # should return dict with 'metrics', optional csv paths, etc.

    # Ensure JSON-serializable (strip any DataFrames accidentally leaked)
    def purify(obj):
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        if isinstance(obj, (np.floating, np.integer)):
            return float(obj)
        return obj

    clean = {k: purify(v) for k, v in metrics.items()}
    return clean


def run_optimize(
    *,
    pair: str,
    span: str,
    resample: str,
    fast_list: List[int],
    slow_list: List[int],
    hyst_list: List[int],
    cooldown_list: List[int],
    qty_list: List[float],
    fee_bps: int,
    slip_bps: int,
    max_daily_loss_bps: int,
    metric: str,
    min_trades: int,
    d_fast: int,
    d_slow: int,
    d_hyst: int,
    d_cd: int,
    wf_top_n: int,
    folds: int,
    min_train_bars: int,
    min_valid_bars: int,
    wf_min_pf: float = 0.0,
    wf_min_return: float = 0.0,
    wf_max_dd: float = 1.0,
    wf_min_winrate: float = 0.0,
    wf_min_sharpe: float = -999.0,
    wf_min_cagr: float = -999.0,
    wf_min_calmar: float = -999.0,
    wf_min_folds: int = 1,
    wf_min_trades: int = 0,
    wf_max_exposure: float = 1.0,
    rank_by: str = "oos_total_return_pct_mean",
    final_backtest: bool = False,
    out_dir: Optional[str | Path] = None,
    report_html: Optional[str | Path] = None,
) -> Dict:
    out_root = Path(out_dir) if out_dir else Path("data/optimize")
    out_root.mkdir(parents=True, exist_ok=True)

    inp = OptimizeInput(
        pair=pair, span=span, resample=resample,
        fast_list=list(map(int, fast_list)), slow_list=list(map(int, slow_list)),
        hyst_list=list(map(int, hyst_list)), cooldown_list=list(map(int, cooldown_list)),
        qty_list=list(map(float, qty_list)),
        fee_bps=int(fee_bps), slip_bps=int(slip_bps), max_daily_loss_bps=int(max_daily_loss_bps),
        robust_metric=str(metric), min_trades=int(min_trades),
        d_fast=int(d_fast), d_slow=int(d_slow), d_hyst=int(d_hyst), d_cd=int(d_cd),
        wf_top_n=int(wf_top_n), folds=int(folds),
        min_train_bars=int(min_train_bars), min_valid_bars=int(min_valid_bars),
        wf_min_pf=float(wf_min_pf), wf_min_return=float(wf_min_return), wf_max_dd=float(wf_max_dd),
        wf_min_winrate=float(wf_min_winrate), wf_min_sharpe=float(wf_min_sharpe),
        wf_min_cagr=float(wf_min_cagr), wf_min_calmar=float(wf_min_calmar),
        wf_min_folds=int(wf_min_folds), wf_min_trades=int(wf_min_trades), wf_max_exposure=float(wf_max_exposure),
        rank_by=str(rank_by), final_backtest=bool(final_backtest),
        out_dir=out_root,
        report_html=(Path(report_html) if report_html else None),
    )

    sweep_csv = _sweep_once(inp, out_root)
    ranked_csv = _rank_robust(sweep_csv, inp, out_root)
    wf_df, wf_csv = _wf_top_configs(ranked_csv, inp, out_root)
    best = _select_best(wf_df, inp)

    final_metrics = {}
    if inp.final_backtest and best:
        final_metrics = _final_backtest(best, inp, out_root)

    summary = {
        "pair": pair,
        "resample": resample,
        "fast": best.get("fast"),
        "slow": best.get("slow"),
        "hysteresis_bps": best.get("hysteresis_bps"),
        "cooldown_bars": best.get("cooldown_bars"),
        "qty_eur": best.get("qty_eur"),
        "pair_resample": f"{pair}/{resample}",
        "wf_rank_by": inp.rank_by,
    }
    # carry over oos_* metrics if present
    for k in wf_df.columns:
        if k.startswith("oos_") and k.endswith(("_mean", "_agg")) and k in best:
            summary[k] = best[k]

    # HTML report (optional)
    if inp.report_html:
        report_mod.write_html(
            output_html=inp.report_html,
            summary_json=summary,
            sweep_csv=sweep_csv,
            ranked_csv=ranked_csv,
            wf_csv=wf_csv,
            final_metrics=final_metrics if final_metrics else None,
        )

    # CLI-ish echo for convenience (match user's previous logs style)
    print("\n--- OPTIMIZE SUMMARY ---\n")
    print(f"Sweep CSV:     {sweep_csv}")
    print(f"Ranked CSV:    {ranked_csv}")
    print(f"WF results:    {wf_csv}")
    if inp.report_html:
        print(f"Report HTML:   {inp.report_html}")

    if best:
        print("\nBest config after filters (by {}):".format(inp.rank_by))
        print(json.dumps({k: v for k, v in best.items() if k in (
            "fast","slow","hysteresis_bps","cooldown_bars","qty_eur","pair","resample",
            "oos_total_return_pct_mean","oos_total_return_pct_agg",
            "oos_cagr_pct_mean","oos_cagr_pct_agg",
            "oos_calmar_mean","oos_calmar_agg",
        )}, ensure_ascii=False, indent=2))
    if final_metrics:
        print("\nFinal backtest artifacts:")
        print(json.dumps(final_metrics, ensure_ascii=False, indent=2))

    return {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "best": best,
        "final": final_metrics,
        "report_html": (str(inp.report_html) if inp.report_html else None),
    }
