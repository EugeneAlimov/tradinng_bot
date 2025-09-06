# src/monitoring/monitor.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

LOG = logging.getLogger(__name__)


@dataclass
class Monitor:
    name: str = "default"
    enabled: bool = True

    def start(self) -> None:
        LOG.debug("[monitor] start %s", self.name)

    def stop(self) -> None:
        LOG.debug("[monitor] stop %s", self.name)

    def event(self, title: str, text: Optional[str] = None) -> None:
        LOG.info("[monitor] %s: %s", title, text or "")
