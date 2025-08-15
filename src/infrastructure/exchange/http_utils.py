from __future__ import annotations

import os
import time
import traceback
from typing import Callable, Iterable, Optional, Type, Tuple


def _is_debug() -> bool:
    v = os.getenv("EXMO_DEBUG", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def with_retries(
    fn: Callable[[], any],
    *,
    attempts: int = 3,
    backoff_base: float = 0.5,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
):
    """
    Универсальный ретраер для HTTP-вызывалок.

    - attempts: сколько всего попыток (>=1)
    - backoff_base: базовая задержка, далее экспонента (base * 2**i)
    - retry_exceptions: какие исключения считаем ретраябельными
    - on_retry(i, err): колбэк перед сном перед (i+1)-й попыткой
    """
    if attempts < 1:
        attempts = 1

    last_err: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except retry_exceptions as e:
            last_err = e
            # последняя попытка — пробрасываем ошибку
            if i == attempts - 1:
                break
            if on_retry:
                try:
                    on_retry(i, e)
                except Exception:
                    # не роняем ретраер, даже если колбэк сломался
                    pass
            # экспоненциальный бэкофф
            delay = backoff_base * (2 ** i)
            if _is_debug():
                print(f"[retry] attempt {i+1}/{attempts} failed: {type(e).__name__}: {e}. sleep {delay:.3f}s")
                # короткий трейс в дебаге
                traceback.print_exc()
            time.sleep(delay)

    assert last_err is not None
    raise last_err
