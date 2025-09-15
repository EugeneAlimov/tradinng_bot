from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional
from src.infrastructure.notify.telegram import TelegramNotifier, _sanitize_token, _mask_token


def _read_env_token() -> Optional[str]:
    tok = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    return _sanitize_token(tok) if tok else None


@dataclass
class Alerter:
    tg: Optional[TelegramNotifier]

    @classmethod
    def from_env(cls) -> "Alerter":
        token = _read_env_token()
        chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_TO")
        if not token:
            print("[telegram] no TELEGRAM_TOKEN/TELEGRAM_BOT_TOKEN in env — notifications disabled")
            return cls(tg=None)
        tg = TelegramNotifier(token=token, chat_id=chat_id)
        r = tg.get_me()
        if not r.get("ok"):
            print(f"[telegram] getMe failed: HTTP {r.get('http')}: {r.get('error')}")
            if r.get("http") == 404:
                print("[telegram] hint: 404 обычно значит, что токен пустой в текущей сессии. "
                      "Убедись, что он export'нут:  export TELEGRAM_TOKEN=123:ABC")
            elif r.get("http") == 401:
                print("[telegram] hint: неверный токен. Формат должен быть '123456789:AA...'. "
                      "Не добавляй префикс 'bot'.")
        else:
            print(f"[telegram] ok, bot @{r['result']['username']} (token {_mask_token(token)})")
        return cls(tg=tg)

    def send_text(self, text: str) -> bool:
        if not self.tg:
            return False
        r = self.tg.send_text(text)
        if not r.get("ok"):
            print(f"[telegram] sendMessage failed: HTTP {r.get('http')}: {r.get('error')}")
            return False
        return True

    def send_photo(self, photo_bytes: bytes, caption: str = "") -> bool:
        if not self.tg:
            return False
        r = self.tg.send_photo(photo_bytes, caption=caption)
        if not r.get("ok"):
            print(f"[telegram] sendPhoto failed: HTTP {r.get('http')}: {r.get('error')}")
            return False
        return True
