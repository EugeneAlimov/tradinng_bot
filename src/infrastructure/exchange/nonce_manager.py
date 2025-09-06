# src/infrastructure/exchange/nonce_manager.py
from __future__ import annotations
import threading
import time
from pathlib import Path


class ThreadSafeNonceManager:
    """
    Строго монотонный числовой nonce для конкурентного доступа.
    Использует атомарный счетчик для гарантии монотонности.
    """

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()  # Обычный Lock, не RLock
        self._counter = 0  # Простой счетчик

        # Инициализация из файла или времени
        initial_value = int(time.time() * 1000)  # Миллисекунды

        if self.path and self.path.exists():
            try:
                content = self.path.read_text().strip()
                file_value = int(content) if content else 0
                initial_value = max(initial_value, file_value)
            except (ValueError, OSError):
                pass  # Используем время

        self._counter = initial_value

    def reset(self, value: int = 0) -> None:
        """Сброс nonce на указанное значение"""
        with self._lock:
            reset_value = max(int(value), int(time.time() * 1000))
            self._counter = reset_value
            self._save_to_file()

    def _save_to_file(self) -> None:
        """Сохранение в файл (вызывается под блокировкой)"""
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(str(self._counter))
            except OSError:
                pass  # Игнорируем ошибки записи

    def next(self) -> int:
        """Основной метод получения следующего nonce - строго атомарный"""
        with self._lock:
            self._counter += 1
            self._save_to_file()
            return self._counter

    def get_next_nonce(self) -> int:
        """Алиас для совместимости с другими частями кода"""
        return self.next()

    def current(self) -> int:
        """Получить текущее значение nonce без увеличения"""
        with self._lock:
            return self._counter