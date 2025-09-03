# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

from src.presentation.cli.engine import (
    run_optimize,
    run_robustness,
    run_walk_forward,
    run_trade_live,
    run_auto,
)

LOG = logging.getLogger("cli")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot")

    # --- Автопилот / автоэскалация ---
    p.add_argument("--auto", action="store_true",
                   help="Автоподбор: если результатов нет, автоматически увеличить историю/снизить --min-trades.")
    p.add_argument("--auto-candles-step", type=int, default=400)
    p.add_argument("--auto-candles-max", type=int, default=4000)
    p.add_argument("--auto-min-trades-min", type=int, default=1)
    p.add_argument("--auto-attempts", type=int, default=6)

    # Глобальные флаги
    p.add_argument("--pair", required=True, help="Trading pair like DOGE_EUR")
    p.add_argument("--candles", required=True, help="TF:COUNT (e.g. 5m:2500)")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--out-dir", default=os.path.join("out", "data"))
    p.add_argument("--out-prefix", default="")
    p.add_argument("--jsonl", action="store_true")
    p.add_argument("--print-trade-summary", action="store_true")

    # HTTP
    p.add_argument("--http-retries", type=int, default=3)
    p.add_argument("--http-backoff", type=float, default=1.0)
    p.add_argument("--http-timeout", type=float, default=15.0)

    sub = p.add_subparsers(dest="cmd", required=True)

    # AUTO
    auto = sub.add_parser("auto", help="Полный автоподбор (стратегии, сетки, история, min_trades)")
    auto.add_argument("--strategies", nargs="+", default=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    auto.add_argument("--score", choices=["sharpe", "total_pnl"], default="sharpe")
    auto.add_argument("--top-n", type=int, default=10, dest="top_n")
    auto.add_argument("--wf-folds", type=int, default=6)
    auto.add_argument("--wf-train-frac", type=float, default=0.7)
    auto.add_argument("--min-trades", type=int, default=3)
    auto.set_defaults(_handler=run_auto)

    # OPTIMIZE
    opt = sub.add_parser("optimize")
    opt.add_argument("--strategy", required=True,
                     choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    opt.add_argument("--metric", default="sharpe")
    opt.add_argument("--top-n", type=int, default=10)
    opt.add_argument("--min-trades", type=int, default=1)
    opt.set_defaults(_handler=run_optimize)

    # ROBUSTNESS
    rb = sub.add_parser("robustness")
    rb.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    rb.add_argument("--rb-windows", type=int, default=8)
    rb.add_argument("--min-trades", type=int, default=1)
    rb.add_argument("--metric", default="sharpe")
    rb.set_defaults(_handler=run_robustness)

    # WALK-FORWARD
    wf = sub.add_parser("walk-forward")
    wf.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    wf.add_argument("--wf-folds", type=int, default=6)
    wf.add_argument("--wf-train-frac", type=float, default=0.7)
    wf.add_argument("--min-trades", type=int, default=1)
    wf.add_argument("--metric", default="sharpe")
    wf.set_defaults(_handler=run_walk_forward)

    # LIVE
    tl = sub.add_parser("trade-live")
    tl.add_argument("--mode", required=True, choices=["observe", "paper"])
    tl.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])

    # общие параметры стратегий (подхватываются выборочно)
    tl.add_argument("--ema-fast", type=int, default=12)
    tl.add_argument("--ema-slow", type=int, default=21)
    tl.add_argument("--adx-len", type=int, default=14)
    tl.add_argument("--adx-on", type=float, default=25.0)
    tl.add_argument("--adx-off", type=float, default=16.0)
    tl.add_argument("--require-di", action="store_true", default=False)
    tl.add_argument("--atr-len", type=int, default=14)
    tl.add_argument("--atr-mult", type=float, default=2.0)

    # rsi2
    tl.add_argument("--rsi-len", type=int, default=2)
    tl.add_argument("--rsi-buy-below", type=float, default=10.0)
    tl.add_argument("--rsi-sell-above", type=float, default=90.0)

    # bb
    tl.add_argument("--bb-len", type=int, default=20)
    tl.add_argument("--bb-k", type=float, default=2.0)

    # observe
    tl.add_argument("--poll-sec", type=int, default=10)
    tl.add_argument("--summary-alert", action="store_true", default=False)
    tl.add_argument("--observe-rows", type=int, default=20)
    tl.add_argument("--observe-print", choices=["always", "on-new-bar", "never"], default="on-new-bar")
    tl.add_argument("--max-mins", type=int, default=0)
    tl.add_argument("--max-iter", type=int, default=0)

    # deal/fees
    tl.add_argument("--fees-bps", type=float, default=0.0)
    tl.add_argument("--slippage-bps", type=float, default=0.0)
    tl.add_argument("--size", type=float, default=100.0)
    tl.add_argument("--sl-mult", type=float, default=0.0)
    tl.add_argument("--tp-mult", type=float, default=0.0)
    tl.add_argument("--trail-mult", type=float, default=0.0)

    tl.set_defaults(_handler=run_trade_live)

    return p


def _dispatch(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        raise RuntimeError("No handler attached to sub-command")
    return int(handler(args))


def _run_cli(argv: Sequence[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return _dispatch(args)


def main() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
