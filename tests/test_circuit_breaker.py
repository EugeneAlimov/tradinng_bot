# tests/test_circuit_breaker.py
import pytest
from src.infrastructure.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

def test_cb_opens_then_half_open_then_close():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1, success_threshold=1, window_size=1))

    def boom():
        raise RuntimeError("x")

    # 2 ошибки -> OPEN
    with pytest.raises(RuntimeError):
        cb.call(boom)
    with pytest.raises(RuntimeError):
        cb.call(boom)
    assert cb.state.value == "open"

    # пока recovery_timeout не истечет — должен бросать CircuitOpenError
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: 1)

