# src/presentation/cli/app.py
from __future__ import annotations

import sys
import argparse
from importlib import import_module
from typing import List, Optional

SUBCMDS = {
    # имя подкоманды -> dotted-path модуля с main(argv: Optional[List[str]]) -> int|None
    "trade-live": "src.presentation.cli.trade_live_cmd",
    # задел под будущие команды — когда появятся, просто создадим соответствующие модули
    "optimize": "src.presentation.cli.optimize_cmd",
    "sweep": "src.presentation.cli.sweep_cmd",
    "walk-forward": "src.presentation.cli.walk_forward_cmd",
    "robustness": "src.presentation.cli.robustness_cmd",
}


def build_top_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tb", description="Trading bot CLI")
    sp = p.add_subparsers(dest="command", required=True)
    for name in SUBCMDS:
        sp.add_parser(name, help=f"{name} subcommand (delegated)")
    return p


def _call_module_main(module_path: str, argv: Optional[List[str]]) -> int:
    mod = import_module(module_path)
    fn = getattr(mod, "main", None)
    if fn is None:
        raise SystemExit(f"Module {module_path} does not define main()")

    try:
        # предпочтительно — если команда принимает argv явно
        ret = fn(argv=argv)
    except TypeError:
        # back-compat: если у команды старая сигнатура main()
        sys.argv = [module_path.split(".")[-1]] + (argv or [])
        ret = fn()

    return int(ret) if ret is not None else 0


def main(argv: Optional[List[str]] = None) -> int:
    top = build_top_parser()
    # ВАЖНО: парсим только имя подкоманды, остальные аргументы отдаём модулю подкоманды
    ns, rest = top.parse_known_args(argv)

    module_path = SUBCMDS.get(ns.command)
    if not module_path:
        top.print_help()
        return 2

    return _call_module_main(module_path, rest)


if __name__ == "__main__":
    raise SystemExit(main())
