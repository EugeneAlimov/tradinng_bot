# src/infrastructure/notify/telegram.py
from __future__ import annotations
import requests
from typing import Optional

class TelegramNotifier:
    def __init__(self, token: Optional[str], chat_id: Optional[str], timeout_sec: int = 5):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout_sec

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}, timeout=self.timeout)
        except Exception:
            # глушим, чтобы алерты не падали пайплайн
            pass
