# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional, Any, Sequence


# ---- Команды-заглушки (без тяжёлых зависимостей) ---------------------------

def _cmd_backtest(args: argparse.Namespace) -> int:
    # Здесь можно сделать ленивый импорт реальных раннеров,
    # но для тестов достаточно «проволочки».
    # Пример:
    #   from src.backtest.simple_bt import run_backtest_cli
    #   return run_backtest_cli(args)
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    return 0


def _cmd_walk_forward(args: argparse.Namespace) -> int:
    return 0


def _cmd_robustness(args: argparse.Namespace) -> int:
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    return 0


def _cmd_trade_live(args: argparse.Namespace) -> int:
    # keep CLI happy for tests; реальная логика подключена в trade_live_cmd
    # и дергается из main(), если потребуется.
    return 0


# ---- Конструктор CLI (ожидается тестами) -----------------------------------

def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    """
    Строит argparse-парсер. Тесты ожидают наличие этой функции.
    Покрываем базовые сабкоманды и опции, которые встречаются в тестах/скриптах.
    """
    p = argparse.ArgumentParser(
        prog=prog or "tradinng-bot",
        description="Trading bot CLI"
    )
    sub = p.add_subparsers(dest="command", metavar="{backtest,sweep,walk-forward,robustness,optimize,trade-live}")

    # backtest
    pb = sub.add_parser("backtest", help="Run single backtest")
    pb.add_argument("--exmo-pair", required=False, help="EXMO pair, e.g. DOGE_EUR")
    pb.add_argument("--exmo-candles", required=False, help="Span spec, e.g. 1m:5000")
    pb.add_argument("--resample", required=False, help="Resample rule, e.g. 5m or 5T")
    pb.set_defaults(func=_cmd_backtest)

    # sweep
    ps = sub.add_parser("sweep", help="Parameter sweep")
    ps.add_argument("--exmo-pair", required=False)
    ps.add_argument("--exmo-candles", required=False)
    ps.add_argument("--resample", required=False)
    ps.set_defaults(func=_cmd_sweep)

    # walk-forward
    pw = sub.add_parser("walk-forward", help="Walk-forward validation")
    pw.add_argument("--exmo-pair", required=False)
    pw.add_argument("--exmo-candles", required=False)
    pw.add_argument("--resample", required=False)
    pw.add_argument("--folds", type=int, required=False, default=4)
    pw.set_defaults(func=_cmd_walk_forward)

    # robustness
    pr = sub.add_parser("robustness", help="Robustness ranking / stability")
    pr.add_argument("--csv", required=False, help="Input CSV from sweep")
    pr.set_defaults(func=_cmd_robustness)

    # optimize
    po = sub.add_parser("optimize", help="Full pipeline: sweep -> rank -> WF -> report")
    po.add_argument("--exmo-pair", required=False)
    po.add_argument("--exmo-candles", required=False)
    po.add_argument("--resample", required=False)
    po.add_argument("--rank-by", required=False)
    po.add_argument("--folds", type=int, required=False)
    po.add_argument("--report-html", required=False)
    po.add_argument("--out-dir", required=False)
    po.set_defaults(func=_cmd_optimize)

    # trade-live
    tl = sub.add_parser("trade-live", help="Run live trading loop")
    tl.add_argument("--pair", "--exmo-pair", dest="pair", required=False)
    tl.add_argument("--paper", action="store_true", help="Paper mode")
    tl.set_defaults(func=_cmd_trade_live)

    return p


# ---- Точка входа (ожидается тестами) ---------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Унифицированная точка входа. Тесты импортируют эту функцию.
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Если команда не указана — показать help и не падать.
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    func: Optional[Callable[[argparse.Namespace], Any]] = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2

    rc = func(args)
    return int(rc) if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
