# src/presentation/api/notifier.py
import os
from typing import Optional

_TG_TOKEN = os.getenv("TG_BOT_TOKEN")

async def notify_safe(chat_id: Optional[int], text: str):
    """Тихо пробуем отправить сообщение в телеграм, если всё настроено."""
    if not chat_id or not _TG_TOKEN:
        return
    try:
        from aiogram import Bot
        bot = Bot(_TG_TOKEN)
        await bot.send_message(chat_id, text)
    except Exception:
        pass
