# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Dict, Any

import pandas as pd

# ВАЖНО: используем уже существующие в проекте функции/типы, не ломаем их сигнатуры
from .sweep import SweepCfg, run_sweep
from .robustness import compute_stability
from .walkforward import WFConfig, run_walkforward
from .vectorized_bt import BtConfig, run_backtest_vectorized


@dataclass
class OptimizeInput:
    # Источник данных
    pair: str
    span: str              # например: "1m:5000"
    resample: str          # "5m" или "5T"

    # Грид для sweep
    fast_list: Iterable[int]
    slow_list: Iterable[int]
    hyst_list: Iterable[int]
    cooldown_list: Iterable[int]
    qty_list: Iterable[float]

    # Торговые издержки и риски
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int

    # Робастность
    metric: str
    min_trades: int
    d_fast: int
    d_slow: int
    d_hyst: int
    d_cd: int

    # Walk-forward
    wf_top_n: int
    folds: int
    min_train_bars: int
    min_valid_bars: int

    # WF-фильтры
    wf_min_pf: float
    wf_min_return: float
    wf_max_dd: float
    wf_min_winrate: float = 0.0
    wf_min_sharpe: float = 0.0
    wf_min_cagr: float = 0.0
    wf_min_calmar: float = 0.0
    wf_min_folds: int = 0
    wf_min_trades: int = 0
    wf_max_exposure: float = 100.0

    # Ранжирование и финальный бектест
    rank_by: str = "oos_total_return_pct_mean"
    final_backtest: bool = False

    # Артефакты
    out_dir: Path = Path("data/optimize")
    report_html: Optional[Path] = None

    # Поведение при нестабильной загрузке EXMO
    sweep_max_retries: int = 3
    sweep_retry_sleep_sec: float = 2.0


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True) if p.suffix else p.mkdir(parents=True, exist_ok=True)


def _sweep_once(inp: OptimizeInput, out_root: Path) -> Path:
    """Запускает один sweep и возвращает путь к CSV."""
    scfg = SweepCfg(
        pair=inp.pair,
        span=inp.span,
        resample=inp.resample,
        fast_list=list(inp.fast_list),
        slow_list=list(inp.slow_list),
        hyst_list=list(inp.hyst_list),
        cooldown_list=list(inp.cooldown_list),
        qty_list=list(inp.qty_list),
        fee_bps=int(inp.fee_bps),
        slip_bps=int(inp.slip_bps),
        max_daily_loss_bps=int(inp.max_daily_loss_bps),
        sort_by="calmar",               # сортировка внутри свип-таблицы (не финальная)
        top_n=0,                        # берём все, отбор дальше делает robust/WF
        out_dir=out_root,
    )
    csv_path = Path(run_sweep(scfg))
    return csv_path


def _robust_rank_or_none(inp: OptimizeInput, sweep_csv: Path) -> Tuple[Optional[pd.DataFrame], Optional[Path], Optional[str]]:
    """
    Пытается посчитать робастность. Если входной CSV только с ошибками — вернёт (None, Path_to_ranked, reason).
    """
    ranked_csv = sweep_csv.with_name(sweep_csv.name.replace("sweep_", "ranked_"))
    try:
        ranked_df = compute_stability(
            csv_path=sweep_csv,
            min_trades=inp.min_trades,
            metric=inp.metric,
            d_fast=inp.d_fast,
            d_slow=inp.d_slow,
            d_hyst=inp.d_hyst,
            d_cd=inp.d_cd,
        )
    except RuntimeError as e:
        # Типичный случай: "Sweep CSV contains no successful rows (all with errors)."
        return None, ranked_csv, str(e)

    # Сохраним ранжированную таблицу (если вызывающий код рассчитывает увидеть файл)
    if ranked_df is not None:
        _ensure_dir(ranked_csv)
        ranked_df.to_csv(ranked_csv, index=False)

    if ranked_df is None or ranked_df.empty:
        return None, ranked_csv, "Ranked table is empty."

    return ranked_df, ranked_csv, None


