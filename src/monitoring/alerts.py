# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import requests
from typing import Optional


class Alerter:
    """
    Простой алертинг в Telegram через Bot API.
    Настройка через ENV:
      TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    """

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None, timeout: float = 5.0):
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.timeout = float(timeout)
        self._base = f"https://api.telegram.org/bot{self.token}" if self.token else None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id and self._base)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            url = f"{self._base}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            requests.post(url, json=payload, timeout=self.timeout)
        except Exception:
            # не роняем торговлю из-за телеги
            pass


# Удобная фабрика
def make_alerter() -> Alerter:
    return Alerter()
