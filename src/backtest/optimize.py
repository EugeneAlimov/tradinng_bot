# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import math

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

from .compat import (
    build_bt_config,
    normalize_metrics,
    normalize_resample_rule,
    run_backtest_compat,
)
from .sweep import SweepCfg, run_sweep

log = logging.getLogger(__name__)


@dataclass
class OptimizeInput:
    pair: str
    span: str
    resample: Optional[str]
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int
    metric: str = "calmar"
    min_trades: int = 0
    d_fast: int = 1
    d_slow: int = 1
    d_hyst: int = 1
    d_cd: int = 1
    wf_top_n: int = 0
    folds: int = 0
    min_train_bars: int = 0
    min_valid_bars: int = 0
    wf_min_pf: float = 0.0
    wf_min_return: float = -1e9
    wf_max_dd: float = 1e9
    wf_min_winrate: float = 0.0
    wf_min_sharpe: float = -1e9
    wf_min_cagr: float = -1e9
    wf_min_calmar: float = -1e9
    wf_min_folds: int = 0
    wf_min_trades: int = 0
    wf_max_exposure: float = 1e9
    rank_by: str = "oos_total_return_pct_mean"
    final_backtest: bool = False
    out_dir: Path = Path("data/optimize")
    report_html: Optional[Path] = None


def _read_csv_safely(path: Path) -> Optional["pd.DataFrame"]:
    if pd is None:
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        log.error("Failed to read CSV %s: %s", path, e)
        return None


def _write_html_report(path: Path, title: str, blocks: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>body{font-family:system-ui,Arial,sans-serif;padding:16px;}"
        "pre{background:#f6f8fa;padding:12px;border-radius:8px;overflow:auto}"
        "table{border-collapse:collapse}td,th{padding:6px 10px;border:1px solid #ddd}</style>",
        "</head><body>",
        f"<h1>{title}</h1>",
    ]
    html.extend(blocks)
    html.append("</body></html>")
    path.write_text("\n".join(html), encoding="utf-8")


