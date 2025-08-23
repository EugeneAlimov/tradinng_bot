# main.py
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from src.backtest.vectorized_bt import BtConfig, run_backtest_vectorized
from src.backtest.sweep import run_sweep, SweepCfg, _parse_int_list, _parse_float_list
from src.backtest.walkforward import WFConfig, run_walkforward  # для отдельного вызова WF
from src.backtest.robustness import compute_stability as rb_compute, _resolve_csv as rb_resolve

# NEW: оркестратор
from src.backtest.optimize import run_optimize

import pandas as pd


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tradinng-bot",
        description="EXMO SMA-crossover bot • backtests, sweep, walk-forward, robustness, optimize",
    )
    sub = p.add_subparsers(dest="cmd", required=False)

    # backtest
    pb = sub.add_parser("backtest", help="Run a single backtest")
    pb.add_argument("--vectorized", action="store_true")
    pb.add_argument("--exmo-pair", type=str, default="DOGE_EUR")
    pb.add_argument("--exmo-candles", type=str, default="1m:2000")
    pb.add_argument("--resample", type=str, default=None)
    pb.add_argument("--fast", type=int, default=6)
    pb.add_argument("--slow", type=int, default=25)
    pb.add_argument("--hysteresis-bps", type=int, default=0)
    pb.add_argument("--cooldown-bars", type=int, default=0)
    pb.add_argument("--enter-on-start", action="store_true")
    pb.add_argument("--fee-bps", type=int, default=10)
    pb.add_argument("--slip-bps", type=int, default=0)
    pb.add_argument("--qty-eur", type=float, default=50.0)
    pb.add_argument("--max-daily-loss-bps", type=int, default=0)
    pb.add_argument("--out-dir", type=str, default="data/backtests")
    pb.add_argument("--json-metrics", type=str, default=None)

    # sweep
    ps = sub.add_parser("sweep", help="Grid search with one aggregated CSV")
    ps.add_argument("--exmo-pair", required=True, type=str)
    ps.add_argument("--exmo-candles", required=True, type=str)
    ps.add_argument("--resample", default=None, type=str)
    ps.add_argument("--fast-list", default="5:15:5", type=str)
    ps.add_argument("--slow-list", default="20:40:5", type=str)
    ps.add_argument("--hyst-list", default="0,5,10,15", type=str)
    ps.add_argument("--cooldown-list", default="0,3,5", type=str)
    ps.add_argument("--qty-list", default="50,100", type=str)
    ps.add_argument("--fee-bps", default=10, type=int)
    ps.add_argument("--slip-bps", default=0, type=int)
    ps.add_argument("--max-daily-loss-bps", default=0, type=int)
    ps.add_argument("--out-dir", default="data/sweep", type=str)
    ps.add_argument("--sort-by", default="calmar", type=str)
    ps.add_argument("--top-n", default=20, type=int)
    ps.add_argument("--save-per-config-csv", action="store_true")
    ps.add_argument("--save-per-config-metrics", action="store_true")
    ps.add_argument("--verbose", action="store_true")
    ps.add_argument("--refetch-per-config", action="store_true")

    # walk-forward
    pw = sub.add_parser("walk-forward", help="Walk-forward validation")
    pw.add_argument("--exmo-pair", required=True)
    pw.add_argument("--exmo-candles", required=True)
    pw.add_argument("--resample", default=None)
    pw.add_argument("--fast", required=True, type=int)
    pw.add_argument("--slow", required=True, type=int)
    pw.add_argument("--hysteresis-bps", default=0, type=int)
    pw.add_argument("--cooldown-bars", default=0, type=int)
    pw.add_argument("--enter-on-start", action="store_true")
    pw.add_argument("--fee-bps", default=10, type=int)
    pw.add_argument("--slip-bps", default=0, type=int)
    pw.add_argument("--qty-eur", default=50.0, type=float)
    pw.add_argument("--max-daily-loss-bps", default=0, type=int)
    pw.add_argument("--folds", default=4, type=int)
    pw.add_argument("--min-train-bars", default=150, type=int)
    pw.add_argument("--min-valid-bars", default=100, type=int)
    pw.add_argument("--out-dir", default="data/walkforward")
    pw.add_argument("--out-json", default=None)
    pw.add_argument("--out-csv", default=None)

    # robustness
    pr = sub.add_parser("robustness", help="Neighborhood robustness ranking for a sweep CSV")
    pr.add_argument("--sweep-csv", required=True, type=str,
                    help="Path/dir/glob, e.g. 'data/sweep/sweep_*DOGE_EUR_5m_*.csv'")
    pr.add_argument("--metric", default="calmar", type=str)
    pr.add_argument("--min-trades", default=4, type=int)
    pr.add_argument("--d-fast", default=2, type=int)
    pr.add_argument("--d-slow", default=5, type=int)
    pr.add_argument("--d-hyst", default=5, type=int)
    pr.add_argument("--d-cd", default=2, type=int)
    pr.add_argument("--out-csv", default=None, type=str)
    pr.add_argument("--top-n", default=20, type=int)

    # optimize (новая)
    po = sub.add_parser("optimize", help="Sweep → robustness → walk-forward for top-N → report")
    # данные + сетка
    po.add_argument("--exmo-pair", required=True, type=str)
    po.add_argument("--exmo-candles", required=True, type=str)
    po.add_argument("--resample", default=None, type=str)
    po.add_argument("--fast-list", default="5:20:5", type=str)
    po.add_argument("--slow-list", default="20:40:5", type=str)
    po.add_argument("--hyst-list", default="0,5,10,15", type=str)
    po.add_argument("--cooldown-list", default="0,3,5", type=str)
    po.add_argument("--qty-list", default="50,100", type=str)
    po.add_argument("--fee-bps", default=10, type=int)
    po.add_argument("--slip-bps", default=0, type=int)
    po.add_argument("--max-daily-loss-bps", default=0, type=int)
    # робастность
    po.add_argument("--metric", default="calmar", type=str, help="Metric for robustness ranking")
    po.add_argument("--min-trades", default=4, type=int)
    po.add_argument("--d-fast", default=2, type=int)
    po.add_argument("--d-slow", default=5, type=int)
    po.add_argument("--d-hyst", default=5, type=int)
    po.add_argument("--d-cd", default=2, type=int)
    po.add_argument("--wf-top-n", default=5, type=int, help="How many top configs to run WF on")
    # WF
    po.add_argument("--folds", default=4, type=int)
    po.add_argument("--min-train-bars", default=150, type=int)
    po.add_argument("--min-valid-bars", default=100, type=int)
    # вывод
    po.add_argument("--out-dir", default="data/optimize", type=str)
    po.add_argument("--verbose", action="store_true")

    # legacy flags (old style)
    p.add_argument("--backtest", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--vectorized", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--exmo-pair", type=str, help=argparse.SUPPRESS)
    p.add_argument("--exmo-candles", type=str, help=argparse.SUPPRESS)
    p.add_argument("--resample", type=str, help=argparse.SUPPRESS)
    p.add_argument("--fast", type=int, help=argparse.SUPPRESS)
    p.add_argument("--slow", type=int, help=argparse.SUPPRESS)
    p.add_argument("--hysteresis-bps", type=int, help=argparse.SUPPRESS)
    p.add_argument("--cooldown-bars", type=int, help=argparse.SUPPRESS)
    p.add_argument("--enter-on-start", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--fee-bps", type=int, help=argparse.SUPPRESS)
    p.add_argument("--slip-bps", type=int, help=argparse.SUPPRESS)
    p.add_argument("--qty-eur", type=float, help=argparse.SUPPRESS)
    p.add_argument("--max-daily-loss-bps", type=int, help=argparse.SUPPRESS)
    p.add_argument("--out-dir", type=str, help=argparse.SUPPRESS)
    p.add_argument("--json-metrics", type=str, help=argparse.SUPPRESS)

    return p


def run_backtest_cmd(args: argparse.Namespace) -> None:
    cfg = BtConfig(
        pair=args.exmo_pair,
        span=args.exmo_candles,
        resample_rule=args.resample,
        fast=int(args.fast), slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        enter_on_start=bool(args.enter_on_start),
        fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps),
        qty_eur=float(args.qty_eur),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        print_summary=True,
    )

    od = Path(args.out_dir); od.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    base = f"{cfg.pair.replace('/', '_')}_{(cfg.resample_rule or 'raw')}_{cfg.fast}-{cfg.slow}_{stamp}"
    cfg.out_trades_csv = od / f"{base}_trades.csv"
    cfg.out_equity_csv = od / f"{base}_equity.csv"
    if getattr(args, "json_metrics", None):
        cfg.out_metrics_json = Path(args.json_metrics)

    run_backtest_vectorized(cfg)


