# src/backtest/optimize.py
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .sweep import SweepCfg, run_sweep
from .compat import (
    fetch_exmo_candles_cached,
    normalize_resample_rule,
    resample_ohlc,
    SimConfig,
    simulate_on_df,
)
from .walkforward import WFConfig, run_walkforward
from .robustness import compute_stability


@dataclass
class OptimizeInput:
    pair: str
    span: str
    resample: str

    fast_list: Sequence[int]
    slow_list: Sequence[int]
    hyst_list: Sequence[int]
    cooldown_list: Sequence[int]
    qty_list: Sequence[float]

    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int

    metric: str = "calmar"
    min_trades: int = 0
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2

    wf_top_n: int = 10
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    wf_min_pf: float = 0.0
    wf_min_return: float = -1.0
    wf_max_dd: float = 1.0
    wf_min_winrate: float = 0.0
    wf_min_sharpe: float = -1e9
    wf_min_cagr: float = -1e9
    wf_min_calmar: float = -1e9
    wf_min_folds: int = 1
    wf_min_trades: int = 0
    wf_max_exposure: float = 100.0

    rank_by: str = "oos_total_return_pct_mean"  # one of enum accepted by main.py
    final_backtest: bool = False

    out_dir: Path | str = Path("data/optimize")
    report_html: Optional[Path] = None


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return np.nan


def _filter_wf(df: pd.DataFrame, inp: OptimizeInput) -> pd.DataFrame:
    w = df.copy()
    # условия соответствуют аргументам CLI
    conds = [
        w["folds"] >= inp.wf_min_folds,
        w["oos_profit_factor_mean"] >= inp.wf_min_pf,
        w["oos_total_return_pct_mean"] >= inp.wf_min_return,
        w["oos_max_drawdown_pct_mean"] >= -abs(inp.wf_max_dd),  # max_dd is negative
        w["oos_winrate_pct_mean"] >= inp.wf_min_winrate,
        w["oos_sharpe_mean"] >= inp.wf_min_sharpe,
        w["oos_cagr_pct_mean"] >= inp.wf_min_cagr,
        w["oos_calmar_mean"] >= inp.wf_min_calmar,
    ]
    if "oos_trades_mean" in w.columns and inp.wf_min_trades > 0:
        conds.append(w["oos_trades_mean"] >= inp.wf_min_trades)
    if "oos_exposure_pct_mean" in w.columns and inp.wf_max_exposure < 100.0:
        conds.append(w["oos_exposure_pct_mean"] <= inp.wf_max_exposure)

    mask = np.logical_and.reduce(conds) if conds else np.array([True] * len(w))
    return w.loc[mask].reset_index(drop=True)


def _rank_key_name(rank_by: str) -> str:
    # В main.py доступные значения уже ограничены, но на всякий случай проверим:
    allowed = {
        "oos_profit_factor_mean",
        "oos_total_return_pct_mean",
        "oos_calmar_mean",
        "oos_sharpe_mean",
        "oos_cagr_pct_mean",
    }
    if rank_by not in allowed:
        # fallback по здравому смыслу
        return "oos_total_return_pct_mean"
    return rank_by


