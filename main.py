from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

# Backtest/Sweep/WF/Robustness/Optimize
from src.backtest.vectorized_bt import BtConfig, run_backtest_vectorized
from src.backtest.sweep import SweepCfg, run_sweep
from src.backtest.walkforward import WFConfig, run_walkforward
from src.backtest.robustness import compute_stability
from src.backtest.optimize import run_optimize


def _parse_range_list(s: str) -> List[int]:
    """
    Accepts:
      '5:20:5' -> [5,10,15,20]
      '1,3,7'  -> [1,3,7]
    """
    s = s.strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 3:
            raise argparse.ArgumentTypeError(f"Bad range '{s}', expected start:stop:step")
        start, stop, step = map(int, parts)
        if step == 0:
            raise argparse.ArgumentTypeError("Step cannot be 0")
        return list(range(start, stop + (1 if step > 0 else -1), step))
    return [int(x) for x in s.split(",") if x != ""]


def _parse_float_list(s: str) -> List[float]:
    return [float(x) for x in s.split(",") if x != ""]


def run_backtest_cmd(args: argparse.Namespace) -> None:
    cfg = BtConfig(
        pair=args.exmo_pair, span=args.exmo_candles,
        fast=args.fast, slow=args.slow,
        hysteresis_bps=args.hysteresis_bps,
        cooldown_bars=args.cooldown_bars,
        enter_on_start=args.enter_on_start,
        fee_bps=args.fee_bps, slip_bps=args.slip_bps,
        qty_eur=args.qty_eur,
        max_daily_loss_bps=args.max_daily_loss_bps,
        resample=args.resample,
        out_dir=args.out_dir,
    )
    metrics = run_backtest_vectorized(cfg)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def run_sweep_cmd(args: argparse.Namespace) -> None:
    cfg = SweepCfg(
        pair=args.exmo_pair, span=args.exmo_candles, resample=args.resample,
        fast_list=args.fast_list, slow_list=args.slow_list,
        hyst_list=args.hyst_list, cooldown_list=args.cooldown_list,
        qty_list=args.qty_list,
        fee_bps=args.fee_bps, slip_bps=args.slip_bps,
        sort_by=args.sort_by, top_n=args.top_n,
        out_dir=Path(args.out_dir) if args.out_dir else Path("data/sweep"),
        write_artifacts=False,  # avoid per-run CSV spam
        verbose=args.verbose,
    )
    path = run_sweep(cfg)
    print(f"\nSweep saved to: {path}")


