#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from typing import Optional, Sequence

try:
    from src.presentation.cli.app import _run_cli  # type: ignore[attr-defined]
except Exception as e:
    def _run_cli(_argv: Sequence[str]) -> int:  # noqa: N802
        print(f"[FATAL] CLI entry not found: {e}", file=sys.stderr)
        return 2


def main(argv: Optional[Sequence[str]] = None):
    """
    Совместимо с проверкой `callable(main())`.
    - Если argv is None → возвращаем вызываемый объект (callable)
    - При обычном запуске используем main(sys.argv[1:])
    """
    if argv is None:
        return lambda: _run_cli(())
    return _run_cli(list(argv))


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
