# src/backtest/optimize.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
from types import SimpleNamespace
import time
import json
import pandas as pd

from .sweep import SweepCfg, run_sweep, _parse_int_list, _parse_float_list
from .robustness import compute_stability
from .walkforward import run_walkforward  # используем как есть


@dataclass
class OptimizeInput:
    pair: str
    span: str
    resample: Optional[str]
    # свип
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]
    fee_bps: int = 10
    slip_bps: int = 2
    max_daily_loss_bps: int = 0
    # робастность
    metric: str = "calmar"
    min_trades: int = 4
    d_fast: int = 2
    d_slow: int = 5
    d_hyst: int = 5
    d_cd: int = 2
    # WF
    wf_top_n: int = 5
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100
    # WF-фильтры (по средним)
    wf_min_pf: float = 0.0
    wf_min_return: float = 0.0
    wf_max_dd: float = 1.0
    wf_min_winrate: float = 0.0
    wf_min_sharpe: float = -1e9
    wf_min_cagr: float = -1e9
    wf_min_calmar: float = -1e9
    wf_min_folds: int = 0
    wf_min_trades: int = 0
    wf_max_exposure: float = 1.01
    # выбор лучшего
    rank_by: str = "oos_total_return_pct_mean"  # один из mean-метрик WF
    final_backtest: bool = False
    # вывод
    out_dir: Path = Path("data/optimize")
    report_html: Optional[Path] = None


def _sweep_once(inp: OptimizeInput, opt_root: Path) -> Path:
    scfg = SweepCfg(
        pair=inp.pair, span=inp.span, resample=inp.resample,
        fast_list=inp.fast_list, slow_list=inp.slow_list,
        hyst_list=inp.hyst_list, cooldown_list=inp.cooldown_list,
        qty_list=inp.qty_list, fee_bps=inp.fee_bps, slip_bps=inp.slip_bps,
        max_daily_loss_bps=inp.max_daily_loss_bps,
        out_dir=opt_root,
    )
    return Path(run_sweep(scfg))


def _wf_cfg_from_row(inp: OptimizeInput, row: pd.Series) -> SimpleNamespace:
    return SimpleNamespace(
        pair=inp.pair,
        span=inp.span,
        resample=inp.resample,
        fast=int(row["fast"]),
        slow=int(row["slow"]),
        hysteresis_bps=int(row["hysteresis_bps"]),
        cooldown_bars=int(row["cooldown_bars"]),
        fee_bps=int(inp.fee_bps),
        slip_bps=int(inp.slip_bps),
        qty_eur=float(row["qty_eur"]),
        max_daily_loss_bps=int(inp.max_daily_loss_bps),
        folds=int(inp.folds),
        min_train_bars=int(inp.min_train_bars),
        min_valid_bars=int(inp.min_valid_bars),
        # out_dir можно не задавать — WF может сам формировать пути; если нужно:
        out_dir=str(inp.out_dir),
    )


