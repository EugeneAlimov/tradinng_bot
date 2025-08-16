from decimal import Decimal
from src.domain.portfolio.position_service import PositionService
from src.infrastructure.storage.files import FileStorage
from src.core.domain.models import TradingPair, TradeFill
import tempfile


def test_position_avg_price():
    with tempfile.TemporaryDirectory() as d:
        storage = FileStorage(path=d)
        svc = PositionService(storage)
        pair = TradingPair("DOGE", "EUR")
        fill1 = TradeFill(order_id="1", pair=pair, qty=Decimal("100"), price=Decimal("0.1"), ts_ms=0)
        fill2 = TradeFill(order_id="2", pair=pair, qty=Decimal("100"), price=Decimal("0.2"), ts_ms=0)
        p = svc.apply(pair, fill1)
        p = svc.apply(pair, fill2)
        assert p.qty == Decimal("200")
        assert p.avg_price == Decimal("0.15")
