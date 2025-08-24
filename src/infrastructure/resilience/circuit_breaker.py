# src/infrastructure/resilience/circuit_breaker.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any, Optional, Dict, List
from datetime import datetime, timedelta
from enum import Enum
import threading
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Исключение при открытом circuit breaker."""
    pass


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: int = 60
    success_threshold: int = 3
    window_size: int = 60


class CircuitBreaker:
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state_changed_at = datetime.now()
        self.lock = threading.Lock()
        self.error_history: deque[datetime] = deque()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        with self.lock:
            self._clean_error_window()
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    raise CircuitOpenError(f"Circuit {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self) -> None:
        with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            if self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def _on_failure(self, error: Exception) -> None:
        with self.lock:
            self.last_failure_time = datetime.now()
            self.error_history.append(self.last_failure_time)
            if self.state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
            elif self.state == CircuitState.CLOSED:
                self.failure_count = len(self.error_history)
                if self.failure_count >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _should_attempt_reset(self) -> bool:
        return (datetime.now() - self.state_changed_at).total_seconds() > self.config.recovery_timeout

    def _transition_to(self, new_state: CircuitState) -> None:
        logger.info("Circuit %s: %s -> %s", self.name, self.state.value, new_state.value)
        self.state = new_state
        self.state_changed_at = datetime.now()
        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
            self.error_history.clear()
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0

    def _clean_error_window(self) -> None:
        cutoff = datetime.now() - timedelta(seconds=self.config.window_size)
        while self.error_history and self.error_history[0] < cutoff:
            self.error_history.popleft()

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
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

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(self.config.max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt < self.config.max_attempts - 1:
                    delay = self._calc_delay(attempt)
                    logger.warning("Attempt %s failed: %s. Retry in %.2fs", attempt + 1, e, delay)
                    time.sleep(delay)
                else:
                    logger.error("All %s attempts failed", self.config.max_attempts)
        assert last_exc is not None
        raise last_exc

    def _calc_delay(self, attempt: int) -> float:
        delay = min(self.config.base_delay * (self.config.exponential_base ** attempt), self.config.max_delay)
        if self.config.jitter:
            import random
            delay *= (0.5 + random.random())
        return delay


class ErrorRecoverySystem:
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.retry = RetryWithBackoff()
        self.error_stats: Dict[str, List[datetime]] = {}
        self.recovery_strategies: Dict[str, Callable[[Exception, Dict[str, Any]], Any]] = {}

    def get_circuit(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(name, config)
        return self.circuit_breakers[name]

    def register_recovery(self, error_type: str, strategy: Callable[[Exception, Dict[str, Any]], Any]) -> None:
        self.recovery_strategies[error_type] = strategy

    def protected_call(self, func: Callable, circuit_name: str, retry: bool = True, *args, **kwargs) -> Any:
        circuit = self.get_circuit(circuit_name)
        def wrapped():
            return circuit.call(func, *args, **kwargs)
        return self.retry.execute(wrapped) if retry else wrapped()

    def handle_error(self, error: Exception, context: Dict[str, Any]) -> Optional[Any]:
        et = type(error).__name__
        self.error_stats.setdefault(et, []).append(datetime.now())
        if et in self.recovery_strategies:
            try:
                return self.recovery_strategies[et](error, context)
            except Exception as ee:
                logger.error("Recovery strategy failed: %s", ee)
        raise error

    def health_report(self) -> Dict[str, Any]:
        one_hour_ago = datetime.now() - timedelta(hours=1)
        counts = {k: len([ts for ts in v if ts > one_hour_ago]) for k, v in self.error_stats.items()}
        return {
            "circuit_breakers": {n: cb.get_state() for n, cb in self.circuit_breakers.items()},
            "error_counts_1h": counts,
            "timestamp": datetime.now().isoformat(),
        }


# Optional sample strategies
def network_error_recovery(error: Exception, context: Dict[str, Any]) -> Any:
    logger.info("Network recovery: waiting 5s...")
    time.sleep(5)
    return None


def rate_limit_recovery(error: Exception, context: Dict[str, Any]) -> Any:
    logger.info("Rate limit: waiting 60s...")
    time.sleep(60)
    return None
