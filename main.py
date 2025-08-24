#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Единый CLI: backtest / sweep / walk-forward / robustness / optimize.
Подкоманды сделаны через subparsers; каждая имеет свой набор аргументов.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Optional

# --- Импорты внутренних модулей ---
from src.backtest.vectorized_bt import run_backtest_vectorized, BtConfig
from src.backtest.sweep import run_sweep, SweepCfg, _parse_int_list as _parse_int_list_sweep, _parse_float_list as _parse_float_list_sweep
from src.backtest.walkforward import run_walkforward, WFConfig
from src.backtest.robustness import compute_stability
from src.backtest.optimize import run_optimize


# ----------------------- helpers -----------------------

def _resolve_glob_latest(pattern: str) -> Path:
    """Вернёт самый свежий файл по glob-шаблону."""
    candidates = sorted(glob.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"No files match pattern: {pattern}")
    return Path(candidates[-1])


# --------------------- subcommands ---------------------

def run_backtest_cmd(args: argparse.Namespace) -> None:
    cfg = BtConfig(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample),
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        qty_eur=float(args.qty_eur),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        enter_on_start=bool(args.enter_on_start),
        out_dir=str(args.out_dir) if args.out_dir else "",
    )
    out = run_backtest_vectorized(cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def run_sweep_cmd(args: argparse.Namespace) -> None:
    scfg = SweepCfg(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        qty_list=_parse_float_list_sweep(args.qty_list),
        fast_list=_parse_int_list_sweep(args.fast_list),
        slow_list=_parse_int_list_sweep(args.slow_list),
        hyst_list=_parse_int_list_sweep(args.hyst_list),
        cooldown_list=_parse_int_list_sweep(args.cooldown_list),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        sort_by=str(args.sort_by),
        top_n=int(args.top_n),
        out_dir=str(args.out_dir) if args.out_dir else "",
        verbose=bool(args.verbose),
    )
    csv_path = run_sweep(scfg)
    print(f"\nSweep saved to: {csv_path}")


def run_walkforward_cmd(args: argparse.Namespace) -> None:
    wcfg = WFConfig(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample),
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        qty_eur=float(args.qty_eur),
        folds=int(args.folds),
        min_train_bars=int(args.min_train_bars),
        min_valid_bars=int(args.min_valid_bars),
        enter_on_start=bool(args.enter_on_start),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
    )
    out_dir = Path(args.out_dir) if args.out_dir else None
    run_walkforward(wcfg, out_dir=out_dir, print_json=True)


def run_robustness_cmd(args: argparse.Namespace) -> None:
    resolved: Path
    if any(ch in args.sweep_csv for ch in "*?[]"):
        resolved = _resolve_glob_latest(args.sweep_csv)
        print(f"\nUsing sweep CSV: {resolved}")
    else:
        resolved = Path(args.sweep_csv)

    ranked = compute_stability(
        csv_path=resolved,
        min_trades=int(args.min_trades),
        metric=str(args.metric),
        d_fast=int(args.d_fast),
        d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst),
        d_cd=int(args.d_cd),
    )
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(out_csv, index=False)

    # Печать топа
    print("\n", ranked.head(20).to_string(index=False))
    print(f"\nSaved ranked table to: {out_csv}")


