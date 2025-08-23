# src/backtest/optimize.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

import numpy as np
import pandas as pd

from .vectorized_bt import _fetch_exmo_candles, _resample_ohlcv
from .sweep import run_sweep, SweepCfg, _parse_int_list, _parse_float_list
from .robustness import compute_stability
from .walkforward import WFConfig, _simulate_on_df


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
    out_dir: Path = Path("data/optimize")
    verbose: bool = False


def _wf_on_df(df: pd.DataFrame, base_cfg: WFConfig) -> Dict[str, Any]:
    """
    Walk-forward по уже загруженному df (без сетевых запросов).
    Используем фиксированные параметры стратегии; "обучения" нет,
    поэтому считаем метрики на валид. окнах при нарастающем train.
    """
    n = len(df)
    folds = int(base_cfg.folds)
    min_train = int(base_cfg.min_train_bars)
    min_valid = int(base_cfg.min_valid_bars)

    # считаем реальное число фолдов, которое помещается
    real_folds = 0
    for k in range(folds):
        train_end = min_train + k * min_valid
        valid_end = train_end + min_valid
        if valid_end <= n:
            real_folds += 1
        else:
            break

    if real_folds == 0:
        raise RuntimeError("Not enough bars for walk-forward.")

    # собираем метрики по каждому фолду
    fold_metrics: List[Dict[str, float]] = []
    for k in range(real_folds):
        train_end = min_train + k * min_valid
        valid_end = train_end + min_valid
        valid_df = df.iloc[train_end:valid_end]

        wfc = WFConfig(
            pair=base_cfg.pair, span=base_cfg.span, resample=base_cfg.resample,
            fast=base_cfg.fast, slow=base_cfg.slow,
            hysteresis_bps=base_cfg.hysteresis_bps, cooldown_bars=base_cfg.cooldown_bars,
            enter_on_start=base_cfg.enter_on_start,
            fee_bps=base_cfg.fee_bps, slip_bps=base_cfg.slip_bps, qty_eur=base_cfg.qty_eur,
            max_daily_loss_bps=base_cfg.max_daily_loss_bps,
        )
        m = _simulate_on_df(valid_df, wfc)
        fold_metrics.append(m)

    # усредняем
    def _mean(key: str) -> float:
        vals = [float(x.get(key, 0.0)) for x in fold_metrics if key in x]
        return float(np.mean(vals)) if vals else 0.0

    summary = {
        "pair": base_cfg.pair,
        "resample": base_cfg.resample,
        "fast": base_cfg.fast, "slow": base_cfg.slow,
        "hysteresis_bps": base_cfg.hysteresis_bps,
        "cooldown_bars": base_cfg.cooldown_bars,
        "fee_bps": base_cfg.fee_bps, "slip_bps": base_cfg.slip_bps,
        "qty_eur": base_cfg.qty_eur,
        "max_daily_loss_bps": base_cfg.max_daily_loss_bps,
        "folds": real_folds,
        "oos_total_return_pct_mean": _mean("total_return_pct"),
        "oos_total_return_pct_std": float(np.std([x.get("total_return_pct", 0.0) for x in fold_metrics], ddof=1)) if real_folds > 1 else 0.0,
        "oos_max_drawdown_pct_mean": _mean("max_drawdown_pct"),
        "oos_winrate_pct_mean": _mean("winrate_pct"),
        "oos_profit_factor_mean": _mean("profit_factor"),
        "oos_sharpe_mean": _mean("sharpe"),
        "oos_cagr_pct_mean": _mean("cagr_pct"),
        "oos_calmar_mean": _mean("calmar"),
    }
    return summary


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
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    # 1) Sweep (без артефактов, одноразовая загрузка свечей)
    sweep_csv = run_sweep(SweepCfg(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list,
        cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        out_dir=out_dir, sort_by=robust_metric, top_n=wf_top_n,
        save_per_config_csv=False, save_per_config_metrics=False,
        quiet_runs=(not verbose), refetch_per_config=False,
    ))

    # 2) Robustness ranking
    ranked = compute_stability(
        csv_path=Path(sweep_csv),
        min_trades=min_trades, metric=robust_metric,
        d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
    )
    ranked_csv = out_dir / f"ranked_{pair.replace('/','_')}_{(resample or 'raw')}_{ts}.csv"
    ranked.to_csv(ranked_csv, index=False)
    ranked_top = ranked.head(wf_top_n).copy()

    # 3) Загружаем свечи один раз для WF
    base = _fetch_exmo_candles(pair, span)
    df = _resample_ohlcv(base, resample) if resample else base

    # 4) Walk-forward на топ-N конфигурациях (без сетевых запросов)
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
            out_dir=out_dir,
            out_json=None, out_csv=None,
        )
        summary = _wf_on_df(df, wfc)
        wf_rows.append({
            **{k: row[k] for k in ["fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur"] if k in row},
            **summary,
        })

    wf_df = pd.DataFrame(wf_rows)
    wf_csv = out_dir / f"wf_{pair.replace('/','_')}_{(resample or 'raw')}_{ts}.csv"
    wf_df.to_csv(wf_csv, index=False)

    # 5) Report JSON (минимум ссылок на файлы и сводки)
    report = {
        "config": {
            "pair": pair, "span": span, "resample": resample,
            "fee_bps": fee_bps, "slip_bps": slip_bps, "max_daily_loss_bps": max_daily_loss_bps,
            "grid": {
                "fast_list": fast_list, "slow_list": slow_list,
                "hyst_list": hyst_list, "cooldown_list": cooldown_list,
                "qty_list": qty_list,
            },
            "robustness": {
                "metric": robust_metric, "min_trades": min_trades,
                "d_fast": d_fast, "d_slow": d_slow, "d_hyst": d_hyst, "d_cd": d_cd,
            },
            "wf": {"wf_top_n": wf_top_n, "folds": folds, "min_train_bars": min_train_bars, "min_valid_bars": min_valid_bars},
        },
        "artifacts": {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": str(wf_csv),
        },
        "tops_preview": ranked_top.head(wf_top_n).to_dict(orient="records"),
        "wf_preview": wf_df.sort_values("oos_profit_factor_mean", ascending=False).head(wf_top_n).to_dict(orient="records"),
    }
    report_json = out_dir / f"report_{pair.replace('/','_')}_{(resample or 'raw')}_{ts}.json"
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Объект для вывода в консоль вызывающей командой
    return {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "report_json": str(report_json),
        "ranked_head": ranked_top,
        "wf_head": wf_df.sort_values("oos_profit_factor_mean", ascending=False).head(wf_top_n),
    }
