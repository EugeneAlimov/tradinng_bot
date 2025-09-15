# scripts/env_check.py
from __future__ import annotations

import importlib
import sys

WANTED = {
    # core data
    "numpy": "2.3.3",
    "pandas": "2.3.2",
    "scipy": "1.16.2",
    "pyarrow": "21.0.0",

    # storage
    "duckdb": "1.3.2",

    # async/http
    "aiohttp": "3.12.15",
    "yarl": "1.20.1",
    "multidict": "6.6.4",
    "httpx": "0.28.1",
    "httpcore": "1.0.9",
    "anyio": "4.10.0",

    # api/server
    "fastapi": "0.116.1",
    "starlette": "0.47.2",
    "pydantic": "2.11.4",
    "typing_extensions": "4.15.0",

    # viz
    "matplotlib": "3.10.6",
    "kiwisolver": "1.4.9",
    "fonttools": "4.59.2",
    "Pillow": "11.3.0",  # модуль называется Pillow, пакет — pillow

    # misc/dev
    "requests": "2.32.5",
    "rich": "14.1.0",
    "pytest": "8.4.2",
    "pytest_asyncio": "1.2.0",
    "pytest_cov": "7.0.0",
    "mypy": "1.18.1",
    "flake8": "7.3.0",
    "black": "25.1.0",
}

# некоторые модули имеют иное внутреннее имя
ALIASES = {
    "pytest_asyncio": "pytest_asyncio",
    "pytest_cov": "pytest_cov",
    "Pillow": "PIL",
}


def get_version(modname: str) -> str | None:
    try:
        m = importlib.import_module(ALIASES.get(modname, modname))
    except Exception:
        return None
    for attr in ("__version__", "VERSION", "version"):
        v = getattr(m, attr, None)
        if v is None:
            continue
        # нормализуем tuple -> str
        if isinstance(v, tuple):
            return ".".join(map(str, v))
        return str(v)
    # у некоторых подмодулей версия лежит глубже
    if modname == "matplotlib":
        try:
            import matplotlib
            return matplotlib.__version__
        except Exception:
            return None
    return None


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    mismatches = []
    for name, want in WANTED.items():
        have = get_version(name)
        status = "OK" if have == want else ("MISSING" if have is None else f"!= {want}")
        print(f"{name:18s} installed={have!s:12s} required={want:10s}  [{status}]")
        if have != want:
            mismatches.append((name, have, want))
    if mismatches:
        print("\nERROR: version mismatches detected:")
        for name, have, want in mismatches:
            print(f" - {name}: have={have}, want={want}")
        return 1
    print("\nAll versions match the stable profile ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