def run_sweep_cmd(args: argparse.Namespace) -> None:
    scfg = SweepCfg(
        pair=args.exmo_pair, span=args.exmo_candles, resample=args.resample,
        fast_list=_parse_int_list(args.fast_list), slow_list=_parse_int_list(args.slow_list),
        hyst_list=_parse_int_list(args.hyst_list), cooldown_list=_parse_int_list(args.cooldown_list),
        qty_list=_parse_float_list(args.qty_list),
        fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        out_dir=Path(args.out_dir), sort_by=str(args.sort_by), top_n=int(args.top_n),
        save_per_config_csv=bool(args.save_per_config_csv),
        save_per_config_metrics=bool(args.save_per_config_metrics),
        quiet_runs=(not bool(args.verbose)),
        refetch_per_config=bool(getattr(args, "refetch_per_config", False)),
    )
    out_csv = run_sweep(scfg)
    print(f"\nSweep saved to: {out_csv}")


def run_walkforward_cmd(args: argparse.Namespace) -> None:
    wcfg = WFConfig(
        pair=args.exmo_pair, span=args.exmo_candles, resample=args.resample,
        fast=int(args.fast), slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps), cooldown_bars=int(args.cooldown_bars),
        enter_on_start=bool(args.enter_on_start),
        fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps), qty_eur=float(args.qty_eur),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        folds=int(args.folds), min_train_bars=int(args.min_train_bars), min_valid_bars=int(args.min_valid_bars),
        out_dir=Path(args.out_dir),
        out_json=Path(args.out_json) if args.out_json else None,
        out_csv=Path(args.out_csv) if args.out_csv else None,
    )
    run_walkforward(wcfg)


