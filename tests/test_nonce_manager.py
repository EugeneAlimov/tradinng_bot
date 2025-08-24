# tests/test_nonce_manager.py
from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager

def test_nonce_monotonic_increment(tmp_path):
    nm = ThreadSafeNonceManager(str(tmp_path / ".nonce"))
    a = nm.get_next_nonce()
    b = nm.get_next_nonce()
    assert b > a
