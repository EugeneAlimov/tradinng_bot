# src/core/engine.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bar:
    """
    Локальная минимальная модель бара, чтобы не тянуть несуществующие импорты.
    Этого достаточно для типизации базового движка.
    """
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class EngineConfig:
    name: str = "default-engine"
    dry_run: bool = True


class Engine:
    """Простая обёртка-движок, чтобы не ломались импорты и базовые сценарии."""

    def __init__(self, cfg: Optional[EngineConfig] = None) -> None:
        self.cfg = cfg or EngineConfig()
        logger.debug("Engine(%s) init, dry_run=%s", self.cfg.name, self.cfg.dry_run)

    def on_bar(self, bar: Bar) -> None:
        # У большинства логгеров нет .trace — страхуемся
        (getattr(logger, "trace", logger.debug))("on_bar: %s", bar)

    def start(self) -> None:
        logger.info("Engine '%s' started (dry_run=%s)", self.cfg.name, self.cfg.dry_run)

    def stop(self) -> None:
        logger.info("Engine '%s' stopped", self.cfg.name)
