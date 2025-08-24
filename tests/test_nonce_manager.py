# tests/test_nonce_manager.py
import concurrent.futures
from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager

def test_nonce_monotonic_and_unique(tmp_path):
    f = tmp_path / ".nonce"
    nm = ThreadSafeNonceManager(str(f))
    vals = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(nm.next) for _ in range(2000)]
        for fu in futs:
            vals.append(fu.result())
    assert len(vals) == len(set(vals)), "nonce must be unique"
    assert all(b > a for a, b in zip(vals, vals[1:])), "nonce must be monotonic within run"
