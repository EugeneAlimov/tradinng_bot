#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# backtest / sweep / robustness / walk-forward / optimize
from src.backtest.vectorized_bt import BtConfig, run_backtest_vectorized
from src.backtest.sweep import SweepCfg, run_sweep, parse_int_list, parse_float_list
from src.backtest.robustness import compute_stability
from src.backtest.walkforward import WFConfig, run_walkforward
from src.backtest.optimize import run_optimize


def _p(path_like: Optional[str]) -> Optional[Path]:
    if path_like is None:
        return None
    if isinstance(path_like, Path):
        return path_like
    return Path(str(path_like))


# ---------- subcommands ----------

def cmd_backtest(args: argparse.Namespace) -> None:
    cfg = BtConfig(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample) if args.resample else "",
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps or 0),
        cooldown_bars=int(args.cooldown_bars or 0),
        enter_on_start=bool(args.enter_on_start),
        fee_bps=int(args.fee_bps or 0),
        slip_bps=int(args.slip_bps or 0),
        qty_eur=float(args.qty_eur or 0.0),
        max_daily_loss_bps=int(args.max_daily_loss_bps or 0),
        out_dir=_p(args.out_dir),
    )
    metrics = run_backtest_vectorized(cfg)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def cmd_sweep(args: argparse.Namespace) -> None:
    scfg = SweepCfg(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample) if args.resample else "",
        fast_list=parse_int_list(args.fast_list),
        slow_list=parse_int_list(args.slow_list),
        hyst_list=parse_int_list(args.hyst_list),
        cooldown_list=parse_int_list(args.cooldown_list),
        qty_list=parse_float_list(args.qty_list),
        fee_bps=int(args.fee_bps or 0),
        slip_bps=int(args.slip_bps or 0),
        sort_by=str(args.sort_by or "calmar"),
        top_n=int(args.top_n or 20),
        out_dir=_p(args.out_dir) or Path("data/sweep"),
        verbose=bool(args.verbose),
    )
    path = run_sweep(scfg)
    print(f"\nSweep saved to: {path}")


def cmd_walk_forward(args: argparse.Namespace) -> None:
    wcfg = WFConfig(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample) if args.resample else "",
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps or 0),
        cooldown_bars=int(args.cooldown_bars or 0),
        fee_bps=int(args.fee_bps or 0),
        slip_bps=int(args.slip_bps or 0),
        qty_eur=float(args.qty_eur or 0.0),
        max_daily_loss_bps=int(args.max_daily_loss_bps or 0),
        folds=int(args.folds or 4),
        min_train_bars=int(args.min_train_bars or 150),
        min_valid_bars=int(args.min_valid_bars or 100),
        out_dir=_p(args.out_dir) or Path("data/walkforward"),
    )
    summary = run_walkforward(wcfg)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_robustness(args: argparse.Namespace) -> None:
    # поддержка glob
    resolved: list[Path] = []
    for patt in str(args.sweep_csv).split(","):
        resolved += list(Path().glob(patt.strip()))
    if not resolved:
        raise FileNotFoundError(f"No sweep csv matched pattern: {args.sweep_csv}")

    # возьмём самый свежий по mtime
    resolved.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    csv_path = resolved[0]

    ranked = compute_stability(
        csv_path=csv_path,
        min_trades=int(args.min_trades or 0),
        metric=str(args.metric or "calmar"),
        d_fast=int(args.d_fast or 1),
        d_slow=int(args.d_slow or 1),
        d_hyst=int(args.d_hyst or 1),
        d_cd=int(args.d_cd or 1),
    )

    out_csv = _p(args.out_csv) or csv_path.with_name("sweep_ranked.csv")
    ranked.to_csv(out_csv, index=False)
    print(f"\nSaved ranked table to: {out_csv}")


