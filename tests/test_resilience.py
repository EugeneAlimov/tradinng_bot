# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time

from src.infrastructure.resilience.circuit_breaker import (
    CircuitBreaker, CircuitBreakerConfig, CircuitOpenError, RetryWithBackoff
)
from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager


def test_circuit_breaker_basic():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1, success_threshold=1))

    # function that fails twice, then succeeds
    calls = {"i": 0}

    def fn():
        calls["i"] += 1
        if calls["i"] <= 2:
            raise RuntimeError("boom")
        return 42

    # two failures -> OPEN
    for _ in range(2):
        try:
            cb.call(fn)
        except RuntimeError:
            pass
    assert cb.get_state()["state"] == "open"

    # before timeout -> still OPEN
    try:
        cb.call(lambda: 1)
    except CircuitOpenError:
        pass

    time.sleep(1.1)
    # HALF_OPEN then success -> CLOSED
    assert cb.call(fn) == 42
    assert cb.get_state()["state"] == "closed"


def test_retry_with_backoff():
    r = RetryWithBackoff()
    cnt = {"i": 0}

    def fn():
        cnt["i"] += 1
        if cnt["i"] < 3:
            raise ValueError("nope")
        return "ok"

    assert r.execute(fn) == "ok"


def test_nonce_manager_concurrent(tmp_path):
    nm = ThreadSafeNonceManager(str(tmp_path / ".nonce"))
    out = []

    def worker(k: int):
        for _ in range(200):
            out.append(nm.get_next_nonce())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(out) == 800
    assert len(out) == len(set(out))  # all unique
    assert out == sorted(out)  # monotonic (not strictly necessary, but expected)
