# src/backtest/optimize.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal, Tuple

import json
import time
import inspect
import pandas as pd

from .robustness import compute_stability
from .walkforward import WFConfig, run_walkforward
from ..report.html_report import ReportInputs, render_report


@dataclass
class OptimizeInputs:
    pair: str
    span: str
    resample: str
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int

    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]

    metric: Literal["calmar", "profit_factor", "total_return_pct", "sharpe", "cagr_pct"] = "calmar"
    min_trades: int = 0
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2

    wf_top_n: int = 5
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    wf_min_pf: float = 1.0
    wf_min_return: float = 0.0      # доля (0.05 = +5%)
    wf_max_dd: float = 0.35         # доля (0.35 = -35%)
    wf_min_folds: int = 3

    # Расширенные фильтры WF
    wf_min_winrate: float = 0.0     # %
    wf_min_sharpe: float = float("-inf")
    wf_min_cagr: float = float("-inf")   # %
    wf_min_calmar: float = float("-inf") # «сырые» единицы
    wf_min_trades: int = 0
    wf_max_exposure: float = 100.0  # %

    rank_by: str = "oos_total_return_pct_mean"
    final_backtest: bool = False


def _sweep_once(inp: OptimizeInputs, out_dir: Path) -> Path:
    """Запуск sweep и возврат пути к CSV."""
    from .sweep import run_sweep, SweepCfg
    scfg = SweepCfg(
        pair=inp.pair, span=inp.span, resample=inp.resample,
        fee_bps=inp.fee_bps, slip_bps=inp.slip_bps, qty_list=inp.qty_list,
        fast_list=inp.fast_list, slow_list=inp.slow_list,
        hyst_list=inp.hyst_list, cooldown_list=inp.cooldown_list,
        max_daily_loss_bps=inp.max_daily_loss_bps,
        sort_by=inp.metric, top_n=0,  # полный CSV без усечения
        out_dir=out_dir,              # Path, а не str
    )
    return Path(run_sweep(scfg))


def _wf_for_top(ranked_csv: Path, top_n: int, inp: OptimizeInputs, out_dir: Path) -> Path:
    ranked = pd.read_csv(ranked_csv)
    top = ranked.head(int(top_n)).copy()
    rows = []
    for _, r in top.iterrows():
        wcfg = WFConfig(
            pair=str(r.get("pair", inp.pair)),
            span=inp.span,
            resample=inp.resample,
            fast=int(r["fast"]),
            slow=int(r["slow"]),
            hysteresis_bps=int(r["hysteresis_bps"]),
            cooldown_bars=int(r["cooldown_bars"]),
            fee_bps=int(r.get("fee_bps", inp.fee_bps)),
            slip_bps=int(r.get("slip_bps", inp.slip_bps)),
            qty_eur=float(r.get("qty_eur", inp.qty_list[0] if inp.qty_list else 50.0)),
            folds=inp.folds,
            min_train_bars=inp.min_train_bars,
            min_valid_bars=inp.min_valid_bars,
            enter_on_start=False,
            max_daily_loss_bps=inp.max_daily_loss_bps,
        )
        res = run_walkforward(wcfg, out_dir=None, print_json=False)
        rows.append({
            "fast": wcfg.fast,
            "slow": wcfg.slow,
            "hysteresis_bps": wcfg.hysteresis_bps,
            "cooldown_bars": wcfg.cooldown_bars,
            "qty_eur": wcfg.qty_eur,
            **res
        })
    wf_df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    wf_csv = out_dir / f"wf_{inp.pair}_{inp.resample}_{time.strftime('%Y%m%d-%H%M%S')}.csv"
    wf_df.to_csv(wf_csv, index=False)
    return wf_csv


