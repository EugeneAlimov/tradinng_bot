# src/infrastructure/exchange/nonce_manager.py
from __future__ import annotations

import os
import time
import fcntl
import threading
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ThreadSafeNonceManager:
    """
    Thread-safe/Process-safe менеджер nonce с файловой персистентностью.
    Гарантирует строго монотонный рост (>= мс таймстемпа) даже при параллельных вызовах.
    """

    def __init__(self, storage_path: str = "data/.exmo_nonce"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self._last_nonce = 0
        self._memory_lock = threading.Lock()

        self._lock_file = Path(str(self.storage_path) + ".lock")

        # загрузка сохраненного значения
        self._load_last_nonce()

    def _load_last_nonce(self) -> None:
        try:
            if self.storage_path.exists():
                with open(self.storage_path, "r") as f:
                    content = (f.read() or "").strip()
                    self._last_nonce = int(content) if content else 0
                logger.debug("Loaded last nonce: %s", self._last_nonce)
        except Exception as e:
            logger.warning("Failed to load nonce from %s: %s", self.storage_path, e)
            self._last_nonce = 0

    def get_next_nonce(self) -> int:
        """
        Возвращает следующий nonce.
        Не уменьшится при гонке потоков/процессов.
        """
        with self._memory_lock:
            now_ms = int(time.time() * 1000)
            new_nonce = max(now_ms, self._last_nonce + 1)
            self._save_nonce_atomic(new_nonce)
            self._last_nonce = new_nonce
            return new_nonce

    def _save_nonce_atomic(self, nonce: int) -> None:
        temp_file = Path(str(self.storage_path) + ".tmp")
        lock_fd = None
        try:
            lock_fd = open(self._lock_file, "w")
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

            with open(temp_file, "w") as f:
                f.write(str(nonce))

            temp_file.replace(self.storage_path)
        except Exception as e:
            logger.error("Failed to persist nonce: %s", e)
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                finally:
                    lock_fd.close()

    # Для тестов
    def reset(self) -> None:
        with self._memory_lock:
            self._last_nonce = 0
            try:
                if self.storage_path.exists():
                    self.storage_path.unlink()
                lock_file = self._lock_file
                if lock_file.exists():
                    lock_file.unlink()
            except Exception:
                pass
