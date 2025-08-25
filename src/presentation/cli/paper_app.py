# src/presentation/cli/paper_app.py
"""
Обёртка paper-режима:
- форсит 'trade-live --mode paper'
- принимает те же флаги, что и основное CLI
- main() возвращает вызываемую функцию для вашего теста.
"""
from __future__ import annotations

import sys
from typing import List

from src.presentation.cli import app as app_cli


def _strip_mode(argv: List[str]) -> List[str]:
    out: List[str] = []
    skip_next = False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a == "--mode":
            skip_next = True
            continue
        if a.startswith("--mode=") or a == "trade-live":
            continue
        out.append(a)
    return out


def run(argv: List[str] | None = None) -> int:
    user_argv = list(sys.argv[1:] if argv is None else argv)
    forwarded = ["trade-live", "--mode", "paper"] + _strip_mode(user_argv)
    return app_cli._run_cli(forwarded)


def main():
    return run


if __name__ == "__main__":
    sys.exit(run())