def run_optimize_cmd(args: argparse.Namespace) -> None:
    # поддержка glob для sweep/robustness в самом optimize не нужна — всё строим с нуля
    result = run_optimize(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample),
        fast_list=[int(x) for x in _parse_int_list_sweep(args.fast_list)],
        slow_list=[int(x) for x in _parse_int_list_sweep(args.slow_list)],
        hyst_list=[int(x) for x in _parse_int_list_sweep(args.hyst_list)],
        cooldown_list=[int(x) for x in _parse_int_list_sweep(args.cooldown_list)],
        qty_list=[float(x) for x in _parse_float_list_sweep(args.qty_list)],
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        metric=str(args.metric),
        min_trades=int(args.min_trades),
        d_fast=int(args.d_fast),
        d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst),
        d_cd=int(args.d_cd),
        wf_top_n=int(args.wf_top_n),
        folds=int(args.folds),
        min_train_bars=int(args.min_train_bars),
        min_valid_bars=int(args.min_valid_bars),
        wf_min_pf=float(args.wf_min_pf),
        wf_min_return=float(args.wf_min_return),
        wf_max_dd=float(args.wf_max_dd),
        wf_min_folds=int(args.wf_min_folds),
        rank_by=str(args.rank_by),
        final_backtest=bool(args.final_backtest),
        out_dir=str(args.out_dir) if args.out_dir else "data/optimize",

        # Доп. фильтры WF (новые)
        wf_min_winrate=float(args.wf_min_winrate),
        wf_min_sharpe=float(args.wf_min_sharpe),
        wf_min_cagr=float(args.wf_min_cagr),
        wf_min_calmar=float(args.wf_min_calmar),
        wf_min_trades=int(args.wf_min_trades),
        wf_max_exposure=float(args.wf_max_exposure),

        report_html=(args.report_html or None),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


