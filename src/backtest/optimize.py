from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import numpy as np
import pandas as pd

from .vectorized_bt import _fetch_exmo_candles, _resample_ohlcv, BtConfig, run_backtest_vectorized
from .sweep import run_sweep, SweepCfg
from .robustness import compute_stability
from .walkforward import WFConfig, run_walkforward


@dataclass
class OptimizeConfig:
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

    robust_metric: str = "calmar"
    min_trades: int = 4
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2

    wf_top_n: int = 5
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    # WF-фильтры
    wf_min_pf: Optional[float] = None
    wf_min_return_pct: Optional[float] = None
    wf_max_dd_pct: Optional[float] = None
    wf_min_winrate_pct: Optional[float] = None
    wf_min_sharpe: Optional[float] = None
    wf_min_cagr_pct: Optional[float] = None
    wf_min_calmar: Optional[float] = None
    wf_min_folds: Optional[int] = None

    # Новые, «на будущее»
    wf_min_trades: Optional[float] = None               # среднее число сделок по фолдам
    wf_max_exposure: Optional[float] = None             # средняя экспозиция (%)

    rank_by: str = "oos_profit_factor_mean"
    final_backtest: bool = False

    out_dir: Path = Path("data/optimize")
    verbose: bool = False


WF_RANK_CHOICES = {
    "oos_profit_factor_mean",
    "oos_total_return_pct_mean",
    "oos_calmar_mean",
    "oos_sharpe_mean",
    "oos_cagr_pct_mean",
}


def _apply_wf_filters(df: pd.DataFrame, cfg: OptimizeConfig) -> pd.DataFrame:
    out = df.copy()

    # folds
    if cfg.wf_min_folds is not None and "folds" in out.columns:
        out = out[out["folds"] >= int(cfg.wf_min_folds)]

    def col(name: str) -> str:
        return name if name in out.columns else ""

    filters = [
        ("oos_profit_factor_mean", cfg.wf_min_pf, "min"),
        ("oos_total_return_pct_mean", cfg.wf_min_return_pct, "min"),
        ("oos_sharpe_mean", cfg.wf_min_sharpe, "min"),
        ("oos_cagr_pct_mean", cfg.wf_min_cagr_pct, "min"),
        ("oos_calmar_mean", cfg.wf_min_calmar, "min"),
        ("oos_winrate_pct_mean", cfg.wf_min_winrate_pct, "min"),
        ("oos_trades_mean", cfg.wf_min_trades, "min"),
    ]
    for cname, thr, mode in filters:
        if thr is None or col(cname) == "":
            continue
        if mode == "min":
            out = out[out[cname].fillna(-np.inf) >= float(thr)]

    # max DD — по модулю
    if cfg.wf_max_dd_pct is not None and col("oos_max_drawdown_pct_mean"):
        out = out[out["oos_max_drawdown_pct_mean"].abs().fillna(np.inf) <= abs(float(cfg.wf_max_dd_pct))]

    # max exposure
    if cfg.wf_max_exposure is not None and col("oos_exposure_pct_mean"):
        out = out[out["oos_exposure_pct_mean"].fillna(np.inf) <= float(cfg.wf_max_exposure)]

    return out


