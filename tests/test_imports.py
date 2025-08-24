"""
Проверка, что все модули src.* импортируются (кроме опционального skip).
Запуск:
  PYTHONPATH=. pytest -q tests/test_imports.py
Можно ограничить тест окружением:
  IMPORT_CHECK_SKIP="(live_trade|websocket)" PYTHONPATH=. pytest -q
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import re
import sys
import types


def _discover() -> list[str]:
    if "." not in sys.path:
        sys.path.insert(0, ".")
    src = importlib.import_module("src")
    mods: list[str] = []
    for m in pkgutil.walk_packages(src.__path__, prefix="src."):  # type: ignore[attr-defined]
        mods.append(m.name)
    return sorted(mods)


def test_all_imports_ok():
    skip_pat = os.environ.get("IMPORT_CHECK_SKIP")
    skip_re = re.compile(skip_pat) if skip_pat else None

    failures: dict[str, str] = {}
    for modname in _discover():
        if skip_re and skip_re.search(modname):
            continue
        try:
            m = importlib.import_module(modname)
            assert isinstance(m, types.ModuleType)
        except Exception as e:
            failures[modname] = f"{e.__class__.__name__}: {e}"

    assert not failures, f"Импорт провалился для модулей: {failures}"
