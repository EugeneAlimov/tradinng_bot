# src/backtest/manifest.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.backtest.selector import make_artifact_path


def write_manifest(
        out_dir: str,
        out_prefix: str,
        pair: str,
        candles: str,
        entries: List[Dict[str, Any]],
        *,
        stem: str = "manifest",
) -> str:
    """
    Записывает manifest.v1 — список артефактов единого «сеанса сохранения».
    Возвращает путь к созданному манифесту.
    """
    doc = {
        "schema_version": "manifest.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pair": str(pair),
        "candles": str(candles),
        "entries": entries,
    }
    path = make_artifact_path(out_dir, out_prefix, pair, candles, stem, "json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=2))
    return path