def _wf_mean_row_to_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Гарантированно сериализуем словарь средних WF-метрик."""
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (int, float, str)) or v is None:
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except Exception:
                out[k] = str(v)
    return out


def run_optimize(
    pair: str,
    span: str,
    resample: Optional[str],
    fast_list: List[int], slow_list: List[int],
    hyst_list: List[int], cooldown_list: List[int],
    qty_list: List[float],
    fee_bps: int = 10, slip_bps: int = 2, max_daily_loss_bps: int = 0,
    metric: str = "calmar", min_trades: int = 4,
    d_fast: int = 2, d_slow: int = 5, d_hyst: int = 5, d_cd: int = 2,
    wf_top_n: int = 5, folds: int = 4, min_train_bars: int = 150, min_valid_bars: int = 100,
    wf_min_pf: float = 0.0, wf_min_return: float = 0.0, wf_max_dd: float = 1.0,
    wf_min_winrate: float = 0.0, wf_min_sharpe: float = -1e9, wf_min_cagr: float = -1e9, wf_min_calmar: float = -1e9,
    wf_min_folds: int = 0, wf_min_trades: int = 0, wf_max_exposure: float = 1.01,
    rank_by: str = "oos_total_return_pct_mean", final_backtest: bool = False,
    out_dir: Optional[Path] = None, report_html: Optional[Path] = None,
) -> Dict[str, Any]:

    inp = OptimizeInput(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list,
        hyst_list=hyst_list, cooldown_list=cooldown_list,
        qty_list=qty_list, fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        metric=metric, min_trades=min_trades, d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        wf_top_n=wf_top_n, folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        wf_min_pf=wf_min_pf, wf_min_return=wf_min_return, wf_max_dd=wf_max_dd,
        wf_min_winrate=wf_min_winrate, wf_min_sharpe=wf_min_sharpe, wf_min_cagr=wf_min_cagr, wf_min_calmar=wf_min_calmar,
        wf_min_folds=wf_min_folds, wf_min_trades=wf_min_trades, wf_max_exposure=wf_max_exposure,
        rank_by=rank_by, final_backtest=final_backtest,
        out_dir=(out_dir or Path("data/optimize")), report_html=report_html,
    )

    # Готовим директорию запуска
    inp.out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Sweep
    sweep_csv = _sweep_once(inp, inp.out_dir)

    # 2) Robustness
    ranked = compute_stability(
        csv_path=sweep_csv,
        min_trades=inp.min_trades,
        metric=inp.metric,
        d_fast=inp.d_fast, d_slow=inp.d_slow, d_hyst=inp.d_hyst, d_cd=inp.d_cd,
    )
    # сохраняем ranked CSV
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    ranked_csv = inp.out_dir / f"ranked_{inp.pair}_{inp.resample or 'raw'}_{stamp}.csv"
    ranked.to_csv(ranked_csv, index=False)

    # 3) Берём топ-N и прогоняем WF
    top = ranked.head(inp.wf_top_n).copy()
    if top.empty:
        raise RuntimeError("No configs to run WF after robustness ranking.")

    wf_rows: List[Dict[str, Any]] = []
    for _, r in top.iterrows():
        wcfg = _wf_cfg_from_row(inp, r)
        wf_result = run_walkforward(wcfg)  # должен вернуть JSON-совместимый dict
        # нормализуем типы (float/int/str)
        wf_rows.append(_wf_mean_row_to_dict(wf_result))

    wf_df = pd.DataFrame(wf_rows)
    wf_csv = inp.out_dir / f"wf_{inp.pair}_{inp.resample or 'raw'}_{stamp}.csv"
    wf_df.to_csv(wf_csv, index=False)

    # 4) Фильтруем по заданным порогам (если требуется). Будем фильтровать по колонкам "*_mean"
    mask = pd.Series(True, index=wf_df.index)
    def _get(col, default):
        return pd.to_numeric(wf_df.get(col, default), errors="coerce")

    mask &= _get("oos_profit_factor_mean", 0.0) >= inp.wf_min_pf
    mask &= _get("oos_total_return_pct_mean", 0.0) >= inp.wf_min_return
    mask &= _get("oos_max_drawdown_pct_mean", -1.0).abs() <= inp.wf_max_dd
    mask &= _get("oos_winrate_pct_mean", 0.0) >= inp.wf_min_winrate
    mask &= _get("oos_sharpe_mean", -1e9) >= inp.wf_min_sharpe
    mask &= _get("oos_cagr_pct_mean", -1e9) >= inp.wf_min_cagr
    mask &= _get("oos_calmar_mean", -1e9) >= inp.wf_min_calmar

    filtered = wf_df.loc[mask].copy()
    # Ограничение по количеству «качественных» фолдов, если есть такая метрика (иначе пропускаем)
    if "folds" in filtered.columns and inp.wf_min_folds > 0:
        filtered = filtered[filtered["folds"] >= inp.wf_min_folds].copy()

    # 5) Выбираем лучший по rank_by из filtered, если пусто — берём лучший из всех
    rank_by_col = inp.rank_by
    selected_source = filtered if not filtered.empty else wf_df
    best_idx = selected_source[rank_by_col].astype(float).idxmax()
    best_row = selected_source.loc[best_idx].to_dict()

    # Вытаскиваем параметры best config обратно из ranked топа (по индексу best_idx привязка может не совпасть,
    # но мы сохранили все нужные поля в wf_row при формировании run_walkforward — можно просто вернуть оттуда)
    # Для ясности положим минимум полей:
    best_cfg = {
        "fast": int(top.iloc[0]["fast"]) if "fast" in top.columns else None,
        "slow": int(top.iloc[0]["slow"]) if "slow" in top.columns else None,
        "hysteresis_bps": int(top.iloc[0]["hysteresis_bps"]) if "hysteresis_bps" in top.columns else None,
        "cooldown_bars": int(top.iloc[0]["cooldown_bars"]) if "cooldown_bars" in top.columns else None,
        "qty_eur": float(top.iloc[0]["qty_eur"]) if "qty_eur" in top.columns else None,
        "pair": inp.pair,
        "resample": inp.resample,
    }

    final_metrics: Dict[str, Any] = {}
    final_artifacts: Dict[str, Any] = {}

    # 6) Финальный бэктест (опционально)
    if inp.final_backtest and all(k in best_cfg and best_cfg[k] is not None for k in ("fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur")):
        from .vectorized_bt import run_backtest_vectorized
        bt_cfg = SimpleNamespace(
            pair=inp.pair, span=inp.span, resample=inp.resample,
            fast=int(best_cfg["fast"]), slow=int(best_cfg["slow"]),
            hysteresis_bps=int(best_cfg["hysteresis_bps"]),
            cooldown_bars=int(best_cfg["cooldown_bars"]),
            fee_bps=int(inp.fee_bps), slip_bps=int(inp.slip_bps),
            qty_eur=float(best_cfg["qty_eur"]),
            max_daily_loss_bps=int(inp.max_daily_loss_bps),
            enter_on_start=False, vectorized=True,
        )
        fm = run_backtest_vectorized(bt_cfg)
        # Оставляем только сериализуемые метрики
        keep = [
            "pair", "bars", "trades", "winrate_pct", "total_return_pct", "max_drawdown_pct",
            "final_equity_eur", "start_equity_eur", "profit_factor", "avg_trade_eur",
            "exposure_pct", "sharpe", "cagr_pct", "calmar", "bars_per_year",
        ]
        final_metrics = {k: fm.get(k, None) for k in keep}
        final_artifacts = {
            "trades_csv": fm.get("trades_csv", None),
            "equity_csv": fm.get("equity_csv", None),
        }

    # 7) HTML-отчёт (если нужно)
    if inp.report_html:
        try:
            html = [
                "<html><head><meta charset='utf-8'><title>Optimize Report</title></head><body>",
                "<h2>Optimize Report</h2>",
                f"<p>Pair: <b>{inp.pair}</b>, Resample: <b>{inp.resample or 'raw'}</b></p>",
                "<h3>Best config (by {rank_by})</h3>".format(rank_by=rank_by),
                "<pre>" + json.dumps(best_row, ensure_ascii=False, indent=2) + "</pre>",
                "<h3>Final backtest metrics</h3>",
                "<pre>" + json.dumps(final_metrics, ensure_ascii=False, indent=2) + "</pre>",
                "</body></html>",
            ]
            inp.report_html.parent.mkdir(parents=True, exist_ok=True)
            inp.report_html.write_text("\n".join(html), encoding="utf-8")
        except Exception:
            # отчёт — не критичный этап
            pass

    # 8) Итог
    summary = {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "report_html": str(inp.report_html) if inp.report_html else None,
        "best_config": {
            **best_cfg,
            rank_by_col: float(best_row.get(rank_by_col, 0.0)),
        },
        "final_metrics": final_metrics,
        "final_artifacts": final_artifacts,
    }
    return summary