def _apply_wf_filters(wf_df: pd.DataFrame, inp: OptimizeInputs) -> pd.DataFrame:
    df = wf_df.copy()

    # Базовые фильтры
    if "oos_profit_factor_mean" in df.columns:
        df = df[df["oos_profit_factor_mean"] >= inp.wf_min_pf]
    if "oos_total_return_pct_mean" in df.columns:
        df = df[df["oos_total_return_pct_mean"] >= inp.wf_min_return]
    if "oos_max_drawdown_pct_mean" in df.columns:
        df = df[df["oos_max_drawdown_pct_mean"] >= -abs(inp.wf_max_dd)]
    if "folds" in df.columns:
        df = df[df["folds"] >= inp.wf_min_folds]

    # Расширенные фильтры
    if "oos_winrate_pct_mean" in df.columns:
        df = df[df["oos_winrate_pct_mean"] >= inp.wf_min_winrate]
    if "oos_sharpe_mean" in df.columns and inp.wf_min_sharpe != float("-inf"):
        df = df[df["oos_sharpe_mean"] >= inp.wf_min_sharpe]
    if "oos_cagr_pct_mean" in df.columns and inp.wf_min_cagr != float("-inf"):
        df = df[df["oos_cagr_pct_mean"] >= inp.wf_min_cagr]
    # calmar может быть «в процентах» — нормализуем к сырым единицам
    if "oos_calmar_mean" in df.columns and inp.wf_min_calmar != float("-inf"):
        df = df[(df["oos_calmar_mean"] / 100.0) >= inp.wf_min_calmar]
    if "oos_trades_mean" in df.columns and inp.wf_min_trades > 0:
        df = df[df["oos_trades_mean"] >= inp.wf_min_trades]
    if "oos_exposure_pct_mean" in df.columns and inp.wf_max_exposure < 100.0:
        df = df[df["oos_exposure_pct_mean"] <= inp.wf_max_exposure]

    return df


def _select_final_row(wf_df: pd.DataFrame, inp: OptimizeInputs) -> pd.Series:
    sel = _apply_wf_filters(wf_df, inp)

    if sel.empty:
        # если всё вырезали — ранжируем по доступной метрике на полном наборе
        if "oos_total_return_pct_agg" in wf_df.columns and inp.rank_by.startswith("oos_total_return_pct"):
            rank_col = "oos_total_return_pct_agg"
        else:
            rank_col = inp.rank_by
        sel = wf_df.copy()
    else:
        rank_col = inp.rank_by
        if rank_col.endswith("_mean"):
            cand = f"{rank_col[:-5]}_agg"
            if cand in sel.columns:
                rank_col = cand

    sel = sel.sort_values(by=rank_col, ascending=False, kind="mergesort")
    return sel.iloc[0]


def _make_btconfig_kwargs(
    BtConfig,
    *,
    pair: str, span: str, resample: str,
    fast: int, slow: int, hysteresis_bps: int, cooldown_bars: int,
    fee_bps: int, slip_bps: int, qty_eur: float,
    max_daily_loss_bps: int, out_dir: str,
) -> Dict[str, Any]:
    """
    Совместимость с разными версиями BtConfig:
    - где-то есть 'resample', где-то 'resample_rule', где-то нет вовсе
    - 'enter_on_start' и 'out_dir' передаём только если они есть в сигнатуре
    """
    sig = inspect.signature(BtConfig)
    params = set(sig.parameters.keys())

    kw = dict(
        pair=pair, span=span,
        fast=fast, slow=slow,
        hysteresis_bps=hysteresis_bps, cooldown_bars=cooldown_bars,
        fee_bps=fee_bps, slip_bps=slip_bps, qty_eur=qty_eur,
        max_daily_loss_bps=max_daily_loss_bps,
    )

    if "enter_on_start" in params:
        kw["enter_on_start"] = False

    if "resample" in params:
        kw["resample"] = resample
    elif "resample_rule" in params:
        kw["resample_rule"] = resample

    if "out_dir" in params:
        kw["out_dir"] = out_dir

    return kw


def _persist_and_sanitize_metrics(
    metrics: Dict[str, Any],
    out_root: Path,
    pair: str, resample: str,
    fast: int, slow: int, hyst: int, cd: int, qty: float
) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """
    - Сохраняем любые DataFrame из metrics в CSV (если нет путей),
      проставляем trades_csv / equity_csv.
    - Удаляем несериализуемые объекты из словаря.
    - Возвращаем (чистый_metrics, paths).
    """
    base = f"final_{pair}_{resample}_{fast}-{slow}_h{hyst}_cd{cd}_q{int(qty)}"
    out_root.mkdir(parents=True, exist_ok=True)

    trades_csv = metrics.get("trades_csv")
    equity_csv = metrics.get("equity_csv")

    cleaned: Dict[str, Any] = {}
    extra_csv_paths: Dict[str, str] = {}

    for k, v in metrics.items():
        if isinstance(v, pd.DataFrame):
            # Решаем, куда писать
            if "trade" in k and not trades_csv:
                path = out_root / f"{base}_trades.csv"
                v.to_csv(path, index=False)
                trades_csv = str(path)
            elif "equity" in k and not equity_csv:
                path = out_root / f"{base}_equity.csv"
                v.to_csv(path, index=False)
                equity_csv = str(path)
            else:
                path = out_root / f"{base}_{k}.csv"
                v.to_csv(path, index=False)
                extra_csv_paths[k] = str(path)
            continue
        cleaned[k] = v

    # Если в metrics не было DF, но пути не заданы — оставляем как есть (может их вернул сам бэктест)
    if trades_csv is not None:
        cleaned["trades_csv"] = trades_csv
    if equity_csv is not None:
        cleaned["equity_csv"] = equity_csv
    if extra_csv_paths:
        cleaned["extra_csv"] = extra_csv_paths

    return cleaned, {"trades_csv": trades_csv, "equity_csv": equity_csv}


