# src/presentation/cli/tg_test_cli.py
from __future__ import annotations

import argparse
import os
import sys

from src.presentation.utils.telegram_notify import tg_get_me, tg_send_message
from ._dotenv import maybe_load_dotenv


def _mask_token(t: str) -> str:
    # 123456789:AbCdEfGh -> *****:Ab...
    t = t or ""
    if ":" in t:
        left, right = t.split(":", 1)
        return "*****:" + (right[:2] + ("..." if len(right) > 2 else ""))
    return "*****"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("tg-test")
    p.add_argument("--tg-token", default=None, help="explicit token (else TELEGRAM_TOKEN/TELEGRAM_BOT_TOKEN)")
    p.add_argument("--tg-chat", default=None, help="chat id")
    p.add_argument("--text", default="hello from tg_test_cli")
    return p


def main(argv: list[str] | None = None) -> int:
    maybe_load_dotenv()
    args = build_parser().parse_args(argv)

    token = args.tg_token or os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat = args.tg_chat or os.getenv("TELEGRAM_CHAT_ID") or ""

    print(f"[telegram] token: {_mask_token(token)}")
    print(f"[telegram] chat:  {chat or '(empty)'}")

    me = tg_get_me(token=token)
    print("getMe:", {"ok": me.ok, "http": me.http, "payload": me.payload, "error": me.error})

    if chat:
        msg = tg_send_message(chat, args.text, token=token)
        print("sendMessage:", {"ok": msg.ok, "http": msg.http, "payload": msg.payload, "error": msg.error})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
