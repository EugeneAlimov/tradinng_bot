from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from src.backtest.vectorized_bt import BtConfig, run_backtest_vectorized
from src.backtest.sweep import main as sweep_main, _parse_int_list, _parse_float_list
from src.backtest.walkforward import main as wf_main
from src.backtest.robustness import main as rb_main
from src.backtest.optimize import run_optimize


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def run_backtest_cmd(args):
    bt = BtConfig(
        pair=args.exmo_pair,
        span=args.exmo_candles,
        resample_rule=args.resample,
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        qty_eur=float(args.qty_eur),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        print_summary=True,
    )
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        base = f"{args.exmo_pair}_{args.resample or 'raw'}_{args.fast}-{args.slow}_{stamp}"
        bt.out_trades_csv = Path(args.out_dir) / f"{base}_trades.csv"
        bt.out_equity_csv = Path(args.out_dir) / f"{base}_equity.csv"
    if args.json_metrics:
        bt.out_metrics_json = Path(args.json_metrics)
    res = run_backtest_vectorized(bt)
    _print_json(res["metrics"])


def run_optimize_cmd(args):
    fast_list = _parse_int_list(args.fast_list)
    slow_list = _parse_int_list(args.slow_list)
    hyst_list = _parse_int_list(args.hyst_list)
    cooldown_list = _parse_int_list(args.cooldown_list)
    qty_list = _parse_float_list(args.qty_list)

    out = run_optimize(
        pair=args.exmo_pair,
        span=args.exmo_candles,
        resample=args.resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list,
        cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        robust_metric=str(args.metric), min_trades=int(args.min_trades),
        d_fast=int(args.d_fast), d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst), d_cd=int(args.d_cd),
        wf_top_n=int(args.wf_top_n), folds=int(args.folds),
        min_train_bars=int(args.min_train_bars), min_valid_bars=int(args.min_valid_bars),
        out_dir=Path(args.out_dir), verbose=bool(args.verbose),
        wf_min_pf=args.wf_min_pf, wf_min_return_pct=args.wf_min_return,
        wf_max_dd_pct=args.wf_max_dd, wf_min_winrate_pct=args.wf_min_winrate,
        wf_min_sharpe=args.wf_min_sharpe, wf_min_cagr_pct=args.wf_min_cagr,
        wf_min_calmar=args.wf_min_calmar, wf_min_folds=args.wf_min_folds,
        wf_min_trades=args.wf_min_trades, wf_max_exposure=args.wf_max_exposure,
        rank_by=str(args.rank_by), final_backtest=bool(args.final_backtest),
    )

    print("\n--- OPTIMIZE SUMMARY ---\n")
    print(f"Sweep CSV:     {out['sweep_csv']}")
    print(f"Ranked CSV:    {out['ranked_csv']}")
    print(f"WF results:    {out['wf_csv']}")
    print(f"Report JSON:   {out['report_json']}\n")

    ranked_head = out.get("ranked_head")
    if ranked_head is not None:
        print("Top configs (robustness):")
        try:
            import pandas as pd
            with pd.option_context("display.max_columns", None, "display.width", 200):
                print(ranked_head.to_string(index=False))
        except Exception:
            pass
        print()

    wf_head_df = out.get("wf_head")
    if wf_head_df is not None:
        print("WF means for top configs:")
        try:
            import pandas as pd
            with pd.option_context("display.max_columns", None, "display.width", 200):
                print(wf_head_df.to_string(index=False))
        except Exception:
            pass
        print()

    wf_filtered_df = out.get("wf_filtered")
    total_count = 0 if wf_head_df is None else len(wf_head_df)
    filtered_count = 0 if wf_filtered_df is None else len(wf_filtered_df)
    print(f"WF filtered count: {filtered_count} / total {total_count}")
    print(f"Selected from: {out.get('selected_from')}")
    print(f"Best config after filters (by {args.rank_by}):")
    _print_json(out.get("selected_best"))

    if out.get("final_backtest"):
        print("\nFinal backtest artifacts:")
        _print_json(out["final_backtest"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("tradinng-bot")
    p.add_argument("command", choices=["backtest", "sweep", "walk-forward", "robustness", "optimize"])

    # backwards compat
    p.add_argument("--backtest", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--vectorized", action="store_true", help=argparse.SUPPRESS)

    # universal
    p.add_argument("--exmo-pair", type=str)
    p.add_argument("--exmo-candles", type=str)
    p.add_argument("--resample", type=str, default=None)

    # strategy params
    p.add_argument("--fast", type=int)
    p.add_argument("--slow", type=int)
    p.add_argument("--hysteresis-bps", type=int, default=0)
    p.add_argument("--cooldown-bars", type=int, default=0)
    p.add_argument("--enter-on-start", action="store_true")

    # frictions / risk
    p.add_argument("--fee-bps", type=int, default=10)
    p.add_argument("--slip-bps", type=int, default=0)
    p.add_argument("--qty-eur", type=float, default=50.0)
    p.add_argument("--max-daily-loss-bps", type=int, default=0)

    # artifacts
    p.add_argument("--out-dir", type=str, default=None)
    p.add_argument("--json-metrics", type=str, default=None)

    # sweep
    p.add_argument("--fast-list", type=str, default="5:20:5")
    p.add_argument("--slow-list", type=str, default="20:40:5")
    p.add_argument("--hyst-list", type=str, default="0,5,10,15")
    p.add_argument("--cooldown-list", type=str, default="0,3,5")
    p.add_argument("--qty-list", type=str, default="50,100")
    p.add_argument("--sort-by", type=str, default="calmar")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--verbose", action="store_true")

    # walk-forward
    p.add_argument("--folds", type=int, default=4)
    p.add_argument("--min-train-bars", type=int, default=150)
    p.add_argument("--min-valid-bars", type=int, default=100)

    # robustness
    p.add_argument("--metric", type=str, default="calmar")
    p.add_argument("--min-trades", type=int, default=4)
    p.add_argument("--d-fast", type=int, default=2)
    p.add_argument("--d-slow", type=int, default=5)
    p.add_argument("--d-hyst", type=int, default=5)
    p.add_argument("--d-cd", type=int, default=2)

    # optimize-only: WF filters.py / ranking / final backtest
    p.add_argument("--wf-top-n", type=int, default=5)
    p.add_argument("--wf-min-pf", type=float, default=None)
    p.add_argument("--wf-min-return", type=float, default=None)
    p.add_argument("--wf-max-dd", type=float, default=None)
    p.add_argument("--wf-min-winrate", type=float, default=None)
    p.add_argument("--wf-min-sharpe", type=float, default=None)
    p.add_argument("--wf-min-cagr", type=float, default=None)
    p.add_argument("--wf-min-calmar", type=float, default=None)
    p.add_argument("--wf-min-folds", type=int, default=None)
    p.add_argument("--wf-min-trades", type=float, default=None)
    p.add_argument("--wf-max-exposure", type=float, default=None)
    p.add_argument("--rank-by", type=str, default="oos_profit_factor_mean",
                   choices=["oos_profit_factor_mean","oos_total_return_pct_mean","oos_calmar_mean","oos_sharpe_mean","oos_cagr_pct_mean"])
    p.add_argument("--final-backtest", action="store_true")

    return p


def main():
    args = build_parser().parse_args()

    cmd = args.command
    if cmd == "backtest":
        run_backtest_cmd(args); return
    if cmd == "sweep":
        sweep_main(); return
    if cmd == "walk-forward":
        wf_main(); return
    if cmd == "robustness":
        rb_main(); return
    if cmd == "optimize":
        run_optimize_cmd(args); return


if __name__ == "__main__":
    main()
