# tests/test_order_id_generator.py
from src.infrastructure.exchange.order_manager import OrderIDGenerator


def test_client_id_uniqueness():
    gen = OrderIDGenerator()
    ids = [gen.generate() for _ in range(50000)]
    assert len(ids) == len(set(ids)), "client_id collision detected"
    assert all(0 <= x < 2_147_483_647 for x in ids)