# -------------------------- main CLI --------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- backtest ----
    pb = sub.add_parser("backtest", help="Запуск одиночного (vectorized) бэктеста")
    pb.add_argument("--vectorized", action="store_true", help="(исторический флаг; бэктест всегда векторный)")
    pb.add_argument("--exmo-pair", required=True)
    pb.add_argument("--exmo-candles", required=True, dest="exmo_candles")
    pb.add_argument("--resample", required=True)
    pb.add_argument("--fast", type=int, required=True)
    pb.add_argument("--slow", type=int, required=True)
    pb.add_argument("--hysteresis-bps", type=int, default=0)
    pb.add_argument("--cooldown-bars", type=int, default=0)
    pb.add_argument("--enter-on-start", action="store_true")
    pb.add_argument("--fee-bps", type=int, default=10)
    pb.add_argument("--slip-bps", type=int, default=0)
    pb.add_argument("--qty-eur", type=float, default=50.0)
    pb.add_argument("--max-daily-loss-bps", type=int, default=0)
    pb.add_argument("--out-dir", type=str, default="")
    pb.set_defaults(func=run_backtest_cmd)

    # ---- sweep ----
    ps = sub.add_parser("sweep", help="Перебор сетки параметров и метрик")
    ps.add_argument("--exmo-pair", required=True)
    ps.add_argument("--exmo-candles", required=True, dest="exmo_candles")
    ps.add_argument("--resample", required=True)
    ps.add_argument("--fast-list", required=True)
    ps.add_argument("--slow-list", required=True)
    ps.add_argument("--hyst-list", required=True)
    ps.add_argument("--cooldown-list", required=True)
    ps.add_argument("--qty-list", required=True)
    ps.add_argument("--fee-bps", type=int, default=10)
    ps.add_argument("--slip-bps", type=int, default=0)
    ps.add_argument("--max-daily-loss-bps", type=int, default=0)
    ps.add_argument("--sort-by", type=str, default="calmar")
    ps.add_argument("--top-n", type=int, default=0)
    ps.add_argument("--verbose", action="store_true")
    ps.add_argument("--out-dir", type=str, default="data/sweep")
    ps.set_defaults(func=run_sweep_cmd)

    # ---- walk-forward ----
    pw = sub.add_parser("walk-forward", help="WF (разбивка train/valid)")
    pw.add_argument("--exmo-pair", required=True)
    pw.add_argument("--exmo-candles", required=True, dest="exmo_candles")
    pw.add_argument("--resample", required=True)
    pw.add_argument("--fast", type=int, required=True)
    pw.add_argument("--slow", type=int, required=True)
    pw.add_argument("--hysteresis-bps", type=int, default=0)
    pw.add_argument("--cooldown-bars", type=int, default=0)
    pw.add_argument("--fee-bps", type=int, default=10)
    pw.add_argument("--slip-bps", type=int, default=0)
    pw.add_argument("--qty-eur", type=float, default=50.0)
    pw.add_argument("--folds", type=int, default=4)
    pw.add_argument("--min-train-bars", type=int, default=150)
    pw.add_argument("--min-valid-bars", type=int, default=100)
    pw.add_argument("--enter-on-start", action="store_true")
    pw.add_argument("--max-daily-loss-bps", type=int, default=0)
    pw.add_argument("--out-dir", type=str, default="data/walkforward")
    pw.set_defaults(func=run_walkforward_cmd)

    # ---- robustness ----
    pr = sub.add_parser("robustness", help="Ранжирование sweep-результатов по стабильности")
    pr.add_argument("--sweep-csv", required=True, help="Путь или glob (например, data/sweep/sweep_*DOGE_*.csv)")
    pr.add_argument("--metric", default="calmar",
                    choices=["calmar", "profit_factor", "total_return_pct", "sharpe", "cagr_pct"])
    pr.add_argument("--min-trades", type=int, default=0)
    pr.add_argument("--d-fast", type=int, default=2)
    pr.add_argument("--d-slow", type=int, default=5)
    pr.add_argument("--d-hyst", type=int, default=5)
    pr.add_argument("--d-cd", type=int, default=2)
    pr.add_argument("--out-csv", required=True)
    pr.set_defaults(func=run_robustness_cmd)

    # ---- optimize ----
    po = sub.add_parser("optimize", help="Пайплайн: sweep → robustness → WF(top-N) → выбор лучшего → (опц.) финальный бэктест + отчёт")
    po.add_argument("--exmo-pair", required=True)
    po.add_argument("--exmo-candles", required=True, dest="exmo_candles")
    po.add_argument("--resample", required=True)

    po.add_argument("--fast-list", required=True)
    po.add_argument("--slow-list", required=True)
    po.add_argument("--hyst-list", required=True)
    po.add_argument("--cooldown-list", required=True)
    po.add_argument("--qty-list", required=True)

    po.add_argument("--fee-bps", type=int, default=10)
    po.add_argument("--slip-bps", type=int, default=0)
    po.add_argument("--max-daily-loss-bps", type=int, default=0)

    po.add_argument("--metric", default="calmar",
                    choices=["calmar", "profit_factor", "total_return_pct", "sharpe", "cagr_pct"])
    po.add_argument("--min-trades", type=int, default=0)
    po.add_argument("--d-fast", type=int, default=2)
    po.add_argument("--d-slow", type=int, default=5)
    po.add_argument("--d-hyst", type=int, default=5)
    po.add_argument("--d-cd", type=int, default=2)

    po.add_argument("--wf-top-n", type=int, default=5)
    po.add_argument("--folds", type=int, default=4)
    po.add_argument("--min-train-bars", type=int, default=150)
    po.add_argument("--min-valid-bars", type=int, default=100)

    # Базовые WF-фильтры
    po.add_argument("--wf-min-pf", type=float, default=1.0)
    po.add_argument("--wf-min-return", type=float, default=0.0, help="Доля, 0.05 = +5%")
    po.add_argument("--wf-max-dd", type=float, default=0.35, help="Макс. просадка по mean, как доля (0.35 = -35%)")
    po.add_argument("--wf-min-folds", type=int, default=3)

    # Расширенные WF-фильтры (добавлены)
    po.add_argument("--wf-min-winrate", type=float, default=0.0, help="В %")
    po.add_argument("--wf-min-sharpe", type=float, default=float("-inf"))
    po.add_argument("--wf-min-cagr", type=float, default=float("-inf"), help="В %")
    po.add_argument("--wf-min-calmar", type=float, default=float("-inf"), help="В «сырых» единицах (например, 0.5)")
    po.add_argument("--wf-min-trades", type=int, default=0)
    po.add_argument("--wf-max-exposure", type=float, default=100.0, help="В %")

    po.add_argument("--rank-by", type=str,
                    choices=[
                        "oos_profit_factor_mean",
                        "oos_total_return_pct_mean",
                        "oos_calmar_mean",
                        "oos_sharpe_mean",
                        "oos_cagr_pct_mean",
                    ],
                    default="oos_total_return_pct_mean")

    po.add_argument("--final-backtest", action="store_true")
    po.add_argument("--report-html", type=str, default="", help="Путь для HTML-отчёта (опционально)")
    po.add_argument("--out-dir", type=str, default="data/optimize")
    po.set_defaults(func=run_optimize_cmd)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
