from __future__ import annotations
import argparse
import os
from pathlib import Path
from src.infrastructure.notify.telegram import TelegramNotifier, _sanitize_token, _mask_token


def _load_bytes(p: str) -> bytes:
    with open(p, "rb") as f:
        return f.read()


def main() -> int:
    ap = argparse.ArgumentParser(description="Telegram smoke test")
    ap.add_argument("--token", default=os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "",
                    help="bot token")
    ap.add_argument("--chat", default=os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_TO") or "", help="chat id")
    ap.add_argument("--text", default="smoke test from CLI")
    ap.add_argument("--photo", default=None, help="path to image to send")
    args = ap.parse_args()

    token = _sanitize_token(args.token)
    if not token:
        print("[telegram] ERROR: empty token (set TELEGRAM_TOKEN or use --token)")
        return 2
    chat = (args.chat or "").strip()
    if not chat:
        print("[telegram] ERROR: empty chat id (set TELEGRAM_CHAT_ID or use --chat)")
        return 2

    tg = TelegramNotifier(token=token, chat_id=chat)
    print(f"[telegram] using token: {_mask_token(token)}, chat: {chat}")
    r = tg.get_me()
    print("getMe:", r)
    r = tg.send_text(args.text)
    print("sendMessage:", r)
    if args.photo:
        b = _load_bytes(args.photo)
        r = tg.send_photo(b, caption="smoke image")
        print("sendPhoto:", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
