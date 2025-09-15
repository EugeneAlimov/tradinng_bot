from __future__ import annotations
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

_TG_API = "https://api.telegram.org"


def _mask_token(tok: Optional[str]) -> str:
    if not tok:
        return "<empty>"
    t = tok
    if len(t) <= 8:
        return t[:1] + "*" * max(0, len(t) - 2) + t[-1:]
    return t[:4] + "*" * (len(t) - 8) + t[-4:]


def _sanitize_token(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    t = str(token).strip().strip('"').strip("'")
    if t.lower().startswith("bot"):
        t = t[3:]
    t = re.sub(r"\s+", "", t)
    return t or None


@dataclass
class TelegramNotifier:
    token: str
    chat_id: Optional[str] = None
    timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
        chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_TO")
        token = _sanitize_token(token or "")
        if not token:
            raise RuntimeError("[telegram] TELEGRAM_TOKEN/TELEGRAM_BOT_TOKEN is not set")
        return cls(token=token, chat_id=chat_id)

    @property
    def base_url(self) -> str:
        return f"{_TG_API}/bot{self.token}"

    def _req(self, method: str, params: Dict[str, Any], files: Optional[Tuple[str, bytes]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{method}"
        data = None
        headers: Dict[str, str] = {}

        if files:
            field_name, content = files
            boundary = f"----tgform{int(time.time() * 1000)}"
            parts = []
            for k, v in params.items():
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{field_name}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n"
            )
            body = "".join(parts).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
            data = body
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        else:
            data = urllib.parse.urlencode(params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    return {"ok": False, "http": resp.status, "error": text}
                obj.setdefault("http", resp.status)
                return obj
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"ok": False, "http": e.code, "error": body}
        except Exception as e:
            return {"ok": False, "http": 0, "error": str(e)}

    def get_me(self) -> Dict[str, Any]:
        return self._req("getMe", {})

    def send_text(self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None) -> Dict[str, Any]:
        chat = chat_id or self.chat_id
        if not chat:
            return {"ok": False, "http": 0, "error": "chat_id is not set"}
        params: Dict[str, Any] = {"chat_id": chat, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        return self._req("sendMessage", params)

    def send_photo(self, photo_bytes: bytes, caption: str = "", chat_id: Optional[str] = None) -> Dict[str, Any]:
        chat = chat_id or self.chat_id
        if not chat:
            return {"ok": False, "http": 0, "error": "chat_id is not set"}
        params: Dict[str, Any] = {"chat_id": chat, "caption": caption}
        return self._req("sendPhoto", params, files=("report.png", photo_bytes))
