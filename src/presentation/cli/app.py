# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from src.presentation.cli.paper_trade_cmd import main as paper_trade_main


def build_root_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tb", description="Trading Bot CLI (intrabar-enabled)")
    sub = p.add_subparsers(dest="command", required=True)

    # paper-trade
    paper = sub.add_parser("paper-trade", help="Run intrabar paper trading for EMA+ADX strategy.")
    # все аргументы делегируем парсеру из paper_trade_cmd
    # но для удобства: просто позволим прокинуть дальше argv без повторного описания
    paper.add_argument("args", nargs=argparse.REMAINDER, help="Args forwarded to paper_trade_cmd.")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [cli] %(message)s")
    parser = build_root_parser()
    ns = parser.parse_args(argv)

    if ns.command == "paper-trade":
        # передаём всё, что после 'paper-trade'
        fwd = ns.args or []
        # удаляем возможный '--' в начале
        if len(fwd) and fwd[0] == "--":
            fwd = fwd[1:]
        return paper_trade_main(fwd)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
