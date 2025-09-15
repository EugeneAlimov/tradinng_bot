from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import random
import string
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, Tuple

API_ROOT = "https://api.telegram.org"


# ============== low-level HTTP helpers ==============

def _http_get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        code = getattr(resp, "status", None)
    try:
        obj = json.loads(data.decode("utf-8"))
        if "http" not in obj:
            obj["http"] = code
        return obj
    except Exception:
        return {"ok": False, "http": code, "error": data.decode("utf-8", "replace")}


def _http_post_form(url: str, fields: Dict[str, str]) -> Dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        code = getattr(resp, "status", None)
    try:
        obj = json.loads(data.decode("utf-8"))
        if "http" not in obj:
            obj["http"] = code
        return obj
    except Exception:
        return {"ok": False, "http": code, "error": data.decode("utf-8", "replace")}


def _encode_multipart(fields: Dict[str, str],
                      files: Tuple[str, str, bytes]) -> Tuple[str, bytes]:
    """
    fields: обычные поля формы
    files:  кортеж (form_name, filename, content_bytes) — ровно один файл
    """
    boundary = "----tb{}".format("".join(random.choices(string.ascii_letters + string.digits, k=24)))
    crlf = "\r\n"

    parts: list[bytes] = []

    # text fields
    for k, v in fields.items():
        parts.append(f"--{boundary}{crlf}".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{k}"{crlf}{crlf}'.encode("utf-8"))
        parts.append(str(v).encode("utf-8"))
        parts.append(crlf.encode("utf-8"))

    # one file
    form_name, filename, content = files
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts.append(f"--{boundary}{crlf}".encode("utf-8"))
    parts.append(
        f'Content-Disposition: form-data; name="{form_name}"; filename="{filename}"{crlf}'.encode("utf-8")
    )
    parts.append(f"Content-Type: {mime}{crlf}{crlf}".encode("utf-8"))
    parts.append(content)
    parts.append(crlf.encode("utf-8"))

    parts.append(f"--{boundary}--{crlf}".encode("utf-8"))
    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return content_type, body


def _http_post_multipart(url: str, fields: Dict[str, str], file_tuple: Tuple[str, str, bytes]) -> Dict[str, Any]:
    content_type, body = _encode_multipart(fields, file_tuple)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        code = getattr(resp, "status", None)
    try:
        obj = json.loads(data.decode("utf-8"))
        if "http" not in obj:
            obj["http"] = code
        return obj
    except Exception:
        return {"ok": False, "http": code, "error": data.decode("utf-8", "replace")}


# ============== token / env helpers ==============

def _normalize_token(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    token = raw.strip().strip('"').strip("'")
    # некоторые пишут 'bot123:ABC…' — Telegram ждёт только '123:ABC…'
    if token.lower().startswith("bot"):
        token = token[3:]
    return token


def get_chat_id_from_env() -> Optional[str]:
    for key in ("TELEGRAM_CHAT_ID", "TB_TELEGRAM_CHAT_ID"):
        v = os.getenv(key)
        if v and v.strip():
            return v.strip()
    return None


def _token_from_env(explicit_token: Optional[str] = None) -> Optional[str]:
    if explicit_token and explicit_token.strip():
        return _normalize_token(explicit_token)
    for key in ("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", "TB_TELEGRAM_TOKEN"):
        v = os.getenv(key)
        if v and v.strip():
            return _normalize_token(v)
    return None


# ============== client ==============

class TelegramClient:
    def __init__(self, token: str):
        self.token = _normalize_token(token) or ""
        self.base = f"{API_ROOT}/bot{self.token}"

    # --- methods ---

    def get_me(self) -> Dict[str, Any]:
        url = f"{self.base}/getMe"
        return _http_get_json(url)

    def get_updates(self, offset: Optional[int] = None, timeout: int = 0) -> Dict[str, Any]:
        url = f"{self.base}/getUpdates"
        fields = {}
        if offset is not None:
            fields["offset"] = str(offset)
        if timeout:
            fields["timeout"] = str(timeout)
        return _http_post_form(url, fields)

    def send_message(self, chat_id: str, text: str, parse_mode: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base}/sendMessage"
        fields = {"chat_id": str(chat_id), "text": text}
        if parse_mode:
            fields["parse_mode"] = parse_mode
        return _http_post_form(url, fields)

    def send_photo(self, chat_id: str, path: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Загрузка файла через multipart (локальный путь)."""
        p = pathlib.Path(path)
        if not p.exists():
            return {"ok": False, "http": 0, "error": f"file not found: {path}"}
        content = p.read_bytes()
        url = f"{self.base}/sendPhoto"
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption
        file_tuple = ("photo", p.name, content)
        return _http_post_multipart(url, fields, file_tuple)

    def send_document(self, chat_id: str, path: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Отправка произвольного файла (CSV/HTML/ZIP и т.п.)."""
        p = pathlib.Path(path)
        if not p.exists():
            return {"ok": False, "http": 0, "error": f"file not found: {path}"}
        content = p.read_bytes()
        url = f"{self.base}/sendDocument"
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption
        file_tuple = ("document", p.name, content)
        return _http_post_multipart(url, fields, file_tuple)


# public helpers

def client_from_env(explicit_token: Optional[str] = None) -> Optional[TelegramClient]:
    token = _token_from_env(explicit_token)
    if not token:
        return None
    return TelegramClient(token)
