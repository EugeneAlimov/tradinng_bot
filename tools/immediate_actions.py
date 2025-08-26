#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import subprocess
from pathlib import Path
from argparse import ArgumentParser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _print(ok, msg):
    icon = "✅" if ok else "❌"
    print(f"{icon} {msg}")


def check_cli_import():
    try:
        __import__("src.presentation.cli.app")
        _print(True, "CLI module present")
        return True
    except Exception as e:
        _print(False, f"CLI import failed: {e}")
        return False


def run_smoke_sweep():
    """
    Минимальный прогон sweep на маленьком окне.
    Используем --pair/--candles: CLI уже их понимает.
    """
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))

    cmd = [
        sys.executable, "-m", "src.presentation.cli.app", "sweep",
        "--pair", "DOGE_EUR",
        "--candles", "5m:200",
        "--strategies", "auto",
        "--metric", "score",
        "--top-n", "3",
        "--min-trades", "1",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode == 0:
        _print(True, "Smoke sweep ok")
        return True
    else:
        # Покажем только хвост лога, чтобы не засорять вывод
        tail = "\n".join(proc.stderr.splitlines()[-20:])
        _print(False, f"Smoke sweep failed: {tail}")
        return False


def check_filesystem_write():
    try:
        out = ROOT / "out"
        out.mkdir(exist_ok=True)
        probe = out / "health_probe.json"
        probe.write_text(json.dumps({"ok": True}), encoding="utf-8")
        _print(True, "FS write ok")
        return True
    except Exception as e:
        _print(False, f"FS write failed: {e}")
        return False


def main():
    p = ArgumentParser()
    p.add_argument("--health", action="store_true", help="Run health checks")
    args = p.parse_args()

    if args.health:
        ok1 = check_cli_import()
        ok2 = run_smoke_sweep()
        ok3 = check_filesystem_write()

        if ok1 and ok2 and ok3:
            print("\n🏥 HEALTH: OK")
            return 0
        else:
            print("\n🏥 HEALTH: NEEDS ATTENTION")
            return 1

    # Если без флагов — покажем подсказку
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
