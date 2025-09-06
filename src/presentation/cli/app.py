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

    # --- Глобальные флаги (их нужно ставить ДО подкоманды!)
    p.add_argument("--pair", required=True, help="Trading pair like DOGE_EUR")
    p.add_argument("--candles", required=True, help="TF:COUNT (e.g. 5m:2500)")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--out-dir", default=os.path.join("out", "data"))
    p.add_argument("--out-prefix", default="")
    p.add_argument("--jsonl", action="store_true")
    p.add_argument("--print-trade-summary", action="store_true")

    # --- HTTP
    p.add_argument("--http-retries", type=int, default=3)
    p.add_argument("--http-backoff", type=float, default=1.0)
    p.add_argument("--http-timeout", type=float, default=15.0)

    sub = p.add_subparsers(dest="cmd", required=True)

    # === AUTO ===
    auto = sub.add_parser("auto", help="Полный автоподбор (стратегии, сетки)")
    auto.add_argument("--strategies", nargs="+", default=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    auto.add_argument("--score", choices=["sharpe", "total_pnl"], default="sharpe")
    auto.add_argument("--top-n", type=int, default=10, dest="top_n")
    auto.add_argument("--wf-folds", type=int, default=6)
    auto.add_argument("--wf-train-frac", type=float, default=0.7)
    auto.add_argument("--min-trades", type=int, default=3)
    auto.set_defaults(_handler=run_auto)

    # === OPTIMIZE ===
    opt = sub.add_parser("optimize")
    opt.add_argument("--strategy", required=True,
                     choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    opt.add_argument("--metric", default="sharpe")
    opt.add_argument("--top-n", type=int, default=10)
    opt.set_defaults(_handler=run_optimize)

    # === ROBUSTNESS ===
    rb = sub.add_parser("robustness")
    rb.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    rb.add_argument("--rb-windows", type=int, default=8)
    rb.add_argument("--min-trades", type=int, default=1)
    rb.add_argument("--metric", default="sharpe")
    rb.set_defaults(_handler=run_robustness)

    # === WALK-FORWARD ===
    wf = sub.add_parser("walk-forward")
    wf.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    wf.add_argument("--wf-folds", type=int, default=6)
    wf.add_argument("--wf-train-frac", type=float, default=0.7)
    wf.add_argument("--min-trades", type=int, default=1)
    wf.add_argument("--metric", default="sharpe")
    wf.set_defaults(_handler=run_walk_forward)

    # === TRADE-LIVE ===
    tl = sub.add_parser("trade-live")
    tl.add_argument("--mode", required=True, choices=["observe", "paper"])
    tl.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])

    # общие параметры стратегий (подхватываются выборочно)
    tl.add_argument("--ema-fast", type=int, default=12)
    tl.add_argument("--ema-slow", type=int, default=21)
    tl.add_argument("--adx-len", type=int, default=14)
    tl.add_argument("--adx-on", type=float, default=23.0)
    tl.add_argument("--adx-off", type=float, default=17.0)
    tl.add_argument("--require-di", action="store_true")

    # риск/комиссии
    tl.add_argument("--risk-max-position-pct", type=int, default=25)
    tl.add_argument("--risk-stop-loss-bps", type=int, default=250)
    tl.add_argument("--cooldown-bars", type=int, default=3)
    tl.add_argument("--fee-bps", type=int, default=10)
    tl.add_argument("--slip-bps", type=int, default=2)

    # поддержка твоих флагов для live-режима
    tl.add_argument("--poll-sec", type=int, default=10, help="Интервал опроса (сек), используется в live-цикле")
    tl.add_argument("--summary-alert", action="store_true",
                    help="Если указан — вывод краткого сводного сообщения по сделкам/состоянию")

    tl.set_defaults(_handler=run_trade_live)

    return p


def _dispatch(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        raise SystemExit("No command selected")
    return int(handler(args) or 0)


def _run_cli(argv: Sequence[str]) -> int:
    # Логи — без лишнего дефиса в начале времени:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in argv else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Разбираем аргументы
    p = _build_parser()
    args = p.parse_args(list(argv))

    # При debug — dump аргументов (удобно ловить мусорные escape-символы из шелла)
    if args.debug:
        LOG.debug("argv=%s", list(argv))
        # vars(args) даёт простую dict-представление Namespace
        LOG.debug("parsed args=%s", {k: v for k, v in vars(args).items() if k not in {"_handler"}})

    return _dispatch(args)


def main() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
