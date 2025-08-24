# tests/test_state_sync.py
from decimal import Decimal
from types import SimpleNamespace
from src.application.sync import StateSynchronizer

class DummyEx:
    def __init__(self):
        self._bal = {"DOGE": "2.0", "EUR": "100.0"}
        self._orders = {"DOGE_EUR": []}
    def user_info(self):
        return {"balances": self._bal}
    def user_open_orders(self, pair=None):
        return self._orders

def test_reconcile(tmp_path):
    ex = DummyEx()
    st_path = tmp_path / "state.json"
    ss = StateSynchronizer(ex, "DOGE_EUR", str(st_path))
    ss.local.pos_qty = Decimal("0")
    ss.sync(force=True)
    assert ss.local.pos_qty == Decimal("2.0")
