
from __future__ import annotations
import argparse
from decimal import Decimal
from src.config.settings import get_settings
from src.core.domain.models import TradingPair
from src.infrastructure.market.paper_feed import PaperFeed
from src.infrastructure.storage.files import FileStorage
from src.infrastructure.notify.log import LogNotifier
from src.infrastructure.exchange.exmo_stub import ExmoStubExchange
from src.domain.strategy.mean_reversion import MeanReversion
from src.domain.risk.risk_service import RiskService
from src.domain.portfolio.position_service import PositionService
from src.application.engine.trade_engine import TradeEngine

def run_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--symbol", default="DOGE_EUR")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    symbol = args.symbol or settings.default_pair
    base, quote = symbol.split("_")
    pair = TradingPair(base=base, quote=quote)

    notifier = LogNotifier()
    market = PaperFeed(start_price=Decimal("0.1"))
    storage = FileStorage(path=settings.storage_path)
    exchange = ExmoStubExchange(market=market)
    strategy = MeanReversion()
    risk = RiskService(settings.risk)
    positions = PositionService(storage=storage)

    if args.validate:
        notifier.info("Validation OK (paper-ready)")
        return

    engine = TradeEngine(market=market, exchange=exchange, storage=storage,
                         notifier=notifier, strategy=strategy, risk=risk, positions=positions)
    engine.run_tick(pair)
    notifier.info("Tick completed.")
