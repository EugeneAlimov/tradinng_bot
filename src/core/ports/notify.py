from __future__ import annotations
from typing import Protocol


class NotifierPort(Protocol):
    def info(self, msg: str) -> None: ...

    def warn(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...
