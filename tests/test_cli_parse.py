"""
Smoke-тест CLI: проверяем, что парсер строится и базовые команды парсятся.
Не делает сетевых вызовов/бэктеста.
"""
from __future__ import annotations

import sys
import types
import importlib


def test_cli_parser_builds_and_parses():
    app = importlib.import_module("src.presentation.cli.app")
    assert hasattr(app, "build_parser"), "build_parser() not found in CLI app"

    parser = app.build_parser()  # type: ignore[attr-defined]
    assert parser is not None

    # Несколько команд на парсинг (без выполнения)
    samples = [
        ["optimize", "--exmo-pair", "DOGE_EUR", "--exmo-candles", "1m:100", "--resample", "5m"],
        ["sweep", "--exmo-pair", "DOGE_EUR", "--exmo-candles", "1m:100", "--resample", "5m"],
        ["walk-forward", "--exmo-pair", "DOGE_EUR", "--exmo-candles", "1m:100", "--resample", "5m", "--folds", "2"],
        ["robustness", "--csv", "data/tmp.csv"],
    ]

    for argv in samples:
        ns = parser.parse_args(argv)
        assert ns is not None
        # важно: не вызываем ns.func, только проверяем, что парсинг успешен