def run_optimize(
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
    robust_metric: str,
    min_trades: int,
    d_fast: int, d_slow: int, d_hyst: int, d_cd: int,
    wf_top_n: int,
    folds: int, min_train_bars: int, min_valid_bars: int,
    out_dir: Path,
    verbose: bool = False,
    # WF фильтры
    wf_min_pf: Optional[float] = None,
    wf_min_return_pct: Optional[float] = None,
    wf_max_dd_pct: Optional[float] = None,
    wf_min_winrate_pct: Optional[float] = None,
    wf_min_sharpe: Optional[float] = None,
    wf_min_cagr_pct: Optional[float] = None,
    wf_min_calmar: Optional[float] = None,
    wf_min_folds: Optional[int] = None,
    wf_min_trades: Optional[float] = None,
    wf_max_exposure: Optional[float] = None,
    rank_by: str = "oos_profit_factor_mean",
    final_backtest: bool = False,
) -> Dict[str, Any]:

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    # 1) Sweep
    sweep_csv = run_sweep(SweepCfg(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list,
        cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        out_dir=out_dir, sort_by=robust_metric, top_n=wf_top_n,
        save_per_config_csv=False, save_per_config_metrics=False,
        quiet_runs=(not verbose), refetch_per_config=False,
    ))

    # 2) Robustness
    ranked = compute_stability(
        csv_path=Path(sweep_csv),
        min_trades=min_trades, metric=robust_metric,
        d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
    )
    ranked_csv = out_dir / f"ranked_{pair.replace('/','_')}_{(resample or 'raw')}_{ts}.csv"
    ranked.to_csv(ranked_csv, index=False)
    ranked_top = ranked.head(wf_top_n).copy()

    # 3) История один раз для WF
    base = _fetch_exmo_candles(pair, span)
    df = _resample_ohlcv(base, resample) if resample else base

    # 4) WF по топ-N
    wf_rows: List[Dict[str, Any]] = []
    for _, row in ranked_top.iterrows():
        wfc = WFConfig(
            pair=pair, span=span, resample=resample,
            fast=int(row["fast"]), slow=int(row["slow"]),
            hysteresis_bps=int(row["hysteresis_bps"]),
            cooldown_bars=int(row["cooldown_bars"]),
            enter_on_start=False,
            fee_bps=int(row.get("fee_bps", fee_bps)),
            slip_bps=int(row.get("slip_bps", slip_bps)),
            qty_eur=float(row.get("qty_eur", qty_list[0] if qty_list else 50.0)),
            max_daily_loss_bps=int(row.get("max_daily_loss_bps", max_daily_loss_bps)),
            folds=int(folds), min_train_bars=int(min_train_bars), min_valid_bars=int(min_valid_bars),
            out_dir=out_dir, out_json=None, out_csv=None,
        )
        summ = run_walkforward(wfc, df_override=df, print_json=False)
        wf_rows.append({
            "fast": int(row["fast"]),
            "slow": int(row["slow"]),
            "hysteresis_bps": int(row["hysteresis_bps"]),
            "cooldown_bars": int(row["cooldown_bars"]),
            "qty_eur": float(row.get("qty_eur", np.nan)),
            **summ,
        })

    wf_df = pd.DataFrame(wf_rows)
    wf_csv = out_dir / f"wf_{pair.replace('/','_')}_{(resample or 'raw')}_{ts}.csv"
    wf_df.to_csv(wf_csv, index=False)

    # 5) Фильтры WF
    filt_cfg = OptimizeConfig(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list, cooldown_list=cooldown_list,
        qty_list=qty_list, fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        robust_metric=robust_metric, min_trades=min_trades, d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        wf_top_n=wf_top_n, folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        wf_min_pf=wf_min_pf, wf_min_return_pct=wf_min_return_pct, wf_max_dd_pct=wf_max_dd_pct,
        wf_min_winrate_pct=wf_min_winrate_pct, wf_min_sharpe=wf_min_sharpe,
        wf_min_cagr_pct=wf_min_cagr_pct, wf_min_calmar=wf_min_calmar,
        wf_min_folds=wf_min_folds, rank_by=rank_by, final_backtest=final_backtest,
        wf_min_trades=wf_min_trades, wf_max_exposure=wf_max_exposure,
        out_dir=out_dir, verbose=verbose,
    )

    wf_filtered = _apply_wf_filters(wf_df, filt_cfg)

    # 6) Ранжирование
    if rank_by not in WF_RANK_CHOICES:
        rank_by = "oos_profit_factor_mean"

    selected_source = "filtered"
    df_for_rank = wf_filtered.copy()
    if df_for_rank.empty:
        df_for_rank = wf_df.copy()
        selected_source = "unfiltered"

    df_for_rank = df_for_rank.sort_values(rank_by, ascending=False, na_position="last")
    best_row = df_for_rank.head(1).to_dict(orient="records")[0] if not df_for_rank.empty else None

    # 7) Финальный бэктест (опционально)
    final_bt_artifacts: Dict[str, Any] = {}
    if final_backtest and best_row is not None:
        bt = BtConfig(
            pair=pair, span=span, resample_rule=resample,
            fast=int(best_row["fast"]), slow=int(best_row["slow"]),
            hysteresis_bps=int(best_row["hysteresis_bps"]),
            cooldown_bars=int(best_row["cooldown_bars"]),
            fee_bps=fee_bps, slip_bps=slip_bps,
            qty_eur=float(best_row["qty_eur"]),
            max_daily_loss_bps=max_daily_loss_bps,
            print_summary=False,
        )
        base_name = f"final_{pair.replace('/','_')}_{(resample or 'raw')}_{bt.fast}-{bt.slow}_h{bt.hysteresis_bps}_cd{bt.cooldown_bars}_q{int(bt.qty_eur)}"
        bt.out_trades_csv = out_dir / f"{base_name}_trades.csv"
        bt.out_equity_csv = out_dir / f"{base_name}_equity.csv"
        bt.out_metrics_json = out_dir / f"{base_name}_metrics.json"

        res = run_backtest_vectorized(bt)
        final_bt_artifacts = {
            "final_backtest": {
                "config": {
                    "fast": bt.fast, "slow": bt.slow, "hysteresis_bps": bt.hysteresis_bps,
                    "cooldown_bars": bt.cooldown_bars, "qty_eur": bt.qty_eur,
                },
                "metrics": res.get("metrics", {}),
                "trades_csv": str(bt.out_trades_csv),
                "equity_csv": str(bt.out_equity_csv),
                "metrics_json": str(bt.out_metrics_json),
            }
        }

    # 8) Отчёт
    report = {
        "config": {
            "pair": pair, "span": span, "resample": resample,
            "fee_bps": fee_bps, "slip_bps": slip_bps, "max_daily_loss_bps": max_daily_loss_bps,
            "grid": {
                "fast_list": fast_list, "slow_list": slow_list,
                "hyst_list": hyst_list, "cooldown_list": cooldown_list, "qty_list": qty_list,
            },
            "robustness": {
                "metric": robust_metric, "min_trades": min_trades,
                "d_fast": d_fast, "d_slow": d_slow, "d_hyst": d_hyst, "d_cd": d_cd,
            },
            "wf": {
                "wf_top_n": wf_top_n, "folds": folds,
                "min_train_bars": min_train_bars, "min_valid_bars": min_valid_bars,
                "filters.py": {
                    "wf_min_pf": wf_min_pf, "wf_min_return_pct": wf_min_return_pct,
                    "wf_max_dd_pct": wf_max_dd_pct, "wf_min_winrate_pct": wf_min_winrate_pct,
                    "wf_min_sharpe": wf_min_sharpe, "wf_min_cagr_pct": wf_min_cagr_pct,
                    "wf_min_calmar": wf_min_calmar, "wf_min_folds": wf_min_folds,
                    "wf_min_trades": wf_min_trades, "wf_max_exposure": wf_max_exposure,
                },
                "rank_by": rank_by,
            },
        },
        "artifacts": {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": str(wf_csv),
        },
        "tops_preview": ranked_top.head(wf_top_n).to_dict(orient="records"),
        "wf_preview": wf_df.sort_values(rank_by, ascending=False).head(wf_top_n).to_dict(orient="records"),
        "wf_filtered_count": int(len(wf_filtered)),
        "wf_total_count": int(len(wf_df)),
        "selected_from": selected_source,
        "selected_best": best_row,
    }
    report.update(final_bt_artifacts)

    report_json = out_dir / f"report_{pair.replace('/','_')}_{(resample or 'raw')}_{ts}.json"
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "report_json": str(report_json),
        "ranked_head": ranked_top,
        "wf_head": wf_df.sort_values(rank_by, ascending=False).head(wf_top_n),
        "wf_filtered": wf_filtered,
        "selected_best": best_row,
        "selected_from": selected_source,
        **final_bt_artifacts,
    }
