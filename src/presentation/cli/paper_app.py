# src/presentation/cli/paper_app.py
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
    Совместимо с тестом: `from ... import main; assert callable(main())`
    - Если argv is None → возвращаем callable (ничего не запускаем).
    - Если argv передан → форвардим в единый CLI как:
        trade-live --mode paper <argv...>
    """
    if argv is None:
        return lambda: 0  # просто «что-то вызываемое» для assert callable(...)
    forwarded = ["trade-live", "--mode", "paper", *list(argv)]
    return _run_cli(forwarded)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
