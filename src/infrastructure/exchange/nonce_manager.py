from __future__ import annotations

import os
import threading
from typing import Optional


class ThreadSafeNonceManager:
    """
    Монотонный и уникальный nonce. Возврат строго в порядке входа в next(),
    чтобы минимизировать инверсии при многопоточном получении результатов.
    """

    def __init__(self, state_path: Optional[str] = None):
        self._state_path = state_path
        self._cv = threading.Condition()
        self._last = 0  # последний выданный nonce (persisted)
        self._issued = 0  # выдано "билетов" на вход
        self._next_ticket_to_return = 1
        if state_path and os.path.exists(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                    if txt.isdigit():
                        self._last = int(txt)
            except Exception:
                pass

    def reset(self) -> None:
        with self._cv:
            self._last = 0
            self._issued = 0
            self._next_ticket_to_return = 1
            self._store_unlocked()

    def _store_unlocked(self) -> None:
        if not self._state_path:
            return
        tmp = self._state_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(str(self._last))
            os.replace(tmp, self._state_path)
        except Exception:
            pass

    def _next_common(self) -> int:
        with self._cv:
            # назначаем билет по порядку входа
            self._issued += 1
            my_ticket = self._issued
            # ждём своей очереди на возврат (FIFO по билету)
            while my_ticket != self._next_ticket_to_return:
                self._cv.wait()
            # возвращаем следующий nonce
            self._last += 1
            val = self._last
            self._store_unlocked()
            self._next_ticket_to_return += 1
            self._cv.notify_all()
            return val

    # совместимость
    def next(self) -> int:
        return self._next_common()

    def get_next_nonce(self) -> int:
        return self._next_common()