def _json_default(o: Any):
    # Универсальный сериализатор для numpy/pandas-типов и прочего
    try:
        import numpy as np  # локальный импорт, чтобы не держать глобальную зависимость
        if isinstance(o, np.generic):
            return o.item()
    except Exception:
        pass
    if isinstance(o, (pd.Timestamp, )):
        return o.isoformat()
    if hasattr(o, "tolist"):
        try:
            return o.tolist()
        except Exception:
            pass
    return str(o)


def run_optimize(
    pair: str,
    span: str,
    resample: str,
    fast_list: List[int], slow_list: List[int],
    hyst_list: List[int], cooldown_list: List[int], qty_list: List[float],
    fee_bps: int, slip_bps: int, max_daily_loss_bps: int,
    metric: str, min_trades: int, d_fast: int, d_slow: int, d_hyst: int, d_cd: int,
    wf_top_n: int, folds: int, min_train_bars: int, min_valid_bars: int,
    wf_min_pf: float, wf_min_return: float, wf_max_dd: float, wf_min_folds: int,
    rank_by: str, final_backtest: bool, out_dir: str,
    # новые фильтры:
    wf_min_winrate: float = 0.0, wf_min_sharpe: float = float("-inf"),
    wf_min_cagr: float = float("-inf"), wf_min_calmar: float = float("-inf"),
    wf_min_trades: int = 0, wf_max_exposure: float = 100.0,
    report_html: Optional[str] = None,
) -> Dict[str, Any]:
    out_root = Path(out_dir) if out_dir else Path("data/optimize")
    out_root.mkdir(parents=True, exist_ok=True)

    inp = OptimizeInputs(
        pair=pair, span=span, resample=resample,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list, cooldown_list=cooldown_list, qty_list=qty_list,
        metric=metric, min_trades=min_trades, d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        wf_top_n=wf_top_n, folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        wf_min_pf=wf_min_pf, wf_min_return=wf_min_return, wf_max_dd=wf_max_dd, wf_min_folds=wf_min_folds,
        rank_by=rank_by, final_backtest=final_backtest,
        wf_min_winrate=wf_min_winrate, wf_min_sharpe=wf_min_sharpe, wf_min_cagr=wf_min_cagr,
        wf_min_calmar=wf_min_calmar, wf_min_trades=wf_min_trades, wf_max_exposure=wf_max_exposure,
    )

    # 1) Sweep
    sweep_csv = _sweep_once(inp, out_root)

    # 2) Robustness
    ranked_csv = out_root / f"ranked_{sweep_csv.name.replace('sweep_', '')}"
    ranked = compute_stability(
        csv_path=sweep_csv,
        min_trades=min_trades, metric=metric,
        d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
    )
    ranked.to_csv(ranked_csv, index=False)

    # 3) WF для top-N
    wf_csv = _wf_for_top(ranked_csv, inp.wf_top_n, inp, out_root)
    wf_df = pd.read_csv(wf_csv)

    # 4) Фильтры + выбор лучшего
    best = _select_final_row(wf_df, inp)

    result: Dict[str, Any] = {
        "pair": pair,
        "resample": resample,
        "fast": int(best["fast"]),
        "slow": int(best["slow"]),
        "hysteresis_bps": int(best["hysteresis_bps"]),
        "cooldown_bars": int(best["cooldown_bars"]),
        "fee_bps": fee_bps,
        "slip_bps": slip_bps,
        "qty_eur": float(best.get("qty_eur", qty_list[0] if qty_list else 50.0)),
        "max_daily_loss_bps": max_daily_loss_bps,
        "folds": int(best.get("folds", folds)),
        "wf_rank_by": inp.rank_by,
        "oos_total_return_pct_mean": float(best.get("oos_total_return_pct_mean", 0.0)),
        "oos_total_return_pct_agg": float(best.get("oos_total_return_pct_agg", 0.0)),
        "oos_max_drawdown_pct_mean": float(best.get("oos_max_drawdown_pct_mean", 0.0)),
        "oos_max_drawdown_pct_agg": float(best.get("oos_max_drawdown_pct_agg", 0.0)),
        "oos_profit_factor_mean": float(best.get("oos_profit_factor_mean", 0.0)),
        "oos_winrate_pct_mean": float(best.get("oos_winrate_pct_mean", 0.0)),
        "oos_sharpe_mean": float(best.get("oos_sharpe_mean", 0.0)),
        "oos_cagr_pct_mean": float(best.get("oos_cagr_pct_mean", 0.0)),
        "oos_cagr_pct_agg": float(best.get("oos_cagr_pct_agg", 0.0)),
        "oos_calmar_mean": float(best.get("oos_calmar_mean", 0.0)),
        "oos_calmar_agg": float(best.get("oos_calmar_agg", 0.0)),
    }

    # 5) Финальный бэктест (опционально)
    final_paths: Dict[str, Optional[str]] = {}
    if inp.final_backtest:
        from .vectorized_bt import run_backtest_vectorized, BtConfig
        bt_kwargs = _make_btconfig_kwargs(
            BtConfig,
            pair=pair, span=span, resample=resample,
            fast=result["fast"], slow=result["slow"],
            hysteresis_bps=result["hysteresis_bps"], cooldown_bars=result["cooldown_bars"],
            fee_bps=fee_bps, slip_bps=slip_bps, qty_eur=result["qty_eur"],
            max_daily_loss_bps=max_daily_loss_bps, out_dir=str(out_root),
        )
        bcfg = BtConfig(**bt_kwargs)
        raw_metrics = run_backtest_vectorized(bcfg)

        # Сохраняем DF → CSV (если нужно) и чистим словарь от несериализуемых объектов
        clean_metrics, paths = _persist_and_sanitize_metrics(
            raw_metrics, out_root,
            pair, resample, result["fast"], result["slow"],
            result["hysteresis_bps"], result["cooldown_bars"], result["qty_eur"]
        )

        final_paths = {
            "trades_csv": paths.get("trades_csv") or clean_metrics.get("trades_csv"),
            "equity_csv": paths.get("equity_csv") or clean_metrics.get("equity_csv"),
            "metrics_json": str(out_root / f"final_{pair}_{resample}_{result['fast']}-{result['slow']}_h{result['hysteresis_bps']}_cd{result['cooldown_bars']}_q{int(result['qty_eur'])}_metrics.json"),
        }
        with open(final_paths["metrics_json"], "w", encoding="utf-8") as f:
            json.dump(clean_metrics, f, ensure_ascii=False, indent=2, default=_json_default)
        result["final_metrics"] = clean_metrics

    # 6) HTML-отчёт
    if report_html or final_paths:
        out_html = Path(report_html) if report_html else (out_root / f"report_{pair}_{resample}.html")
        out_html.parent.mkdir(parents=True, exist_ok=True)
        ri = ReportInputs(
            sweep_csv=sweep_csv, ranked_csv=ranked_csv, wf_csv=wf_csv,
            final_equity_csv=final_paths.get("equity_csv"),
            final_trades_csv=final_paths.get("trades_csv"),
            out_html=out_html,
        )
        render_report(ri)
        result["report_html"] = str(out_html)

    # Короткая сводка
    print("\n--- OPTIMIZE SUMMARY ---\n")
    print(f"Sweep CSV:     {sweep_csv}")
    print(f"Ranked CSV:    {ranked_csv}")
    print(f"WF results:    {wf_csv}")
    if "report_html" in result:
        print(f"Report HTML:   {result['report_html']}")
    print("\nBest config after filters (by {}):".format(inp.rank_by))
    print(json.dumps({
        "fast": result["fast"], "slow": result["slow"],
        "hysteresis_bps": result["hysteresis_bps"], "cooldown_bars": result["cooldown_bars"],
        "qty_eur": result["qty_eur"], "pair": pair, "resample": resample,
        "oos_total_return_pct_mean": result["oos_total_return_pct_mean"],
        "oos_total_return_pct_agg": result["oos_total_return_pct_agg"],
        "oos_cagr_pct_mean": result["oos_cagr_pct_mean"],
        "oos_cagr_pct_agg": result["oos_cagr_pct_agg"],
        "oos_calmar_mean": result["oos_calmar_mean"],
        "oos_calmar_agg": result["oos_calmar_agg"],
    }, ensure_ascii=False, indent=2))

    return result
