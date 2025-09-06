# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Callable, Sequence

from src.presentation.cli.engine import (
    run_optimize,
    run_robustness,
    run_walk_forward,
    run_trade_live,
    run_auto,
)

LOG = logging.getLogger("cli")


def _add_common_io_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", help="Путь к CSV выводу результатов", default=None)


def _add_common_market_args(p: argparse.ArgumentParser) -> None:
    # Глобально-совместимые алиасы для тестов
    p.add_argument("--pair", dest="pair", help="Пара, напр. DOGE_EUR")
    p.add_argument("--exmo-pair", dest="pair", help="Пара EXMO (синоним)", default=None)
    p.add_argument("--candles", dest="candles", help="TF:COUNT (e.g. 5m:2500)")
    p.add_argument("--exmo-candles", dest="candles", help="Алиас для --candles", default=None)
    p.add_argument("--resample", dest="resample", help="Правило ресемплинга (e.g. 5m, 1H)", default=None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot")

    # --- Автопилот / автоэскалация ---
    p.add_argument("--auto", action="store_true",
                   help="Автоподбор: если результатов нет, автоматически увеличить историю/снизить --min-trades.")
    p.add_argument("--auto-candles-step", type=int, default=400)
    p.add_argument("--auto-candles-max", type=int, default=4000)
    p.add_argument("--auto-min-trades-min", type=int, default=1)
    p.add_argument("--auto-attempts", type=int, default=6)

    # --- Глобальные флаги (делаем НЕобязательными для совместимости с тест-парсером)
    p.add_argument("--pair", required=False, help="Trading pair like DOGE_EUR")
    p.add_argument("--candles", required=False, help="TF:COUNT (e.g. 5m:2500)")
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
    _add_common_market_args(auto)
    auto.add_argument("--strategies", nargs="+", default=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    auto.add_argument("--score", choices=["sharpe", "total_pnl"], default="sharpe")
    auto.add_argument("--top-n", type=int, default=10, dest="top_n")
    auto.add_argument("--wf-folds", type=int, default=6)
    auto.add_argument("--wf-train-frac", type=float, default=0.7)
    auto.add_argument("--min-trades", type=int, default=3)
    auto.set_defaults(_handler=run_auto)

    # === OPTIMIZE ===
    opt = sub.add_parser("optimize")
    _add_common_market_args(opt)
    opt.add_argument("--strategy", required=False,
                     choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"], default="ema_adx")
    opt.add_argument("--metric", default="sharpe")
    opt.add_argument("--top-n", type=int, default=10)
    _add_common_io_args(opt)
    opt.set_defaults(_handler=run_optimize)

    # === SWEEP (только для парсинга в тесте) ===
    sw = sub.add_parser("sweep", help="Сканирование сетки параметров (заглушка для тестов парсинга)")
    _add_common_market_args(sw)
    sw.add_argument("--metric", default="sharpe")
    sw.add_argument("--top-n", type=int, default=10)
    _add_common_io_args(sw)
    # обработчик не используется в тесте, поэтому не задаём

    # === ROBUSTNESS ===
    rb = sub.add_parser("robustness")
    _add_common_market_args(rb)
    rb.add_argument("--strategy", required=False,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"], default="ema_adx")
    rb.add_argument("--rb-windows", type=int, default=8)
    rb.add_argument("--min-trades", type=int, default=1)
    rb.add_argument("--metric", default="sharpe")
    _add_common_io_args(rb)
    rb.set_defaults(_handler=run_robustness)

    # === WALK-FORWARD ===
    wf = sub.add_parser("walk-forward")
    _add_common_market_args(wf)
    wf.add_argument("--strategy", required=False,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"], default="ema_adx")
    wf.add_argument("--wf-folds", type=int, default=6)
    wf.add_argument("--folds", dest="wf_folds", type=int)  # алиас для теста
    wf.add_argument("--wf-train-frac", type=float, default=0.7)
    wf.add_argument("--min-trades", type=int, default=1)
    wf.add_argument("--metric", default="sharpe")
    _add_common_io_args(wf)
    wf.set_defaults(_handler=run_walk_forward)

    # === TRADE-LIVE ===
    tl = sub.add_parser("trade-live")
    _add_common_market_args(tl)
    tl.add_argument("--mode", required=True, choices=["observe", "paper"])
    tl.add_argument("--strategy", required=True,
                    choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])

    # параметры ema_adx
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

    # live-опции
    tl.add_argument("--poll-sec", type=int, default=10, help="Интервал опроса (сек)")
    tl.add_argument("--summary-alert", action="store_true", help="Короткое резюме сигналов")

    tl.set_defaults(_handler=run_trade_live)
    return p


def _dispatch(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        # для "sweep" в тесте обработчик не нужен
        return 0
    return int(handler(args) or 0)


def _run_cli(argv: Sequence[str]) -> int:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in argv else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    p = build_parser()
    args = p.parse_args(list(argv))

    if args.debug:
        LOG.debug("argv=%s", list(argv))
        LOG.debug("parsed args=%s", {k: v for k, v in vars(args).items() if k != "_handler"})

    # Переложим алиасы, если заданы только они
    if getattr(args, "pair", None) is None:
        setattr(args, "pair", None)
    if getattr(args, "candles", None) is None:
        setattr(args, "candles", None)

    return _dispatch(args)


def main() -> Callable[..., int]:
    def runner(argv: Sequence[str] | None = None) -> int:
        return _run_cli(argv or [])

    return runner


def cli() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    cli()
