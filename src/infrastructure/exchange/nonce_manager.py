# src/infrastructure/exchange/nonce_manager.py
from __future__ import annotations

import os
import time
import threading
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# На Linux используем fcntl для межпроцессной блокировки.
try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None


class ThreadSafeNonceManager:
    """
    Потокобезопасный и (по возможности) межпроцессный менеджер nonce.
    Обеспечивает монотонный рост и уникальность в рамках процесса/хоста.
    Тесты ожидают методы: get_next_nonce() и next().
    """

    def __init__(self, storage_path: str = "data/.exmo_nonce"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._mem_lock = threading.Lock()
        self._last = 0
        self._load_last()

    # --- публичное API, ожидаемое тестами ---

    def get_next_nonce(self) -> int:
        with self._mem_lock:
            now = int(time.time() * 1000)
            new = max(now, self._last + 1)
            self._persist(new)
            self._last = new
            return new

    def next(self) -> int:
        """Синоним для тестов совместимости."""
        return self.get_next_nonce()

    def reset(self) -> None:
        with self._mem_lock:
            self._last = 0
            try:
                if self.storage_path.exists():
                    self.storage_path.unlink()
            except Exception as e:
                logger.warning("Nonce reset failed: %s", e)

    # --- внутреннее ---

    def _load_last(self) -> None:
        try:
            if self.storage_path.exists():
                txt = self.storage_path.read_text().strip()
                self._last = int(txt) if txt else 0
        except Exception as e:
            logger.warning("Failed to load nonce: %s", e)
            self._last = 0

    def _persist(self, value: int) -> None:
        # атомарная запись с опциональной файловой блокировкой
        tmp = self.storage_path.with_suffix(".tmp")
        try:
            if fcntl is not None:
                with open(self.storage_path.with_suffix(".lock"), "w") as lockf:
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
                    tmp.write_text(str(value))
                    tmp.replace(self.storage_path)
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
            else:
                tmp.write_text(str(value))
                tmp.replace(self.storage_path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
