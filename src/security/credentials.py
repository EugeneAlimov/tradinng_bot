"""
Безопасная загрузка/хранение API-ключей EXMO с graceful fallback.
- Если установлен пакет `cryptography` — используем симметричное шифрование (Fernet).
- Если нет — аккуратно падаем в режим ENV/FIFO-хранения без шифрования (с явным WARNING).
- Не печатаем ключи в логах (даже хвосты).
"""

from __future__ import annotations

import os
import json
import base64
import getpass
from pathlib import Path
from typing import Tuple, Optional
from datetime import datetime
import hashlib
import logging

logger = logging.getLogger(__name__)

# --- Опциональная крипта: ---
_CRYPTO_OK = True
try:
    from cryptography.fernet import Fernet  # type: ignore
    from cryptography.hazmat.primitives import hashes  # type: ignore
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # type: ignore
except Exception:
    _CRYPTO_OK = False
    Fernet = None  # type: ignore
    PBKDF2HMAC = None  # type: ignore
    hashes = None  # type: ignore


class SecureCredentialsManager:
    """
    Хранит и загружает API-ключи. Если есть `cryptography` — шифруем Fernet.
    Файлы:
      ~/.crypto_bot/credentials/.key         — мастер-ключ (base64)
      ~/.crypto_bot/credentials/credentials.enc — зашифрованные креды
    """

    def __init__(self, storage_path: str = "~/.crypto_bot/credentials"):
        self.storage_path = Path(storage_path).expanduser()
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.key_file = self.storage_path / ".key"
        self.creds_file = self.storage_path / "credentials.enc"
        self._cipher: Optional[Fernet] = None

        if not _CRYPTO_OK:
            logger.warning(
                "[security] cryptography is not installed. Falling back to env/plain mode. "
                "Install `cryptography` to enable encrypted storage."
            )

    # ---------- Вспомогательное: ключ и шифратор ----------

    def _get_or_create_master_key(self) -> bytes:
        """
        Получить/создать мастер-ключ.
        ВНИМАНИЕ: при отсутствии `cryptography` возвращаем пустой ключ — чтобы не ломать интерфейс.
        """
        if not _CRYPTO_OK:
            # Режим без шифрования — возвращаем фиктивный ключ (не используется)
            return b""

        if self.key_file.exists():
            with open(self.key_file, "rb") as f:
                return f.read()

        # Создаем мастер-ключ из пароля пользователя
        print("No master key found for encrypted credentials.")
        pwd1 = getpass.getpass("Create master password: ").encode("utf-8")
        pwd2 = getpass.getpass("Confirm master password: ").encode("utf-8")
        if pwd1 != pwd2:
            raise ValueError("Passwords don't match")

        # В реальном проде соль должна быть случайной и храниться отдельно
        salt = b"stable_salt_for_bot_v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(pwd1))

        with open(self.key_file, "wb") as f:
            f.write(key)
        try:
            os.chmod(self.key_file, 0o600)
        except Exception:
            pass

        return key

    def _get_cipher(self) -> Optional[Fernet]:
        if not _CRYPTO_OK:
            return None
        if self._cipher is None:
            key = self._get_or_create_master_key()
            self._cipher = Fernet(key)
        return self._cipher

    # ---------- Публичные методы ----------

    def store_credentials(self, api_key: str, api_secret: str, exchange: str = "exmo") -> None:
        """
        Сохранить креды. Если криптографии нет — сохраняем «как есть» (JSON) с правами 600.
        """
        payload = {
            "exchange": exchange,
            "api_key": api_key,
            "api_secret": api_secret,
            "timestamp": datetime.now().isoformat(),
            "checksum": hashlib.sha256(f"{api_key}{api_secret}".encode("utf-8")).hexdigest(),
        }

        data: bytes
        if _CRYPTO_OK:
            cipher = self._get_cipher()
            assert cipher is not None
            data = cipher.encrypt(json.dumps(payload).encode("utf-8"))
        else:
            logger.warning("[security] Storing credentials in plaintext (no cryptography).")
            data = json.dumps(payload).encode("utf-8")

        with open(self.creds_file, "wb") as f:
            f.write(data)
        try:
            os.chmod(self.creds_file, 0o600)
        except Exception:
            pass

        logger.info("[security] Credentials stored securely for %s", exchange)

    def get_credentials(self, exchange: str = "exmo") -> Tuple[str, str]:
        """
        Прочитать креды из зашифрованного/плейн файла.
        Если файла нет — FileNotFoundError (пусть вызывающий решает, откуда брать).
        """
        if not self.creds_file.exists():
            raise FileNotFoundError("No stored credentials found")

        with open(self.creds_file, "rb") as f:
            raw = f.read()

        if _CRYPTO_OK:
            cipher = self._get_cipher()
            assert cipher is not None
            decoded = cipher.decrypt(raw).decode("utf-8")
        else:
            decoded = raw.decode("utf-8")

        creds = json.loads(decoded)
        # простая проверка целостности
        expect = hashlib.sha256(f"{creds['api_key']}{creds['api_secret']}".encode("utf-8")).hexdigest()
        if creds.get("checksum") != expect:
            raise ValueError("Credentials integrity check failed")

        return str(creds["api_key"]), str(creds["api_secret"])

    def rotate_credentials(self) -> None:
        """
        Ротация мастер-ключа (только если есть cryptography).
        В режиме plaintext просто переписываем файл.
        """
        key, sec = self.get_credentials()
        if _CRYPTO_OK and self.key_file.exists():
            try:
                self.key_file.unlink()
            except Exception:
                pass
        self._cipher = None
        self.store_credentials(key, sec)


def load_secure_credentials() -> Tuple[str, str]:
    """
    Унифицированная точка входа:
      1) пробуем зашифрованное хранилище
      2) если нет — берём из ENV (EXMO_KEY/EXMO_SECRET или EXMO_API_KEY/EXMO_API_SECRET), сразу сохраняем
      3) иначе — интерактивно запрашиваем у пользователя и сохраняем
    """
    mgr = SecureCredentialsManager()

    # 1) Encrypted/plain storage
    try:
        return mgr.get_credentials()
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[security] Stored credentials exist but failed to load: %s", e)

    # 2) ENV
    env_key = os.environ.get("EXMO_KEY") or os.environ.get("EXMO_API_KEY") or ""
    env_sec = os.environ.get("EXMO_SECRET") or os.environ.get("EXMO_API_SECRET") or ""
    if env_key and env_sec:
        # Сохраняем и очищаем окружение, чтобы не утекало
        mgr.store_credentials(env_key, env_sec)
        for k in ("EXMO_KEY", "EXMO_SECRET", "EXMO_API_KEY", "EXMO_API_SECRET"):
            if k in os.environ:
                try:
                    del os.environ[k]
                except Exception:
                    pass
        return env_key, env_sec

    # 3) Interactive (последний шанс)
    print("No EXMO credentials found. Please enter them (they will be stored securely).")
    in_key = getpass.getpass("EXMO API Key: ")
    in_sec = getpass.getpass("EXMO API Secret: ")
    mgr.store_credentials(in_key, in_sec)
    return in_key, in_sec
