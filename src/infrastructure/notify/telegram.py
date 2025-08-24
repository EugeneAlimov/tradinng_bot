# src/infrastructure/notify/telegram.py
from __future__ import annotations

from typing import Optional
import requests


class TelegramNotifier:
    """
    Лёгкий Telegram‑нотификатор без внешних SDK.
    Безопасно «молчит», если не задан токен/чат.
    """

    def __init__(self, token: Optional[str], chat_id: Optional[str], timeout_sec: int = 5):
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout = timeout_sec

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=self.timeout,
            )
        except Exception:
            # Не валим основной поток из-за сбоев алёртов
            pass
