# src/core/engine.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

# Раньше тут был невалидный импорт:
#   from src.strategies.sma import Bar   <-- его нет
# Берём доменную модель бара из доменного слоя:
from src.core.domain.models import Bar  # noqa: F401 (часто используется тип как аннотация)

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    name: str = "default-engine"
    dry_run: bool = True


class Engine:
    """Минимальный движок-обёртка, чтобы не ломались импорты в модулях."""

    def __init__(self, cfg: Optional[EngineConfig] = None) -> None:
        self.cfg = cfg or EngineConfig()
        logger.debug("Engine(%s) init, dry_run=%s", self.cfg.name, self.cfg.dry_run)

    def on_bar(self, bar: Bar) -> None:
        """Хэндлер нового бара. В базовой реализации ничего не делает."""
        logger.trace("on_bar: %s", bar) if hasattr(logger, "trace") else logger.debug("on_bar: %s", bar)

    def start(self) -> None:
        logger.info("Engine '%s' started (dry_run=%s)", self.cfg.name, self.cfg.dry_run)

    def stop(self) -> None:
        logger.info("Engine '%s' stopped", self.cfg.name)
