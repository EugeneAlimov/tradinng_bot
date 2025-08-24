# -*- coding: utf-8 -*-
"""
Thread-safe nonce manager with cross-process file locking.
Linux/macOS: fcntl; Windows: fall back to in-memory only (safe for single process).
"""
from __future__ import annotations

import os
import time
import threading
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:  # POSIX file locking
    import fcntl  # type: ignore
    _HAS_FCNTL = True
except Exception:  # pragma: no cover
    fcntl = None
    _HAS_FCNTL = False


class ThreadSafeNonceManager:
    """
    - гарантирует монотонно возрастающий nonce
    - сохраняет последнее значение в файле атомарно
    - блокирует файл на запись при обновлении в мультипроцессной среде
    """
    def __init__(self, storage_path: str = "data/.nonce"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self._last_nonce = 0
        self._mem_lock = threading.Lock()

        self._lock_file = Path(str(self.storage_path) + ".lock")

        self._load()

    def _load(self) -> None:
        try:
            if self.storage_path.exists():
                raw = self.storage_path.read_text().strip()
                self._last_nonce = int(raw or "0")
                logger.debug("Nonce loaded: %s", self._last_nonce)
        except Exception as e:
            logger.warning("Failed to load nonce %s: %s", self.storage_path, e)
            self._last_nonce = 0

    def get_next_nonce(self) -> int:
        with self._mem_lock:
            now_ms = int(time.time() * 1000)
            new = max(now_ms, self._last_nonce + 1)
            self._persist(new)
            self._last_nonce = new
            return new

    def _persist(self, nonce: int) -> None:
        tmp = Path(str(self.storage_path) + ".tmp")
        if _HAS_FCNTL:
            # POSIX: эксклюзивная блокировка
            try:
                with open(self._lock_file, "w") as lck:
                    fcntl.flock(lck.fileno(), fcntl.LOCK_EX)
                    try:
                        tmp.write_text(str(nonce))
                        tmp.replace(self.storage_path)
                    finally:
                        fcntl.flock(lck.fileno(), fcntl.LOCK_UN)
            except Exception as e:  # pragma: no cover
                logger.error("Failed to persist nonce atomically: %s", e)
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
        else:  # Windows fallback (single-process safe)
            try:
                tmp.write_text(str(nonce))
                tmp.replace(self.storage_path)
            except Exception as e:  # pragma: no cover
                logger.error("Failed to persist nonce: %s", e)

    def reset(self) -> None:
        with self._mem_lock:
            self._last_nonce = 0
            try:
                if self.storage_path.exists():
                    self.storage_path.unlink()
            except Exception:
                pass
            try:
                if self._lock_file.exists():
                    self._lock_file.unlink()
            except Exception:
                pass
