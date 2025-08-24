# src/infrastructure/resilience/circuit_breaker.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any, Optional, Dict, Deque
from datetime import datetime, timedelta
from enum import Enum
from collections import deque
import threading
import time
import logging
import random

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5  # сколько ошибок подряд, чтобы открыть
    recovery_timeout: int = 60  # сек до попытки half-open
    success_threshold: int = 3  # успешных вызовов, чтобы закрыть
    window_size: int = 60  # окно для подсчёта ошибок (сек)


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """
    Потокобезопасный circuit breaker с half-open и скользящим окном ошибок.
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self._lock = threading.Lock()
        self._errors: Deque[datetime] = deque()
        self._state_changed_at: datetime = datetime.now()
        self._last_failure_at: Optional[datetime] = None
        self._success_in_half_open: int = 0
        self._failures_in_window: int = 0

    def _prune_window(self) -> None:
        cutoff = datetime.now() - timedelta(seconds=self.config.window_size)
        while self._errors and self._errors[0] < cutoff:
            self._errors.popleft()
        self._failures_in_window = len(self._errors)

    def _transition(self, new_state: CircuitState) -> None:
        if self.state != new_state:
            logger.info("circuit %s: %s -> %s", self.name, self.state.value, new_state.value)
        self.state = new_state
        self._state_changed_at = datetime.now()
        if new_state == CircuitState.CLOSED:
            self._errors.clear()
            self._success_in_half_open = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_in_half_open = 0

    def _should_probe(self) -> bool:
        return (datetime.now() - self._state_changed_at).total_seconds() >= self.config.recovery_timeout

    def call(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        with self._lock:
            self._prune_window()
            if self.state == CircuitState.OPEN:
                if not self._should_probe():
                    raise CircuitOpenError(f"Circuit {self.name} is OPEN")
                self._transition(CircuitState.HALF_OPEN)

        try:
            res = fn(*args, **kwargs)
        except Exception:
            with self._lock:
                self._errors.append(datetime.now())
                self._prune_window()
                self._last_failure_at = datetime.now()
                if self.state == CircuitState.HALF_OPEN:
                    self._transition(CircuitState.OPEN)
                elif self.state == CircuitState.CLOSED and self._failures_in_window >= self.config.failure_threshold:
                    self._transition(CircuitState.OPEN)
            raise
        else:
            with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self._success_in_half_open += 1
                    if self._success_in_half_open >= self.config.success_threshold:
                        self._transition(CircuitState.CLOSED)
                elif self.state == CircuitState.CLOSED:
                    # успешный вызов в closed — просто «подсыхаем» окно ошибок
                    self._prune_window()
            return res

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            self._prune_window()
            return {
                "name": self.name,
                "state": self.state.value,
                "failures_window": self._failures_in_window,
                "last_failure_at": self._last_failure_at.isoformat() if self._last_failure_at else None,
                "state_age_sec": (datetime.now() - self._state_changed_at).total_seconds(),
            }


@dataclass
class RetryConfig:
    max_attempts: int = 4
    base_delay: float = 0.6
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


class RetryWithBackoff:
    def __init__(self, cfg: Optional[RetryConfig] = None):
        self.cfg = cfg or RetryConfig()

    def execute(self, func, *args, **kwargs):
        """
        Совместимость с тестами: синоним основного запуска с ретраями.
        """
        last_exception = None
        for attempt in range(self.config.max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.config.max_attempts - 1:
                    delay = self._calculate_delay(attempt)
                    logger.warning("Attempt %s failed: %s. Retrying in %.2fs", attempt + 1, e, delay)
                    time.sleep(delay)
        raise last_exception

    def _delay_for(self, attempt: int) -> float:
        delay = min(self.cfg.base_delay * (self.cfg.exponential_base ** attempt), self.cfg.max_delay)
        if self.cfg.jitter:
            delay *= 0.5 + random.random()
        return delay

    def run(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        last_exc: Optional[BaseException] = None
        for attempt in range(self.cfg.max_attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt == self.cfg.max_attempts - 1:
                    break
                sleep_s = self._delay_for(attempt)
                logger.warning("retry (%d/%d) after error: %s; sleep=%.2fs",
                               attempt + 1, self.cfg.max_attempts, exc, sleep_s)
                time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc


class ErrorRecoverySystem:
    """
    Унифицированный слой защиты: circuit breaker + retry.
    """

    def __init__(self):
        self._cb_map: Dict[str, CircuitBreaker] = {}
        self._retry = RetryWithBackoff()

    def breaker(self, name: str, cfg: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        if name not in self._cb_map:
            self._cb_map[name] = CircuitBreaker(name, cfg)
        return self._cb_map[name]

    def protected_call(self, name: str, fn: Callable[..., Any], *args, **kwargs) -> Any:
        cb = self.breaker(name)

        def _wrapped():
            return cb.call(fn, *args, **kwargs)

        return self._retry.run(_wrapped)

    def get_status(self) -> Dict[str, Any]:
        return {name: cb.get_state() for name, cb in self._cb_map.items()}
