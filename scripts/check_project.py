#!/usr/bin/env python3
"""
Массовая проверка импортов проекта.

Запуск:
  PYTHONPATH=. python scripts/check_project.py
  PYTHONPATH=. python scripts/check_project.py --skip "(live_trade|websocket)"
  PYTHONPATH=. python scripts/check_project.py --json > import_report.json && jq .

Код выхода:
  0  — все импорты успешны
  1+ — есть сбои (кол-во упавших модулей)
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import re
import sys
import traceback
from typing import Dict, List


def discover_src_modules() -> List[str]:
    # Гарантируем, что src импортируемый
    if "." not in sys.path:
        sys.path.insert(0, ".")
    import src  # noqa: F401

    modules: List[str] = []
    for m in pkgutil.walk_packages(src.__path__, prefix="src."):  # type: ignore[attr-defined]
        modules.append(m.name)
    return sorted(modules)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", help="regexp для модулей, которые пропускаем", default=None)
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    args = ap.parse_args()

    skip_re = re.compile(args.skip) if args.skip else None

    checked: List[str] = []
    failures: Dict[str, Dict[str, str]] = {}
    for modname in discover_src_modules():
        if skip_re and skip_re.search(modname):
            continue
        try:
            importlib.import_module(modname)
            checked.append(modname)
        except Exception as e:
            tb = traceback.format_exc()
            failures[modname] = {"error": f"{e.__class__.__name__}: {e}", "traceback": tb}

    if args.json:
        out = {
            "checked_count": len(checked) + len(failures),
            "ok_count": len(checked),
            "fail_count": len(failures),
            "failed": failures,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for ok in checked:
            print(f"[OK]   {ok}")
        for name, info in failures.items():
            print(f"[FAIL] {name} -> {info['error']}")
            print("       details:", info["error"])

        print("\n--- SUMMARY ---")
        print(f"Checked: {len(checked) + len(failures)} modules")
        print(f"Failed : {len(failures)} modules")

        if failures:
            print("\nBroken imports:")
            for name, info in failures.items():
                print(f" - {name}: {info['error']}")

        if not (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
            print("\n(подсказка) Запускай из корня проекта с PYTHONPATH=.")

    return min(255, len(failures))


if __name__ == "__main__":
    sys.exit(main())
