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
            self._failures_in_window = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_in_half_open = 0
        elif new_state == CircuitState.OPEN:
            self._last_failure_at = datetime.now()

    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Основной метод circuit breaker"""
        with self._lock:
            self._prune_window()
            
            if self.state == CircuitState.OPEN:
                # Проверяем, можно ли перейти в HALF_OPEN
                time_since_failure = datetime.now() - self._state_changed_at
                if time_since_failure.total_seconds() >= self.config.recovery_timeout:
                    self._transition(CircuitState.HALF_OPEN)
                else:
                    raise CircuitOpenError(f"Circuit {self.name} is OPEN")
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except Exception as e:
                self._on_failure()
                raise e

    def _on_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self._success_in_half_open += 1
            if self._success_in_half_open >= self.config.success_threshold:
                self._transition(CircuitState.CLOSED)

    def _on_failure(self) -> None:
        self._errors.append(datetime.now())
        self._failures_in_window += 1
        
        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED:
            if self._failures_in_window >= self.config.failure_threshold:
                self._transition(CircuitState.OPEN)

    def get_state(self) -> Dict[str, Any]:
        """Получить текущее состояние circuit breaker"""
        return {
            "state": self.state.value,
            "failures_in_window": self._failures_in_window,
            "success_in_half_open": self._success_in_half_open,
            "last_failure": self._last_failure_at.isoformat() if self._last_failure_at else None,
            "state_changed_at": self._state_changed_at.isoformat(),
        }


class RetryWithBackoff:
    """Retry with exponential backoff"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def execute(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    # Add jitter
                    delay += random.uniform(0, delay * 0.1)
                    time.sleep(delay)
                else:
                    break
        
        raise last_exception or RuntimeError("Max retries exceeded")


class ErrorRecoverySystem:
    """System for managing multiple circuit breakers"""
    
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.retry_handler = RetryWithBackoff()
    
    def protected_call(self, service_name: str, func: Callable[..., Any], *args, **kwargs) -> Any:
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker(service_name)
        
        cb = self.circuit_breakers[service_name]
        return cb.call(func, *args, **kwargs)
    
    def get_status(self) -> Dict[str, Any]:
        return {
            name: cb.get_state() 
            for name, cb in self.circuit_breakers.items()
        }