def _pick_top_for_wf(ranked_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if ranked_df is None or ranked_df.empty:
        return pd.DataFrame()
    # Простая защита от отсутствия ожидаемых колонок:
    cols = list(ranked_df.columns)
    # Оставим понятные поля + гиперпараметры
    keep = [c for c in [
        "pair", "bars", "trades", "winrate_pct", "total_return_pct",
        "max_drawdown_pct", "final_equity_eur", "start_equity_eur",
        "profit_factor", "avg_trade_eur", "exposure_pct", "sharpe",
        "cagr_pct", "calmar", "bars_per_year",
        "fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur",
        "fee_bps", "slip_bps", "max_daily_loss_bps",
        "stability_mean", "stability_median", "neighbors"
    ] if c in cols]
    core = ranked_df[keep].copy()
    if top_n and top_n > 0:
        core = core.head(top_n).copy()
    return core


def _wf_mean_row_to_dict(row: pd.Series) -> Dict[str, Any]:
    return {k: (None if (pd.isna(v) if isinstance(v, float) else False) else v) for k, v in row.items()}


def _write_report(report_html: Path,
                  pair: str,
                  resample: str,
                  sweep_csv: Path,
                  ranked_csv: Optional[Path],
                  wf_csv: Optional[Path],
                  best_summary: Optional[Dict[str, Any]],
                  message: str) -> None:
    _ensure_dir(report_html)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Optimize Report</title>
<style>
body{{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:24px;}}
code,pre{{background:#f6f8fa;border-radius:6px;padding:8px;display:block}}
h1{{margin:0 0 12px}} h2{{margin:24px 0 8px}}
table{{border-collapse:collapse}} td,th{{border:1px solid #ddd;padding:6px 10px}}
</style></head><body>
<h1>Optimize Report</h1>
<p><b>Pair:</b> {pair} &nbsp; <b>Resample:</b> {resample}</p>
<h2>Artifacts</h2>
<ul>
  <li>Sweep CSV: <code>{sweep_csv}</code></li>
  <li>Ranked CSV: <code>{ranked_csv or '-'}</code></li>
  <li>WF CSV: <code>{wf_csv or '-'}</code></li>
</ul>
<h2>Status</h2>
<pre>{message}</pre>
"""
    if best_summary:
        html += "<h2>Best after filters</h2><pre>"
        html += json.dumps(best_summary, ensure_ascii=False, indent=2)
        html += "</pre>"
    html += "</body></html>"
    report_html.write_text(html, encoding="utf-8")


def run_optimize(
    *,
    pair: str,
    span: str,
    resample: str,
    fast_list: Iterable[int],
    slow_list: Iterable[int],
    hyst_list: Iterable[int],
    cooldown_list: Iterable[int],
    qty_list: Iterable[float],
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
    wf_min_pf: float,
    wf_min_return: float,
    wf_max_dd: float,
    wf_min_winrate: float = 0.0,
    wf_min_sharpe: float = 0.0,
    wf_min_cagr: float = 0.0,
    wf_min_calmar: float = 0.0,
    wf_min_folds: int = 0,
    wf_min_trades: int = 0,
    wf_max_exposure: float = 100.0,
    rank_by: str = "oos_total_return_pct_mean",
    final_backtest: bool = False,
    out_dir: Path | str = Path("data/optimize"),
    report_html: Optional[Path] = None,
    sweep_max_retries: int = 3,
    sweep_retry_sleep_sec: float = 2.0,
) -> Dict[str, Any]:
    """
    Точка входа для main.py. Возвращает словарь с полезной телеметрией и путями к артефактам.
    """
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    if report_html is None:
        report_html = out_root / "report.html"

    inp = OptimizeInput(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list, cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        metric=metric, min_trades=min_trades, d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        wf_top_n=wf_top_n, folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        wf_min_pf=wf_min_pf, wf_min_return=wf_min_return, wf_max_dd=wf_max_dd,
        wf_min_winrate=wf_min_winrate, wf_min_sharpe=wf_min_sharpe, wf_min_cagr=wf_min_cagr, wf_min_calmar=wf_min_calmar,
        wf_min_folds=wf_min_folds, wf_min_trades=wf_min_trades, wf_max_exposure=wf_max_exposure,
        rank_by=rank_by, final_backtest=final_backtest, out_dir=out_root, report_html=report_html,
        sweep_max_retries=sweep_max_retries, sweep_retry_sleep_sec=sweep_retry_sleep_sec,
    )

    # ---------- 1) SWEEP c автоповторами при пустых данных ----------
    last_reason: Optional[str] = None
    sweep_csv: Optional[Path] = None
    ranked_csv: Optional[Path] = None
    ranked_df: Optional[pd.DataFrame] = None

    for attempt in range(1, inp.sweep_max_retries + 1):
        sweep_csv = _sweep_once(inp, out_root)
        ranked_df, ranked_csv, reason = _robust_rank_or_none(inp, sweep_csv)
        if ranked_df is not None and not ranked_df.empty:
            last_reason = None
            break

        # все строки — с ошибками или ранкинг пустой
        last_reason = reason or "ranked is empty"
        if attempt < inp.sweep_max_retries:
            time.sleep(inp.sweep_retry_sleep_sec * (1.5 ** (attempt - 1)))
            continue
        # исчерпали попытки — выйдем с сообщением
        msg = "Ranked table is empty or contains only errors; stopping before WF."
        payload = {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv) if ranked_csv else None,
            "wf_csv": None,
            "report_html": str(report_html),
            "message": msg,
        }
        _write_report(report_html, inp.pair, inp.resample, sweep_csv, ranked_csv, None, None, msg)
        return payload

    assert sweep_csv is not None and ranked_csv is not None and ranked_df is not None

    # ---------- 2) Выбор top-N на WF ----------
    to_wf = _pick_top_for_wf(ranked_df, inp.wf_top_n)
    if to_wf.empty:
        msg = "No rows selected for WF (top-N is empty)."
        payload = {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": None,
            "report_html": str(report_html),
            "message": msg,
        }
        _write_report(report_html, inp.pair, inp.resample, sweep_csv, ranked_csv, None, None, msg)
        return payload

    # ---------- 3) Walk-Forward для выбранных конфигов ----------
    wf_rows: List[Dict[str, Any]] = []
    for _, r in to_wf.iterrows():
        wcfg = WFConfig(
            pair=inp.pair, span=inp.span, resample=inp.resample,
            fast=int(r["fast"]), slow=int(r["slow"]),
            hysteresis_bps=int(r["hysteresis_bps"]), cooldown_bars=int(r["cooldown_bars"]),
            fee_bps=int(r["fee_bps"]), slip_bps=int(r["slip_bps"]),
            qty_eur=float(r["qty_eur"]), max_daily_loss_bps=int(r.get("max_daily_loss_bps", 0)),
            folds=inp.folds, min_train_bars=inp.min_train_bars, min_valid_bars=inp.min_valid_bars,
        )
        # run_walkforward возвращает dict с метриками; складываем в единую таблицу
        wf_res = run_walkforward(wcfg)
        wf_rows.append(wf_res)

    wf_df = pd.DataFrame(wf_rows)
    wf_csv = out_root / f"wf_{inp.pair}_{inp.resample}_{time.strftime('%Y%m%d-%H%M%S')}.csv"
    _ensure_dir(wf_csv)
    wf_df.to_csv(wf_csv, index=False)

    # ---------- 4) Фильтры по WF & выбор лучшего ----------
    # Сначала — «жёсткие» фильтры
    filtered = wf_df.copy()

    def _col(name: str) -> str:
        # страховка: колонок может не быть (например, если run_walkforward изменяет схему)
        return name if name in filtered.columns else None

    conds = []
    c = _col("oos_profit_factor_mean")
    if c and inp.wf_min_pf is not None:
        conds.append(filtered[c] >= float(inp.wf_min_pf))
    c = _col("oos_total_return_pct_mean")
    if c and inp.wf_min_return is not None:
        conds.append(filtered[c] >= float(inp.wf_min_return))
    c = _col("oos_max_drawdown_pct_mean")
    if c and inp.wf_max_dd is not None:
        conds.append(filtered[c] >= -float(inp.wf_max_dd))  # drawdown отрицательный
    c = _col("oos_winrate_pct_mean")
    if c and inp.wf_min_winrate is not None:
        conds.append(filtered[c] >= float(inp.wf_min_winrate))
    c = _col("oos_sharpe_mean")
    if c and inp.wf_min_sharpe is not None:
        conds.append(filtered[c] >= float(inp.wf_min_sharpe))
    c = _col("oos_cagr_pct_mean")
    if c and inp.wf_min_cagr is not None:
        conds.append(filtered[c] >= float(inp.wf_min_cagr))
    c = _col("oos_calmar_mean")
    if c and inp.wf_min_calmar is not None:
        conds.append(filtered[c] >= float(inp.wf_min_calmar))
    c = _col("folds")
    if c and inp.wf_min_folds:
        conds.append(filtered[c] >= int(inp.wf_min_folds))

    if conds:
        mask = conds[0]
        for m in conds[1:]:
            mask = mask & m
        filtered = filtered[mask].copy()

    selected_from = "filtered" if not filtered.empty else "unfiltered"
    if filtered.empty:
        filtered = wf_df.copy()

    # Ранжируем по ранжирующей метрике
    rank_col = inp.rank_by if inp.rank_by in filtered.columns else "oos_total_return_pct_mean"
    filtered = filtered.sort_values(rank_col, ascending=False, kind="mergesort")
    best_row = filtered.iloc[0].copy()
    best_summary: Dict[str, Any] = _wf_mean_row_to_dict(best_row)

    # ---------- 5) Финальный backtest (опционально) ----------
    final_metrics_block: Optional[Dict[str, Any]] = None
    if inp.final_backtest:
        bcfg = BtConfig(
            pair=inp.pair,
            span=inp.span,
            resample=inp.resample,
            fast=int(best_row.get("fast")),
            slow=int(best_row.get("slow")),
            hysteresis_bps=int(best_row.get("hysteresis_bps")),
            cooldown_bars=int(best_row.get("cooldown_bars")),
            fee_bps=int(best_row.get("fee_bps", 0)),
            slip_bps=int(best_row.get("slip_bps", 0)),
            qty_eur=float(best_row.get("qty_eur", 0.0)),
            max_daily_loss_bps=int(best_row.get("max_daily_loss_bps", 0)),
            # Никаких trades/equity отдельных файлов в свипах; для финального — можно оставить внутри run_backtest логику как есть
        )
        bt_res = run_backtest_vectorized(bcfg)
        # Убедимся, что всё сериализуемо
        metrics = bt_res.copy()
        for k in ("trades_df", "equity_df"):
            if k in metrics:
                metrics.pop(k)  # на всякий случай
        # Если вложенные DataFrame попадают в словарь — выбрасываем их:
        for k, v in list(metrics.items()):
            if isinstance(v, pd.DataFrame):
                metrics.pop(k)

        final_metrics_block = {
            "metrics": metrics.get("metrics", metrics),  # поддержка обоих вариантов
            "trades_csv": metrics.get("trades_csv"),
            "equity_csv": metrics.get("equity_csv"),
        }
        best_summary["final_metrics"] = final_metrics_block

    # ---------- 6) Запишем репорт и вернём сводку ----------
    msg = f"Selected from: {selected_from}"
    _write_report(report_html, inp.pair, inp.resample, sweep_csv, ranked_csv, wf_csv, best_summary, msg)

    result = {
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "report_html": str(report_html),
        "best": best_summary,
        "message": msg,
    }
    return result
