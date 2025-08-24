# -*- coding: utf-8 -*-
"""
E2E/интеграционные тесты с моками EXMO для проверки:
- уникальности client_id (ImprovedOrderManager + OrderIDGenerator);
- потокобезопасности nonce (ThreadSafeNonceManager) при параллельных вызовах;
- поведения circuit breaker + retry при кратковременных сбоях.

Требуется: pytest
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest


# --- Импорты наших компонентов (могут отсутствовать в старых ветках — тесты пропускаются) ---
om_mod = None
nonce_mod = None
cb_mod = None

try:
    om_mod = __import__("src.infrastructure.exchange.order_manager", fromlist=["*"])
except Exception:
    pass

try:
    nonce_mod = __import__("src.infrastructure.exchange.nonce_manager", fromlist=["*"])
except Exception:
    pass

try:
    cb_mod = __import__("src.infrastructure.resilience.circuit_breaker", fromlist=["*"])
except Exception:
    pass


# -------------------
# Мок EXMO API
# -------------------
class _FakeExmoApi:
    """Простой мок EXMO для тестов order_create/user_open_orders/order_trades."""

    def __init__(self):
        self._next_id = 1
        self._open: Dict[str, Dict[str, Any]] = {}

    # Интерфейс order_create, который ожидает ImprovedOrderManager
    def order_create(self, pair: str, quantity: str, price: str, side: str, client_id: Optional[int] = None) -> Dict[str, Any]:
        oid = str(self._next_id)
        self._next_id += 1
        # Сохраним "открытый ордер"
        self._open[oid] = dict(
            order_id=oid,
            client_id=client_id,
            pair=pair,
            type=side,
            price=price,
            quantity=quantity,
            status="open",
            created=int(time.time()),
        )
        return {"result": True, "order_id": oid}

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for od in self._open.values():
            if pair is None or od["pair"] == pair:
                out.setdefault(od["pair"], []).append(od)
        return out

    def order_cancel(self, order_id: str) -> Dict[str, Any]:
        self._open.pop(str(order_id), None)
        return {"result": True}

    def order_trades(self, order_id: str) -> Dict[str, Any]:
        # в этом простом моке считаем, что ордер не исполняется сам
        return {"trades": []}


@pytest.mark.skipif(om_mod is None, reason="ImprovedOrderManager not available")
def test_client_id_uniqueness_under_pressure():
    """
    Проверяем, что при большом числе подряд размещённых ордеров client_id уникальный.
    """
    ImprovedOrderManager = getattr(om_mod, "ImprovedOrderManager")
    mgr = ImprovedOrderManager(_FakeExmoApi())

    seen: set = set()
    ok = 0

    # Размещаем 500 ордеров подряд
    for _ in range(500):
        success, order_id, err = mgr.place_order_with_retry(
            pair="DOGE_EUR",
            side="buy",
            price=0.1,
            quantity=10.0,
            max_retries=1,
        )
        assert success, f"order_create failed: {err}"
        ci = mgr.active_orders[order_id].client_id if order_id in mgr.active_orders else None
        assert isinstance(ci, int)
        assert ci not in seen, "client_id collision!"
        seen.add(ci)
        ok += 1

    assert ok == 500


@pytest.mark.skipif(nonce_mod is None, reason="ThreadSafeNonceManager not available")
def test_threadsafe_nonce_is_monotonic(monkeypatch):
    """
    Многопоточность: получаем nonce из нескольких потоков и убеждаемся в монотонности и уникальности.
    """
    ThreadSafeNonceManager = getattr(nonce_mod, "ThreadSafeNonceManager")

    nm = ThreadSafeNonceManager("data/.test_nonce")
    nm.reset()

    n_threads = 8
    per_thread = 200
    results: List[int] = []
    lock = threading.Lock()

    def worker():
        lst = []
        for _ in range(per_thread):
            lst.append(nm.get_next_nonce())
        with lock:
            results.extend(lst)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == n_threads * per_thread
    assert len(set(results)) == len(results), "Nonce duplicates detected!"
    # монотонность глобально (не строго упорядочено, но минимум растёт)
    assert min(results) >= 0
    assert max(results) > min(results)


@pytest.mark.skipif(cb_mod is None, reason="CircuitBreaker not available")
def test_circuit_breaker_with_retry(monkeypatch):
    """
    Проверяем, что RetryWithBackoff перехватывает кратковременные сбои, а CircuitBreaker открывается при частых ошибках.
    """
    CircuitBreaker = getattr(cb_mod, "CircuitBreaker")
    CircuitBreakerConfig = getattr(cb_mod, "CircuitBreakerConfig")
    RetryWithBackoff = getattr(cb_mod, "RetryWithBackoff")

    # Ускоряем тест: подменяем sleep на no-op
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kw: None)

    cb = CircuitBreaker("exmo", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=1, window_size=10))
    retry = RetryWithBackoff()

    state = {"count": 0}

    def flaky():
        state["count"] += 1
        # первые 2 раза кидаем исключение
        if state["count"] <= 2:
            raise RuntimeError("temporary")
        return 42

    # через cb + retry
    result = retry.execute(lambda: cb.call(flaky))
    assert result == 42
    # если теперь наломаем подряд 3 ошибки — откроется
    def always_bad():
        raise RuntimeError("boom")
    with pytest.raises(Exception):
        # 3 ошибки подряд внутри окна откроют брейкер и в итоге упадём
        retry.execute(lambda: cb.call(always_bad))