def run_wf_cmd(args: argparse.Namespace) -> None:
    cfg = WFConfig(
        pair=args.exmo_pair, span=args.exmo_candles, resample=args.resample,
        fast=args.fast, slow=args.slow,
        hysteresis_bps=args.hysteresis_bps,
        cooldown_bars=args.cooldown_bars,
        fee_bps=args.fee_bps, slip_bps=args.slip_bps,
        qty_eur=args.qty_eur,
        max_daily_loss_bps=args.max_daily_loss_bps,
        folds=args.folds, min_train_bars=args.min_train_bars, min_valid_bars=args.min_valid_bars,
        out_dir=Path(args.out_dir) if args.out_dir else None,
    )
    out = run_walkforward(cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def run_robustness_cmd(args: argparse.Namespace) -> None:
    ranked = compute_stability(
        csv_path=Path(args.sweep_csv),
        min_trades=int(args.min_trades),
        metric=str(args.metric),
        d_fast=int(args.d_fast), d_slow=int(args.d_slow), d_hyst=int(args.d_hyst), d_cd=int(args.d_cd),
    )
    out = Path(args.out_csv) if args.out_csv else Path("data/sweep/sweep_ranked.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(out, index=False)
    print(ranked.head(20).to_string(index=False))
    print(f"\nSaved ranked table to: {out}")


def run_optimize_cmd(args: argparse.Namespace) -> None:
    result = run_optimize(
        pair=str(args.exmo_pair), span=str(args.exmo_candles), resample=str(args.resample),
        fast_list=list(args.fast_list), slow_list=list(args.slow_list),
        hyst_list=list(args.hyst_list), cooldown_list=list(args.cooldown_list),
        qty_list=list(args.qty_list),
        fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps), max_daily_loss_bps=int(args.max_daily_loss_bps),
        metric=str(args.metric), min_trades=int(args.min_trades),
        d_fast=int(args.d_fast), d_slow=int(args.d_slow), d_hyst=int(args.d_hyst), d_cd=int(args.d_cd),
        wf_top_n=int(args.wf_top_n), folds=int(args.folds),
        min_train_bars=int(args.min_train_bars), min_valid_bars=int(args.min_valid_bars),
        wf_min_pf=float(args.wf_min_pf), wf_min_return=float(args.wf_min_return), wf_max_dd=float(args.wf_max_dd),
        wf_min_winrate=float(args.wf_min_winrate), wf_min_sharpe=float(args.wf_min_sharpe),
        wf_min_cagr=float(args.wf_min_cagr), wf_min_calmar=float(args.wf_min_calmar),
        wf_min_folds=int(args.wf_min_folds), wf_min_trades=int(args.wf_min_trades),
        wf_max_exposure=float(args.wf_max_exposure),
        rank_by=str(args.rank_by), final_backtest=bool(args.final_backtest),
        out_dir=Path(args.out_dir) if args.out_dir else None,
        report_html=(Path(args.report_html) if args.report_html else None),
    )
    # expose summary again as JSON for piping
    print()
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _add_shared_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--exmo-pair", dest="exmo_pair", default="DOGE_EUR")
    p.add_argument("--exmo-candles", dest="exmo_candles", default="1m:2000")
    p.add_argument("--resample", default="5m")
    p.add_argument("--fast", type=int, default=15)
    p.add_argument("--slow", type=int, default=25)
    p.add_argument("--hysteresis-bps", type=int, default=0)
    p.add_argument("--cooldown-bars", type=int, default=5)
    p.add_argument("--enter-on-start", action="store_true", default=False)
    p.add_argument("--fee-bps", type=int, default=10)
    p.add_argument("--slip-bps", type=int, default=2)
    p.add_argument("--qty-eur", type=float, default=100.0)
    p.add_argument("--max-daily-loss-bps", type=int, default=0)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--json-metrics", default=None)


def main() -> None:
    ap = argparse.ArgumentParser(prog="tradinng-bot")
    sub = ap.add_subparsers(required=True, dest="command")

    # backtest
    p_bt = sub.add_parser("backtest")
    _add_shared_args(p_bt)
    p_bt.set_defaults(func=run_backtest_cmd)

    # sweep
    p_sw = sub.add_parser("sweep")
    _add_shared_args(p_sw)
    p_sw.add_argument("--fast-list", type=_parse_range_list, required=True)
    p_sw.add_argument("--slow-list", type=_parse_range_list, required=True)
    p_sw.add_argument("--hyst-list", type=_parse_range_list, required=True)
    p_sw.add_argument("--cooldown-list", type=_parse_range_list, required=True)
    p_sw.add_argument("--qty-list", type=_parse_float_list, required=True)
    p_sw.add_argument("--sort-by", default="calmar")
    p_sw.add_argument("--top-n", type=int, default=0)
    p_sw.add_argument("--verbose", action="store_true", default=False)
    p_sw.set_defaults(func=run_sweep_cmd)

    # walk-forward
    p_wf = sub.add_parser("walk-forward")
    _add_shared_args(p_wf)
    p_wf.add_argument("--folds", type=int, default=4)
    p_wf.add_argument("--min-train-bars", type=int, default=150)
    p_wf.add_argument("--min-valid-bars", type=int, default=100)
    p_wf.set_defaults(func=run_wf_cmd)

    # robustness
    p_rb = sub.add_parser("robustness")
    p_rb.add_argument("--sweep-csv", required=True)
    p_rb.add_argument("--metric", default="calmar")
    p_rb.add_argument("--min-trades", type=int, default=0)
    p_rb.add_argument("--d-fast", type=int, default=1)
    p_rb.add_argument("--d-slow", type=int, default=1)
    p_rb.add_argument("--d-hyst", type=int, default=1)
    p_rb.add_argument("--d-cd", type=int, default=1)
    p_rb.add_argument("--out-csv", default="data/sweep/sweep_ranked.csv")
    p_rb.set_defaults(func=run_robustness_cmd)

    # optimize
    p_opt = sub.add_parser("optimize")
    _add_shared_args(p_opt)
    p_opt.add_argument("--fast-list", type=_parse_range_list, required=True)
    p_opt.add_argument("--slow-list", type=_parse_range_list, required=True)
    p_opt.add_argument("--hyst-list", type=_parse_range_list, required=True)
    p_opt.add_argument("--cooldown-list", type=_parse_range_list, required=True)
    p_opt.add_argument("--qty-list", type=_parse_float_list, required=True)

    p_opt.add_argument("--metric", default="calmar")
    p_opt.add_argument("--min-trades", type=int, default=0)
    p_opt.add_argument("--d-fast", type=int, default=1)
    p_opt.add_argument("--d-slow", type=int, default=1)
    p_opt.add_argument("--d-hyst", type=int, default=1)
    p_opt.add_argument("--d-cd", type=int, default=1)

    p_opt.add_argument("--wf-top-n", type=int, default=10)
    p_opt.add_argument("--folds", type=int, default=4)
    p_opt.add_argument("--min-train-bars", type=int, default=150)
    p_opt.add_argument("--min-valid-bars", type=int, default=100)

    # WF filters
    p_opt.add_argument("--wf-min-pf", type=float, default=0.0)
    p_opt.add_argument("--wf-min-return", type=float, default=0.0)
    p_opt.add_argument("--wf-max-dd", type=float, default=1.0)
    p_opt.add_argument("--wf-min-winrate", type=float, default=0.0)
    p_opt.add_argument("--wf-min-sharpe", type=float, default=-999.0)
    p_opt.add_argument("--wf-min-cagr", type=float, default=-999.0)
    p_opt.add_argument("--wf-min-calmar", type=float, default=-999.0)
    p_opt.add_argument("--wf-min-folds", type=int, default=1)
    p_opt.add_argument("--wf-min-trades", type=int, default=0)
    p_opt.add_argument("--wf-max-exposure", type=float, default=1.0)

    p_opt.add_argument("--rank-by",
                       choices=["oos_profit_factor_mean", "oos_total_return_pct_mean", "oos_calmar_mean",
                                "oos_sharpe_mean", "oos_cagr_pct_mean"],
                       default="oos_total_return_pct_mean")
    p_opt.add_argument("--final-backtest", action="store_true", default=False)
    p_opt.add_argument("--report-html", default=None)
    p_opt.set_defaults(func=run_optimize_cmd)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
