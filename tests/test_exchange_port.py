from decimal import Decimal
from src.infrastructure.market.paper_feed import PaperFeed
from src.infrastructure.exchange.exmo_stub import ExmoStubExchange
from src.core.domain.models import TradingPair, OrderRequest, Side


def test_exchange_contract():
    market = PaperFeed(start_price=Decimal("0.1"))
    ex = ExmoStubExchange(market)
    pair = TradingPair("DOGE", "EUR")
    assert ex.get_price(pair) == Decimal("0.1")
    oid = ex.place_order(OrderRequest(pair=pair, side=Side.BUY, qty=Decimal("1")))
    assert isinstance(oid, str)
