# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Tuple, Optional
import os

try:
    import keyring  # системное безопасное хранилище
except Exception:  # если keyring не установлен/не работает
    keyring = None  # type: ignore[assignment]

_SERVICE = "exmo_bot"


def save_api_credentials(key: str, secret: str) -> None:
    """
    Сохранить ключи в системный keyring.
    Если keyring недоступен, бросит исключение.
    """
    if keyring is None:
        raise RuntimeError("keyring is not available. Install 'keyring' package or enable system keyring.")
    keyring.set_password(_SERVICE, "api_key", key)
    keyring.set_password(_SERVICE, "api_secret", secret)


def get_api_credentials() -> Tuple[Optional[str], Optional[str]]:
    """
    Достаём ключи: сначала из keyring, затем из окружения (.env уже мог быть загружен).
    Возвращаем (key, secret) или (None, None), если нет.
    """
    # 1) keyring
    if keyring is not None:
        try:
            kr_key = keyring.get_password(_SERVICE, "api_key")
            kr_secret = keyring.get_password(_SERVICE, "api_secret")
            if kr_key and kr_secret:
                return kr_key, kr_secret
        except Exception:
            pass

    # 2) окружение
    ek = os.getenv("EXMO_KEY") or os.getenv("EXMO_API_KEY")
    es = os.getenv("EXMO_SECRET") or os.getenv("EXMO_API_SECRET")
    return ek, es
