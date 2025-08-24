# src/infrastructure/exchange/nonce_manager.py
from __future__ import annotations

import os
import fcntl
import threading
from pathlib import Path
from typing import Optional
import time
import logging

logger = logging.getLogger(__name__)


class ThreadSafeNonceManager:
    """
    Монотонный nonce с файловой блокировкой и атомарной записью (POSIX).
    Безопасен для многопоточности и мультипроцесса.
    """
    def __init__(self, storage_path: str = "data/.exmo_nonce"):
        self._path = Path(storage_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._mem_lock = threading.Lock()
        self._last_nonce: int = 0
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._last_nonce = int(self._path.read_text().strip() or "0")
                logger.debug("nonce loaded: %s", self._last_nonce)
        except Exception as e:
            logger.warning("nonce load failed: %s", e)
            self._last_nonce = 0

    def _persist_atomic(self, nonce: int) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(self._lock_path, "w") as lfd:
            fcntl.flock(lfd.fileno(), fcntl.LOCK_EX)
            try:
                tmp.write_text(str(nonce))
                tmp.replace(self._path)
            finally:
                fcntl.flock(lfd.fileno(), fcntl.LOCK_UN)

    def next(self) -> int:
        with self._mem_lock:
            now_ms = int(time.time() * 1000)
            new_nonce = max(now_ms, self._last_nonce + 1)
            try:
                self._persist_atomic(new_nonce)
            except Exception as e:
                logger.error("nonce save failed: %s", e)
            self._last_nonce = new_nonce
            return new_nonce

    def reset(self) -> None:
        with self._mem_lock:
            self._last_nonce = 0
            try:
                if self._path.exists():
                    self._path.unlink()
                if self._lock_path.exists():
                    self._lock_path.unlink()
            except Exception:
                pass
