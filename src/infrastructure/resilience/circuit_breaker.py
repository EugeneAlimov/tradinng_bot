# -*- coding: utf-8 -*-
"""
Circuit breaker + retry with backoff + simple error recovery registry.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    pass


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: int = 60  # seconds
    success_threshold: int = 3
    window_size: int = 60  # seconds


class CircuitBreaker:
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state_changed_at = datetime.now()
        self._lock = threading.Lock()
        self._errors: Deque[datetime] = deque()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        with self._lock:
            self._cleanup_window()
            if self.state == CircuitState.OPEN:
                if self._ready_for_half_open():
                    self._transition(CircuitState.HALF_OPEN)
                else:
                    raise CircuitOpenError(f"Circuit {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise

    # internals
    def _on_success(self) -> None:
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self._transition(CircuitState.CLOSED)
            if self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def _on_failure(self, err: Exception) -> None:
        with self._lock:
            now = datetime.now()
            self._errors.append(now)
            self.last_failure_time = now
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif self.state == CircuitState.CLOSED:
                self.failure_count = len(self._errors)
                if self.failure_count >= self.config.failure_threshold:
                    self._transition(CircuitState.OPEN)

    def _cleanup_window(self) -> None:
        cutoff = datetime.now() - timedelta(seconds=self.config.window_size)
        while self._errors and self._errors[0] < cutoff:
            self._errors.popleft()

    def _ready_for_half_open(self) -> bool:
        return (datetime.now() - self.state_changed_at).total_seconds() > self.config.recovery_timeout

    def _transition(self, new_state: CircuitState) -> None:
        logger.info("Circuit %s: %s -> %s", self.name, self.state.value, new_state.value)
        self.state = new_state
        self.state_changed_at = datetime.now()
        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
            self._errors.clear()
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
                "state_duration": (datetime.now() - self.state_changed_at).total_seconds(),
            }


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


class RetryWithBackoff:
    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()

    def _delay_for(self, attempt: int) -> float:
        delay = min(self.config.base_delay * (self.config.exponential_base ** attempt), self.config.max_delay)
        if self.config.jitter:
            import random
            delay *= (0.5 + random.random())
        return delay

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(self.config.max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt < self.config.max_attempts - 1:
                    delay = self._delay_for(attempt)
                    logger.warning("Attempt %s failed: %s. Retrying in %.2fs", attempt + 1, e, delay)
                    time.sleep(delay)
                else:
                    logger.error("All %s attempts failed", self.config.max_attempts)
        assert last_exc is not None
        raise last_exc


class ErrorRecoverySystem:
    def __init__(self):
        self.circuits: Dict[str, CircuitBreaker] = {}
        self.retry = RetryWithBackoff()
        self.error_stats: Dict[str, List[datetime]] = {}
        self.strategies: Dict[str, Callable[[Exception, Dict[str, Any]], Any]] = {}

    def circuit(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        if name not in self.circuits:
            self.circuits[name] = CircuitBreaker(name, config)
        return self.circuits[name]

    def register_strategy(self, error_type: str, strategy: Callable[[Exception, Dict[str, Any]], Any]) -> None:
        self.strategies[error_type] = strategy

    def handle(self, error: Exception, context: Dict[str, Any]) -> Optional[Any]:
        et = type(error).__name__
        self.error_stats.setdefault(et, []).append(datetime.now())
        if et in self.strategies:
            try:
                logger.info("Attempting recovery for %s", et)
                return self.strategies[et](error, context)
            except Exception as e:
                logger.error("Recovery strategy failed: %s", e)
        raise error

    def protected_call(self, func: Callable, circuit_name: str, retry: bool = True, *args, **kwargs) -> Any:
        c = self.circuit(circuit_name)
        def wrapped():
            return c.call(func, *args, **kwargs)
        return self.retry.execute(wrapped) if retry else wrapped()

    def health_report(self) -> Dict[str, Any]:
        one_hour_ago = datetime.now() - timedelta(hours=1)
        err_counts = {k: len([ts for ts in v if ts > one_hour_ago]) for k, v in self.error_stats.items()}
        return {
            "circuits": {n: c.get_state() for n, c in self.circuits.items()},
            "error_counts_1h": err_counts,
            "timestamp": datetime.now().isoformat(),
        }


# sample strategies
def network_error_recovery(error: Exception, context: Dict[str, Any]) -> Any:
    logger.info("network recovery: pause 5s")
    time.sleep(5)
    return None


def rate_limit_recovery(error: Exception, context: Dict[str, Any]) -> Any:
    logger.info("rate limit recovery: pause 60s")
    time.sleep(60)
    return None
