# src/infra/log.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Optional


class NdjsonWriter:
    def __init__(self, path: Optional[str]):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, obj: Any) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line)