def cmd_optimize(args: argparse.Namespace) -> None:
    out = run_optimize(
        pair=str(args.exmo_pair),
        span=str(args.exmo_candles),
        resample=str(args.resample) if args.resample else "",
        fast_list=parse_int_list(args.fast_list),
        slow_list=parse_int_list(args.slow_list),
        hyst_list=parse_int_list(args.hyst_list),
        cooldown_list=parse_int_list(args.cooldown_list),
        qty_list=parse_float_list(args.qty_list),
        fee_bps=int(args.fee_bps or 0),
        slip_bps=int(args.slip_bps or 0),
        max_daily_loss_bps=int(args.max_daily_loss_bps or 0),
        metric=str(args.metric or "calmar"),
        min_trades=int(args.min_trades or 0),
        d_fast=int(args.d_fast or 1),
        d_slow=int(args.d_slow or 1),
        d_hyst=int(args.d_hyst or 1),
        d_cd=int(args.d_cd or 1),
        wf_top_n=int(args.wf_top_n or 5),
        folds=int(args.folds or 4),
        min_train_bars=int(args.min_train_bars or 150),
        min_valid_bars=int(args.min_valid_bars or 100),
        wf_min_pf=float(args.wf_min_pf or 0.0),
        wf_min_return=float(args.wf_min_return or 0.0),
        wf_max_dd=float(args.wf_max_dd or 1.0),
        wf_min_winrate=float(args.wf_min_winrate or 0.0) if args.wf_min_winrate is not None else None,
        wf_min_sharpe=float(args.wf_min_sharpe or 0.0) if args.wf_min_sharpe is not None else None,
        wf_min_cagr=float(args.wf_min_cagr or 0.0) if args.wf_min_cagr is not None else None,
        wf_min_calmar=float(args.wf_min_calmar or 0.0) if args.wf_min_calmar is not None else None,
        wf_min_folds=int(args.wf_min_folds or 0),
        wf_min_trades=int(args.wf_min_trades or 0),
        wf_max_exposure=float(args.wf_max_exposure or 1.0),
        rank_by=str(args.rank_by or "oos_total_return_pct_mean"),
        final_backtest=bool(args.final_backtest),
        out_dir=_p(args.out_dir) or Path("data/optimize"),
        report_html=_p(args.report_html) if args.report_html else None,
    )
    # печатаем финальный JSON (словарь)
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tradinng-bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # common
    def add_common(sp: argparse.ArgumentParser):
        sp.add_argument("--exmo-pair", dest="exmo_pair", default="DOGE_EUR")
        sp.add_argument("--exmo-candles", dest="exmo_candles", default="1m:2000")
        sp.add_argument("--resample", default="5m")
        sp.add_argument("--fee-bps", type=int, default=10)
        sp.add_argument("--slip-bps", type=int, default=2)
        sp.add_argument("--max-daily-loss-bps", type=int, default=0)
        sp.add_argument("--out-dir", default=None)

    # backtest
    sp_b = sub.add_parser("backtest")
    add_common(sp_b)
    sp_b.add_argument("--vectorized", action="store_true")
    sp_b.add_argument("--fast", type=int, default=15)
    sp_b.add_argument("--slow", type=int, default=25)
    sp_b.add_argument("--hysteresis-bps", type=int, default=0)
    sp_b.add_argument("--cooldown-bars", type=int, default=0)
    sp_b.add_argument("--enter-on-start", action="store_true")
    sp_b.add_argument("--qty-eur", type=float, default=100.0)
    sp_b.set_defaults(func=cmd_backtest)

    # sweep
    sp_s = sub.add_parser("sweep")
    add_common(sp_s)
    sp_s.add_argument("--fast-list", default="5:20:5")
    sp_s.add_argument("--slow-list", default="20:40:5")
    sp_s.add_argument("--hyst-list", default="0,5,10,15")
    sp_s.add_argument("--cooldown-list", default="0,3,5")
    sp_s.add_argument("--qty-list", default="50,100")
    sp_s.add_argument("--sort-by", default="calmar")
    sp_s.add_argument("--top-n", type=int, default=20)
    sp_s.add_argument("--verbose", action="store_true")
    sp_s.set_defaults(func=cmd_sweep)

    # walk-forward
    sp_wf = sub.add_parser("walk-forward")
    add_common(sp_wf)
    sp_wf.add_argument("--fast", type=int, default=15)
    sp_wf.add_argument("--slow", type=int, default=25)
    sp_wf.add_argument("--hysteresis-bps", type=int, default=0)
    sp_wf.add_argument("--cooldown-bars", type=int, default=0)
    sp_wf.add_argument("--qty-eur", type=float, default=100.0)
    sp_wf.add_argument("--folds", type=int, default=4)
    sp_wf.add_argument("--min-train-bars", type=int, default=150)
    sp_wf.add_argument("--min-valid-bars", type=int, default=100)
    sp_wf.set_defaults(func=cmd_walk_forward)

    # robustness
    sp_r = sub.add_parser("robustness")
    add_common(sp_r)
    sp_r.add_argument("--sweep-csv", required=True)
    sp_r.add_argument("--metric", default="calmar")
    sp_r.add_argument("--min-trades", type=int, default=4)
    sp_r.add_argument("--d-fast", type=int, default=2)
    sp_r.add_argument("--d-slow", type=int, default=5)
    sp_r.add_argument("--d-hyst", type=int, default=5)
    sp_r.add_argument("--d-cd", type=int, default=2)
    sp_r.add_argument("--out-csv", default="data/sweep/sweep_ranked.csv")
    sp_r.set_defaults(func=cmd_robustness)

    # optimize
    sp_o = sub.add_parser("optimize")
    add_common(sp_o)
    sp_o.add_argument("--fast-list", default="5:20:5")
    sp_o.add_argument("--slow-list", default="20:40:5")
    sp_o.add_argument("--hyst-list", default="0,5,10,15")
    sp_o.add_argument("--cooldown-list", default="0,3,5")
    sp_o.add_argument("--qty-list", default="50,100")
    sp_o.add_argument("--metric", default="calmar")
    sp_o.add_argument("--min-trades", type=int, default=4)
    sp_o.add_argument("--d-fast", type=int, default=2)
    sp_o.add_argument("--d-slow", type=int, default=5)
    sp_o.add_argument("--d-hyst", type=int, default=5)
    sp_o.add_argument("--d-cd", type=int, default=2)
    sp_o.add_argument("--wf-top-n", type=int, default=5)
    sp_o.add_argument("--folds", type=int, default=4)
    sp_o.add_argument("--min-train-bars", type=int, default=150)
    sp_o.add_argument("--min-valid-bars", type=int, default=100)
    sp_o.add_argument("--wf-min-pf", type=float, default=1.0)
    sp_o.add_argument("--wf-min-return", type=float, default=0.0)
    sp_o.add_argument("--wf-max-dd", type=float, default=0.35)
    sp_o.add_argument("--wf-min-winrate", type=float, default=None)
    sp_o.add_argument("--wf-min-sharpe", type=float, default=None)
    sp_o.add_argument("--wf-min-cagr", type=float, default=None)
    sp_o.add_argument("--wf-min-calmar", type=float, default=None)
    sp_o.add_argument("--wf-min-folds", type=int, default=3)
    sp_o.add_argument("--wf-min-trades", type=int, default=0)
    sp_o.add_argument("--wf-max-exposure", type=float, default=1.0)
    sp_o.add_argument("--rank-by",
                      choices=["oos_profit_factor_mean", "oos_total_return_pct_mean", "oos_calmar_mean",
                               "oos_sharpe_mean", "oos_cagr_pct_mean"],
                      default="oos_total_return_pct_mean")
    sp_o.add_argument("--final-backtest", action="store_true")
    sp_o.add_argument("--report-html", default=None)
    sp_o.set_defaults(func=cmd_optimize)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