def _make_report_html(path: Path, sweep_csv: Optional[Path], ranked_csv: Optional[Path],
                      wf_csv: Optional[Path], final_block: Optional[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts: List[str] = [
        "<!doctype html><meta charset='utf-8'><title>Optimize Report</title>",
        "<style>body{font:14px system-ui,Roboto,Arial} table{border-collapse:collapse;margin:12px 0} td,th{border:1px solid #ddd;padding:4px 8px} h2{margin-top:24px}</style>",
        "<h1>Optimize Report</h1>",
        f"<p>Generated: {html.escape(datetime.now().isoformat(sep=' ', timespec='seconds'))}</p>"
    ]

    def _tbl(title: str, df: Optional[pd.DataFrame], max_rows: int = 50):
        if df is None or df.empty:
            parts.append(f"<h2>{html.escape(title)}</h2><p><em>empty</em></p>")
            return
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts.append(df.head(max_rows).to_html(index=False, border=0))

    if sweep_csv and Path(sweep_csv).exists():
        try:
            df = pd.read_csv(sweep_csv)
        except Exception:
            df = None
        _tbl("Sweep (head)", df)

    if ranked_csv and Path(ranked_csv).exists():
        try:
            df = pd.read_csv(ranked_csv)
        except Exception:
            df = None
        _tbl("Ranked (head)", df)

    if wf_csv and Path(wf_csv).exists():
        try:
            df = pd.read_csv(wf_csv)
        except Exception:
            df = None
        _tbl("Walk-forward (head)", df)

    if final_block:
        parts.append("<h2>Final backtest</h2>")
        parts.append("<pre>" + html.escape(json.dumps(final_block, ensure_ascii=False, indent=2)) + "</pre>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def run_optimize(
    *,
    pair: str,
    span: str,
    resample: str,
    fast_list: Sequence[int],
    slow_list: Sequence[int],
    hyst_list: Sequence[int],
    cooldown_list: Sequence[int],
    qty_list: Sequence[float],
    fee_bps: int,
    slip_bps: int,
    max_daily_loss_bps: int,

    metric: str = "calmar",
    min_trades: int = 0,
    d_fast: int = 2,
    d_slow: int = 5,
    d_hyst: int = 5,
    d_cd: int = 2,

    wf_top_n: int = 10,
    folds: int = 4,
    min_train_bars: int = 150,
    min_valid_bars: int = 100,

    wf_min_pf: float = 0.0,
    wf_min_return: float = -1.0,
    wf_max_dd: float = 1.0,
    wf_min_winrate: float = 0.0,
    wf_min_sharpe: float = -1e9,
    wf_min_cagr: float = -1e9,
    wf_min_calmar: float = -1e9,
    wf_min_folds: int = 1,
    wf_min_trades: int = 0,
    wf_max_exposure: float = 100.0,

    rank_by: str = "oos_total_return_pct_mean",
    final_backtest: bool = False,

    out_dir: Path | str = Path("data/optimize"),
    report_html: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Полный цикл: свип -> робастность -> WF по топ-N -> финальный БТ (опционально) -> HTML
    Возвращает сводный словарь с путями артефактов.
    """
    rr = normalize_resample_rule(resample)
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1) sweep
    sweep_path = run_sweep(SweepCfg(
        pair=pair, span=span, resample=rr,
        fast_list=fast_list, slow_list=slow_list,
        hyst_list=hyst_list, cooldown_list=cooldown_list,
        qty_list=qty_list, fee_bps=fee_bps, slip_bps=slip_bps,
        max_daily_loss_bps=max_daily_loss_bps,
        out_dir=out_root,
    ))
    sweep_csv = Path(sweep_path)

    # 2) robustness ranking
    try:
        ranked_df = compute_stability(
            csv_path=sweep_csv,
            min_trades=min_trades, metric=metric,
            d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        )
    except RuntimeError as e:
        # Частый кейс: свип весь с ошибками -> прекратить
        result = {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(out_root / f"ranked_{pair}_{rr}_{_now_stamp()}.csv"),
            "wf_csv": None,
            "report_html": str(report_html) if report_html else None,
            "message": str(e) if str(e) else "Ranked table is empty or contains only errors; stopping before WF.",
        }
        # Пишем пустой ranked, чтобы было куда смотреть
        pd.DataFrame().to_csv(result["ranked_csv"], index=False)
        if report_html:
            _make_report_html(Path(report_html), sweep_csv, Path(result["ranked_csv"]), None, None)
        return result

    ranked_csv = out_root / f"ranked_{pair}_{rr}_{_now_stamp()}.csv"
    ranked_df.to_csv(ranked_csv, index=False)

    if ranked_df.empty:
        result = {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": None,
            "report_html": str(report_html) if report_html else None,
            "message": "Ranked table is empty or contains only errors; stopping before WF.",
        }
        if report_html:
            _make_report_html(Path(report_html), sweep_csv, ranked_csv, None, None)
        return result

    # 3) take top-N (by robustness metric already) and run WF for each
    top = ranked_df.head(max(1, int(wf_top_n))).copy()
    wf_rows: List[Dict[str, Any]] = []

    for _, r in top.iterrows():
        fast = int(r["fast"])
        slow = int(r["slow"])
        hyst = int(r["hysteresis_bps"])
        cd = int(r["cooldown_bars"])
        qty = float(r["qty_eur"])

        wcfg = WFConfig(
            pair=pair, span=span, resample=rr,
            fast=fast, slow=slow, hysteresis_bps=hyst, cooldown_bars=cd,
            fee_bps=fee_bps, slip_bps=slip_bps, qty_eur=qty,
            max_daily_loss_bps=max_daily_loss_bps,
            folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
            out_dir=None,  # CSVы по WF в сводной таблице ниже
        )
        try:
            out = run_walkforward(wcfg)
        except Exception as e:
            out = {
                "pair": pair, "resample": rr,
                "fast": fast, "slow": slow, "hysteresis_bps": hyst, "cooldown_bars": cd,
                "fee_bps": fee_bps, "slip_bps": slip_bps, "qty_eur": qty,
                "max_daily_loss_bps": max_daily_loss_bps,
                "folds": 0,
                "oos_total_return_pct_mean": np.nan,
                "oos_total_return_pct_std": np.nan,
                "oos_max_drawdown_pct_mean": np.nan,
                "oos_winrate_pct_mean": np.nan,
                "oos_profit_factor_mean": np.nan,
                "oos_sharpe_mean": np.nan,
                "oos_cagr_pct_mean": np.nan,
                "oos_calmar_mean": np.nan,
                "error": str(e),
            }
        wf_rows.append(out)

    wf_df = pd.DataFrame(wf_rows)
    wf_csv = out_root / f"wf_{pair}_{rr}_{_now_stamp()}.csv"
    wf_df.to_csv(wf_csv, index=False)

    # 4) WF filters + pick best
    filtered = _filter_wf(wf_df, OptimizeInput(
        pair=pair, span=span, resample=rr,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list,
        cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        metric=metric, min_trades=min_trades, d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        wf_top_n=wf_top_n, folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        wf_min_pf=wf_min_pf, wf_min_return=wf_min_return, wf_max_dd=wf_max_dd, wf_min_winrate=wf_min_winrate,
        wf_min_sharpe=wf_min_sharpe, wf_min_cagr=wf_min_cagr, wf_min_calmar=wf_min_calmar,
        wf_min_folds=wf_min_folds, wf_min_trades=wf_min_trades, wf_max_exposure=wf_max_exposure,
        rank_by=rank_by, final_backtest=final_backtest, out_dir=out_root, report_html=report_html
    ))
    pool = filtered if not filtered.empty else wf_df
    key = _rank_key_name(rank_by)
    best = pool.sort_values(by=[key], ascending=False).head(1)

    final_block: Optional[dict] = None

    # 5) final backtest on full history
    if final_backtest and not best.empty:
        b = best.iloc[0]
        fast = int(b["fast"]); slow = int(b["slow"])
        hyst = int(b["hysteresis_bps"]); cd = int(b["cooldown_bars"]); qty = float(b["qty_eur"])

        # candles full resampled
        raw = fetch_exmo_candles_cached(pair, span)
        df = resample_ohlc(raw, rr)
        scfg = SimConfig(
            fast=fast, slow=slow, hysteresis_bps=hyst, cooldown_bars=cd,
            fee_bps=fee_bps, slip_bps=slip_bps, qty_eur=qty,
            max_daily_loss_bps=max_daily_loss_bps, resample=rr,
        )
        trades_df, equity_df, metrics = simulate_on_df(df, scfg)

        # filenames
        tag = f"{pair}_{rr}_{fast}-{slow}_h{hyst}_cd{cd}_q{int(qty) if float(qty).is_integer() else qty}"
        trades_csv = out_root / f"final_{tag}_trades.csv"
        equity_csv = out_root / f"final_{tag}_equity.csv"
        trades_df.to_csv(trades_csv, index=False)
        equity_df.to_csv(equity_csv, index=False)

        final_block = {
            "metrics": metrics,
            "trades_csv": str(trades_csv),
            "equity_csv": str(equity_csv),
        }

    # 6) report
    if report_html:
        _make_report_html(Path(report_html), sweep_csv, ranked_csv, wf_csv, final_block)

    # 7) summary
    out = {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "report_html": str(report_html) if report_html else None,
    }
    if filtered.empty and not wf_df.empty:
        out["message"] = "WF filtered count: 0 / total {}; Selected from: unfiltered".format(len(wf_df))
    return out
