# src/security/credentials.py
from __future__ import annotations

import os
import json
import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

# Внешние зависимости — опциональны.
try:
    import keyring  # type: ignore
except Exception:
    keyring = None

try:
    from cryptography.fernet import Fernet  # type: ignore
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt  # type: ignore
    _CRYPTO_OK = True
except Exception:
    _CRYPTO_OK = False

logger = logging.getLogger(__name__)


@dataclass
class _StoredMeta:
    version: int = 1
    salt_b64: str = ""


class SecureCredentialsManager:
    """
    Безопасное хранение API-ключей.
    Приоритет:
      1) OS keyring (если доступен)
      2) шифрование (Fernet+scrypt) с passphrase из env CREDSTORE_PASSPHRASE
      3) Fallback: использование только env без хранения (безопасный режим по умолчанию)
    """
    def __init__(self, storage_dir: str = "~/.crypto_bot/credentials"):
        self.root = Path(storage_dir).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.root / "meta.json"
        self.creds_path = self.root / "credentials.enc"
        self.service = "tradinng_bot"
        self.account_key = "EXMO_API_KEY"
        self.account_secret = "EXMO_API_SECRET"

    # ---------- Keyring path ----------
    def _keyring_available(self) -> bool:
        return keyring is not None

    def store_keyring(self, api_key: str, api_secret: str, exchange: str = "exmo") -> None:
        if not self._keyring_available():
            raise RuntimeError("python-keyring not available")
        keyring.set_password(f"{self.service}:{exchange}", self.account_key, api_key)
        keyring.set_password(f"{self.service}:{exchange}", self.account_secret, api_secret)
        logger.info("[security] credentials stored in OS keyring")

    def load_keyring(self, exchange: str = "exmo") -> Optional[Tuple[str, str]]:
        if not self._keyring_available():
            return None
        try:
            key = keyring.get_password(f"{self.service}:{exchange}", self.account_key)
            sec = keyring.get_password(f"{self.service}:{exchange}", self.account_secret)
            if key and sec:
                return key, sec
        except Exception:
            return None
        return None

    # ---------- Fernet+scrypt path ----------
    def _ensure_meta(self) -> _StoredMeta:
        if self.meta_path.exists():
            data = json.loads(self.meta_path.read_text() or "{}")
            return _StoredMeta(**data)
        # создаём соль
        salt = os.urandom(16)
        meta = _StoredMeta(version=1, salt_b64=base64.urlsafe_b64encode(salt).decode())
        self.meta_path.write_text(json.dumps(meta.__dict__, indent=2))
        os.chmod(self.meta_path, 0o600)
        return meta

    def _derive_key(self, passphrase: str, salt: bytes) -> bytes:
        if not _CRYPTO_OK:
            raise RuntimeError("cryptography is not installed")
        kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
        key = kdf.derive(passphrase.encode("utf-8"))
        return base64.urlsafe_b64encode(key)

    def _get_cipher(self) -> Optional[Fernet]:
        if not _CRYPTO_OK:
            return None
        meta = self._ensure_meta()
        salt = base64.urlsafe_b64decode(meta.salt_b64.encode())
        passphrase = os.environ.get("CREDSTORE_PASSPHRASE", "")
        if not passphrase:
            # без пароля шифрование не включаем — безопаснее отказаться от хранения
            return None
        key = self._derive_key(passphrase, salt)
        return Fernet(key)

    def store_encrypted(self, api_key: str, api_secret: str, exchange: str = "exmo") -> None:
        cipher = self._get_cipher()
        if cipher is None:
            raise RuntimeError("cannot encrypt: missing cryptography or CREDSTORE_PASSPHRASE")
        payload = {
            "exchange": exchange,
            "api_key": api_key,
            "api_secret": api_secret,
            "timestamp": datetime.now().isoformat(),
        }
        enc = cipher.encrypt(json.dumps(payload).encode())
        self.creds_path.write_bytes(enc)
        os.chmod(self.creds_path, 0o600)
        logger.info("[security] credentials stored encrypted at %s", str(self.creds_path))

    def load_encrypted(self, exchange: str = "exmo") -> Optional[Tuple[str, str]]:
        if not self.creds_path.exists():
            return None
        cipher = self._get_cipher()
        if cipher is None:
            return None
        try:
            dec = cipher.decrypt(self.creds_path.read_bytes())
            data = json.loads(dec)
            if data.get("exchange") != exchange:
                return None
            return data["api_key"], data["api_secret"]
        except Exception:
            return None

    # ---------- Unified API ----------
    def store_credentials(self, api_key: str, api_secret: str, exchange: str = "exmo") -> None:
        # сначала пытаемся keyring
        if self._keyring_available():
            try:
                self.store_keyring(api_key, api_secret, exchange)
                return
            except Exception as e:
                logger.warning("keyring store failed: %s, fallback to file-encrypt", e)
        # потом шифрование
        try:
            self.store_encrypted(api_key, api_secret, exchange)
            return
        except Exception as e:
            logger.warning("encrypted store failed: %s; no persistent store will be used", e)
            # как fallback — ничего не сохраняем

    def get_credentials(self, exchange: str = "exmo") -> Tuple[str, str]:
        # 1) keyring
        kr = self.load_keyring(exchange)
        if kr:
            return kr
        # 2) encrypted file
        enc = self.load_encrypted(exchange)
        if enc:
            return enc
        # 3) env
        key = os.environ.get("EXMO_KEY") or os.environ.get("EXMO_API_KEY") or ""
        sec = os.environ.get("EXMO_SECRET") or os.environ.get("EXMO_API_SECRET") or ""
        if key and sec:
            # на будущее — сохраним (без печати каких-либо хвостов!)
            try:
                self.store_credentials(key, sec, exchange)
                # очищать env не будем принудительно — ответственность на пользователе окружения
            except Exception:
                pass
            return key, sec
        # 4) отсутствуют
        raise RuntimeError("EXMO credentials not found; set via keyring, encrypted store, or env")

    def rotate_credentials(self, exchange: str = "exmo") -> None:
        creds = self.get_credentials(exchange)
        # перегенерим соль и перезапишем
        if self.meta_path.exists():
            self.meta_path.unlink()
        if self.creds_path.exists():
            self.creds_path.unlink()
        self.store_credentials(*creds, exchange=exchange)