def run_robustness_cmd(args: argparse.Namespace) -> None:
    resolved = rb_resolve(args.sweep_csv)
    ranked = rb_compute(
        csv_path=resolved, min_trades=int(args.min_trades), metric=str(args.metric),
        d_fast=int(args.d_fast), d_slow=int(args.d_slow), d_hyst=int(args.d_hyst), d_cd=int(args.d_cd),
    )
    if args.out_csv:
        out_p = Path(args.out_csv); out_p.parent.mkdir(parents=True, exist_ok=True)
        ranked.to_csv(out_p, index=False)

    print(f"\nUsing sweep CSV: {resolved}\n")
    top = ranked.head(int(args.top_n))
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(top.to_string(index=False))
    if args.out_csv:
        print(f"\nSaved ranked table to: {args.out_csv}")


def run_optimize_cmd(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    session_dir = out_dir / f"opt_{args.exmo_pair.replace('/','_')}_{(args.resample or 'raw')}_{stamp}"
    session_dir.mkdir(parents=True, exist_ok=True)

    res = run_optimize(
        pair=args.exmo_pair,
        span=args.exmo_candles,
        resample=args.resample,
        fast_list=_parse_int_list(args.fast_list),
        slow_list=_parse_int_list(args.slow_list),
        hyst_list=_parse_int_list(args.hyst_list),
        cooldown_list=_parse_int_list(args.cooldown_list),
        qty_list=_parse_float_list(args.qty_list),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        robust_metric=str(args.metric),
        min_trades=int(args.min_trades),
        d_fast=int(args.d_fast), d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst), d_cd=int(args.d_cd),
        wf_top_n=int(args.wf_top_n),
        folds=int(args.folds), min_train_bars=int(args.min_train_bars), min_valid_bars=int(args.min_valid_bars),
        out_dir=session_dir,
        verbose=bool(args.verbose),
    )

    # Красивое резюме в консоль
    print("\n--- OPTIMIZE SUMMARY ---\n")
    print(f"Sweep CSV:     {res['sweep_csv']}")
    print(f"Ranked CSV:    {res['ranked_csv']}")
    print(f"WF results:    {res['wf_csv']}")
    print(f"Report JSON:   {res['report_json']}")
    print("\nTop configs (robustness):")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(res["ranked_head"].to_string(index=False))
    print("\nWF means for top configs:")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(res["wf_head"].to_string(index=False))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "backtest":
        if not args.vectorized:
            raise SystemExit("Only --vectorized engine is implemented.")
        run_backtest_cmd(args); return
    if args.cmd == "sweep":
        run_sweep_cmd(args); return
    if args.cmd == "walk-forward":
        run_walkforward_cmd(args); return
    if args.cmd == "robustness":
        run_robustness_cmd(args); return
    if args.cmd == "optimize":
        run_optimize_cmd(args); return

    # Legacy flags path
    if getattr(args, "backtest", False) and getattr(args, "vectorized", False):
        class _Obj: pass
        la = _Obj()
        la.exmo_pair = args.exmo_pair or "DOGE_EUR"
        la.exmo_candles = args.exmo_candles or "1m:2000"
        la.resample = args.resample
        la.fast = args.fast or 6
        la.slow = args.slow or 25
        la.hysteresis_bps = args.hysteresis_bps or 0
        la.cooldown_bars = args.cooldown_bars or 0
        la.enter_on_start = bool(args.enter_on_start)
        la.fee_bps = args.fee_bps or 10
        la.slip_bps = args.slip_bps or 0
        la.qty_eur = args.qty_eur or 50.0
        la.max_daily_loss_bps = args.max_daily_loss_bps or 0
        la.out_dir = args.out_dir or "data/backtests"
        la.json_metrics = args.json_metrics
        run_backtest_cmd(la); return

    parser.print_help()


if __name__ == "__main__":
    main()
