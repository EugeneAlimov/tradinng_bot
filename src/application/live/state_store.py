# src/application/live/state_store.py
from __future__ import annotations

import json, os, tempfile
from typing import Any, Dict, Optional


class StateStore:
    """
    Простой файловый KV для снапшота paper-движка.
    Атомарная запись (через временный файл + rename), чтобы переживать падения.
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def save(self, snap: Dict[str, Any]) -> None:
        d = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".snap_", dir=d, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