def run_optimize(
    *,
    pair: str,
    span: str,
    resample: Optional[str],
    fast_list: List[int],
    slow_list: List[int],
    hyst_list: List[int],
    cooldown_list: List[int],
    qty_list: List[float],
    fee_bps: int,
    slip_bps: int,
    max_daily_loss_bps: int,
    metric: str = "calmar",
    min_trades: int = 0,
    d_fast: int = 1,
    d_slow: int = 1,
    d_hyst: int = 1,
    d_cd: int = 1,
    wf_top_n: int = 0,
    folds: int = 0,
    min_train_bars: int = 0,
    min_valid_bars: int = 0,
    wf_min_pf: float = 0.0,
    wf_min_return: float = -1e9,
    wf_max_dd: float = 1e9,
    wf_min_winrate: float = 0.0,
    wf_min_sharpe: float = -1e9,
    wf_min_cagr: float = -1e9,
    wf_min_calmar: float = -1e9,
    wf_min_folds: int = 0,
    wf_min_trades: int = 0,
    wf_max_exposure: float = 1e9,
    rank_by: str = "oos_total_return_pct_mean",
    final_backtest: bool = False,
    out_dir: Path = Path("data/optimize"),
    report_html: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Orchestrates sweep -> (optional) WF -> (optional) final backtest.
    Returns a dict with produced artifact paths and summary info.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Sweep
    scfg = SweepCfg(
        pair=pair,
        span=span,
        resample=resample,
        fast_list=list(fast_list),
        slow_list=list(slow_list),
        hyst_list=list(hyst_list),
        cooldown_list=list(cooldown_list),
        qty_list=list(qty_list),
        fee_bps=int(fee_bps),
        slip_bps=int(slip_bps),
        max_daily_loss_bps=int(max_daily_loss_bps),
        out_dir=out_dir,
    )
    sweep_csv = Path(run_sweep(scfg))

    # 2) Rank (simple pass-through; robust ranking module may exist in project)
    ranked_csv = out_dir / sweep_csv.name.replace("sweep_", "ranked_")
    wf_csv: Optional[Path] = None

    df = _read_csv_safely(sweep_csv)
    if df is None or df.empty:
        msg = "Sweep table is empty; stopping before WF."
        log.warning(msg)
        if report_html:
            _write_html_report(report_html, "Optimize Report", [
                f"<p>{msg}</p>",
                f"<p>Sweep CSV: <code>{sweep_csv}</code></p>",
            ])
        return {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": None,
            "report_html": str(report_html) if report_html else None,
            "message": msg,
        }

    # keep only successful rows
    if "error" in df.columns:
        df = df[(df["error"].isna()) | (df["error"] == "")]
    if df.empty:
        msg = "Ranked table is empty or contains only errors; stopping before WF."
        log.warning(msg)
        if report_html:
            _write_html_report(report_html, "Optimize Report", [
                f"<p>{msg}</p>",
                f"<p>Sweep CSV: <code>{sweep_csv}</code></p>",
            ])
        # still write an empty ranked file for consistency
        try:
            df.to_csv(ranked_csv, index=False)
        except Exception:
            pass
        return {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": None,
            "report_html": str(report_html) if report_html else None,
            "message": msg,
        }

    # naive ranking by chosen column if present, else by total_return_pct
    rank_col = rank_by if rank_by in df.columns else "total_return_pct"
    df = df.sort_values(by=rank_col, ascending=False).reset_index(drop=True)
    df.to_csv(ranked_csv, index=False)

    html_blocks = [
        f"<p>Sweep CSV: <code>{sweep_csv}</code><br>"
        f"Ranked CSV: <code>{ranked_csv}</code></p>"
    ]

    # 3) Optional walk-forward (use project module if available)
    wf_summary: Optional[Dict[str, Any]] = None
    if wf_top_n and folds and "fast" in df.columns and "slow" in df.columns:
        try:
            from .walkforward import WFConfig, run_walkforward  # type: ignore

            top = df.head(int(wf_top_n)).copy()
            # Build WF input rows
            rows: List[Dict[str, Any]] = []
            for _, r in top.iterrows():
                rows.append({
                    "fast": int(r["fast"]),
                    "slow": int(r["slow"]),
                    "hysteresis_bps": int(r.get("hysteresis_bps", 0) or 0),
                    "cooldown_bars": int(r.get("cooldown_bars", 0) or 0),
                    "qty_eur": float(r.get("qty_eur", 0) or 0.0),
                })

            wcfg = WFConfig(
                pair=pair,
                span=span,
                resample=normalize_resample_rule(resample),
                fee_bps=int(fee_bps),
                slip_bps=int(slip_bps),
                max_daily_loss_bps=int(max_daily_loss_bps),
                folds=int(folds),
                min_train_bars=int(min_train_bars),
                min_valid_bars=int(min_valid_bars),
                # filters
                wf_min_pf=float(wf_min_pf),
                wf_min_return=float(wf_min_return),
                wf_max_dd=float(wf_max_dd),
                wf_min_winrate=float(wf_min_winrate),
                wf_min_sharpe=float(wf_min_sharpe),
                wf_min_cagr=float(wf_min_cagr),
                wf_min_calmar=float(wf_min_calmar),
                wf_min_folds=int(wf_min_folds),
                wf_min_trades=int(wf_min_trades),
                wf_max_exposure=float(wf_max_exposure),
                # candidates:
                candidates=rows,
                out_dir=out_dir,
            )
            wf_res = run_walkforward(wcfg)
            wf_csv = Path(wf_res["csv"]) if isinstance(wf_res, dict) and "csv" in wf_res else None
            wf_summary = wf_res if isinstance(wf_res, dict) else None
            html_blocks.append("<h2>Walk-forward</h2>")
            html_blocks.append("<pre>" + json.dumps(wf_summary or {}, ensure_ascii=False, indent=2) + "</pre>")

        except Exception as e:
            log.warning("Walk-forward step skipped due to error: %s", e)
            html_blocks.append(f"<p><em>WF skipped:</em> {e}</p>")

    # 4) Optional final backtest for the best config (after WF if present)
    final_summary: Optional[Dict[str, Any]] = None
    if final_backtest:
        best_row = None
        if wf_summary and isinstance(wf_summary, dict) and "best" in wf_summary:
            best_row = wf_summary.get("best")
        if best_row is None:
            best_row = df.iloc[0].to_dict()

        bt_cfg = build_bt_config(
            pair=pair,
            span=span,
            resample=normalize_resample_rule(resample),
            fast=int(best_row.get("fast")),
            slow=int(best_row.get("slow")),
            hysteresis_bps=int(best_row.get("hysteresis_bps", 0) or 0),
            cooldown_bars=int(best_row.get("cooldown_bars", 0) or 0),
            qty_eur=float(best_row.get("qty_eur", 0) or 0.0),
            fee_bps=int(fee_bps),
            slip_bps=int(slip_bps),
            max_daily_loss_bps=int(max_daily_loss_bps),
        )
        out = run_backtest_compat(bt_cfg, write_csv=False)
        norm = normalize_metrics(out)

        # Save trades/equity if present
        trades_csv_path = None
        equity_csv_path = None
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        tag = f"{pair}_{normalize_resample_rule(resample) or 'raw'}_{best_row.get('fast')}-{best_row.get('slow')}_h{best_row.get('hysteresis_bps',0)}_cd{best_row.get('cooldown_bars',0)}_q{int(float(best_row.get('qty_eur',0)))}"

        if norm.get("trades_df") is not None and pd is not None:
            trades_csv_path = out_dir / f"final_{tag}_trades.csv"
            try:
                norm["trades_df"].to_csv(trades_csv_path, index=False)  # type: ignore
            except Exception as e:
                log.warning("Failed to save trades CSV: %s", e)

        if norm.get("equity_df") is not None and pd is not None:
            equity_csv_path = out_dir / f"final_{tag}_equity.csv"
            try:
                norm["equity_df"].to_csv(equity_csv_path, index=False)  # type: ignore
            except Exception as e:
                log.warning("Failed to save equity CSV: %s", e)

        final_summary = {
            "config": {
                "fast": int(best_row.get("fast")),
                "slow": int(best_row.get("slow")),
                "hysteresis_bps": int(best_row.get("hysteresis_bps", 0) or 0),
                "cooldown_bars": int(best_row.get("cooldown_bars", 0) or 0),
                "qty_eur": float(best_row.get("qty_eur", 0) or 0.0),
            },
            "metrics": norm["metrics"],
            "trades_csv": str(trades_csv_path) if trades_csv_path else None,
            "equity_csv": str(equity_csv_path) if equity_csv_path else None,
        }

        html_blocks.append("<h2>Final backtest</h2>")
        html_blocks.append("<pre>" + json.dumps(final_summary, ensure_ascii=False, indent=2) + "</pre>")

    # 5) Report
    if report_html:
        _write_html_report(report_html, "Optimize Report", html_blocks)

    return {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv) if wf_csv else None,
        "report_html": str(report_html) if report_html else None,
        "wf_summary": wf_summary,
        "final_summary": final_summary,
    }
