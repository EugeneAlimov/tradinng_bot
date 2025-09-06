from __future__ import annotations
import threading
from pathlib import Path


class ThreadSafeNonceManager:
    """
    Строго монотонный числовой nonce для конкурентного доступа.
    Реализация — просто атомарный счётчик под мьютексом.
    Это устойчивее под тест «монотонен в рамках прогона», чем time.monotonic_ns().
    """

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._last = 0
        if self.path and self.path.exists():
            try:
                self._last = int(self.path.read_text().strip())
            except Exception:
                self._last = 0

    def reset(self, value: int = 0) -> None:
        with self._lock:
            self._last = int(value)
            if self.path:
                self.path.write_text(str(self._last))

    def _bump_locked(self) -> int:
        self._last += 1
        if self.path:
            self.path.write_text(str(self._last))
        return self._last

    # контракт из тестов: nm.next()
    def next(self) -> int:
        with self._lock:
            return self._bump_locked()

    # контракт из resilience-теста
    def get_next_nonce(self) -> int:
        return self.next()
