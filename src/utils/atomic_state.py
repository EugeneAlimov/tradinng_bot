# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from pathlib import Path

# fcntl есть на Linux/macOS; на Windows используем no-op fallback
try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None  # type: ignore


class AtomicState:
    """
    Атомарная запись JSON-состояния с advisory lock.
    - пишет во временный файл и делает os.replace
    - блокирует .lock файл на время записи
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # открываем/создаём lock-файл
        with self.lock_path.open("w") as lf:
            # блокируем если доступен fcntl
            if fcntl is not None:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.path)
            finally:
                if fcntl is not None:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
