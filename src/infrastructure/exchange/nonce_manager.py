# src/infrastructure/exchange/nonce_manager.py
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional, Union

Pathish = Union[str, os.PathLike[str]]

class ThreadSafeNonceManager:
    """
    Потокобезопасный nonce: каждый вызов next() -> строго +1.
    Персистентность через файл (опционально).

    Совместимость:
      __init__(path: Optional[pathlike] = None, *, start: Optional[int] = None)
      reset()                 -> перезагрузка: читаем из файла (если есть), иначе оставляем текущее
      reset(int_start)        -> выставить стартовое значение (файл обновим, если задан)
      reset(pathlike)         -> сменить файл: если файл есть — читаем, иначе записываем текущее
      reset(arg, *, path=..., start=...) — любые комбинации; явные ключи приоритетнее
    """

    def __init__(self, path: Optional[Pathish] = None, *, start: Optional[int] = None) -> None:
        self._lock = threading.Lock()
        self._path: Optional[Path] = Path(path) if path is not None else None
        self._nonce: int = 0

        # 1) если есть файл — пробуем читать
        loaded = False
        if self._path and self._path.exists():
            try:
                txt = self._path.read_text().strip()
                if txt:
                    self._nonce = int(txt)
                    loaded = True
            except Exception:
                loaded = False

        # 2) явный start перекрывает файл
        if isinstance(start, int):
            self._nonce = int(start)
            loaded = True

        # 3) если всё ещё 0 и ничего не грузили — просто стартуем с 0
        # (первый next() вернёт 1)
        if not loaded:
            self._nonce = 0

        self._persist()

    def _persist(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(str(self._nonce))

    def reset(
        self,
        arg: Optional[object] = None,
        *,
        path: Optional[Pathish] = None,
        start: Optional[int] = None,
    ) -> None:
        """
        См. докстринг класса для вариантов использования.
        """
        with self._lock:
            # Разбор позиционного аргумента (если есть)
            # - int -> трактуем как старт
            # - иное -> трактуем как путь
            if isinstance(arg, int):
                start = arg
            elif arg is not None and path is None:
                path = arg  # пусть Path(...) решит

            # Если передали путь — переключаем файл
            if path is not None:
                self._path = Path(path)

            if isinstance(start, int):
                # Явно задан старт — просто установим его
                self._nonce = int(start)
                self._persist()
                return

            # Иначе попытка перечитать из файла (если есть)
            if self._path and self._path.exists():
                try:
                    txt = self._path.read_text().strip()
                    self._nonce = int(txt) if txt else 0
                except Exception:
                    # если не получилось — оставим как есть
                    pass

            # Если файла нет — просто синхронизируем текущее значение в новый файл (если он появился)
            self._persist()

    def next(self) -> int:
        """
        Следующее значение: строго +1 к предыдущему.
        Гарантируется атомарность и отсутствие "дыр" (после сортировки результатов).
        """
        with self._lock:
            self._nonce += 1
            self._persist()
            return self._nonce

    # Backward compatibility
    def get_next_nonce(self) -> int:
        return self.next()
