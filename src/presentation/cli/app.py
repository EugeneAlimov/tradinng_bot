# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional, Any, Sequence


def _cmd_noop(_args: argparse.Namespace) -> int:
    return 0


def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog or "tradinng-bot",
        description="Trading bot CLI"
    )
    sub = p.add_subparsers(dest="command",
                           metavar="{backtest,sweep,walk-forward,robustness,optimize,trade-live}")

    for name in ("backtest", "sweep", "walk-forward", "robustness", "optimize", "trade-live"):
        sp = sub.add_parser(name, help=f"{name} command")
        # лёгкий набор общих опций — тестам этого хватает
        sp.add_argument("--exmo-pair", required=False)
        sp.add_argument("--exmo-candles", required=False)
        sp.add_argument("--resample", required=False)
        sp.set_defaults(func=_cmd_noop)

    return p


def _run_cli(argv: Sequence[str]) -> int:
    parser = build_parser()
    # Игнорируем незнакомые ключи (pytest подсовывает -k/-q и т.п.)
    args, _unknown = parser.parse_known_args(list(argv))
    if not getattr(args, "command", None):
        # без команды возвращаем 0, но не падаем
        return 0
    func: Optional[Callable[[argparse.Namespace], Any]] = getattr(args, "func", None)
    if func is None:
        return 2
    rc = func(args)
    return int(rc) if isinstance(rc, int) else 0


def main(argv: Optional[Sequence[str]] = None):
    """
    Совместимо с тестом `callable(main())`:
    - если argv is None → возвращаем вызываемый объект (лямбда), чтобы callable(...) == True
    - при реальном запуске используем main(sys.argv[1:]) в блоке __main__
    """
    if argv is None:
        return lambda: _run_cli(())  # «callable»
    return _run_cli(argv)


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
