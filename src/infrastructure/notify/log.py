from __future__ import annotations
import logging
from src.core.ports.notify import NotifierPort


class LogNotifier(NotifierPort):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        self._log = logging.getLogger("bot")

    def info(self, msg: str) -> None:
        self._log.info(msg)

    def warn(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)
