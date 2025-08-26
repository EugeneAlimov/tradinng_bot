#!/usr/bin/env python3
import os
import sys
import subprocess
import tempfile
from pathlib import Path


def _ok(msg): print(f"✅ {msg}")


def _bad(msg): print(f"❌ {msg}")


def _run(cmd, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, env=env or os.environ)


def health():
    # 1) Проверка доступности CLI
    r = _run(["python", "-m", "src.presentation.cli.app", "-h"])
    if r.returncode == 0:
        _ok("CLI module present")
    else:
        _bad("CLI module missing")
        print(r.stderr.strip())
        return 1

    # 2) Быстрый smoke sweep (малое окно), используем ИМЕННО --exmo-* флаги
    env = {**os.environ, "PYTHONPATH": "."}
    cmd = [
        "python", "-m", "src.presentation.cli.app", "sweep",
        "--exmo-pair", "DOGE_EUR",
        "--exmo-candles", "5m:200",
        "--strategies", "auto",
        "--metric", "score",
        "--top-n", "2",
        "--min-trades", "1",
    ]
    r2 = _run(cmd, env=env)
    if r2.returncode == 0:
        _ok("Smoke sweep passed")
    else:
        _bad(f"Smoke sweep failed: {r2.stdout}{r2.stderr}")

    # 3) Тест записи на диск
    try:
        Path("out").mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir="out", delete=True) as f:
            f.write(b"ping")
            f.flush()
        _ok("FS write ok")
    except Exception as e:
        _bad(f"FS write failed: {e}")

    print("\n🏥 HEALTH:", "OK" if r2.returncode == 0 else "NEEDS ATTENTION")
    return 0 if r2.returncode == 0 else 2


if __name__ == "__main__":
    if "--health" in sys.argv:
        sys.exit(health())
    print("Usage: python tools/immediate_actions.py --health")
