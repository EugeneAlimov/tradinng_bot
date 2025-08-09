
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any
from src.core.domain.models import TradingPair, OrderRequest, Side, TradeFill
from src.core.ports.market_data import MarketDataPort
from src.core.ports.exchange import ExchangePort
from src.core.ports.storage import StoragePort
from src.core.ports.notify import NotifierPort
from src.domain.strategy.mean_reversion import MeanReversion
from src.domain.risk.risk_service import RiskService
from src.domain.portfolio.position_service import PositionService

@dataclass
class TradeEngine:
    market: MarketDataPort
    exchange: ExchangePort
    storage: StoragePort
    notifier: NotifierPort
    strategy: MeanReversion
    risk: RiskService
    positions: PositionService

    def run_tick(self, pair: TradingPair) -> None:
        price = self.market.get_price(pair)
        ctx: Dict[str, Any] = {"last_price": price, "client_id": f"paper-{pair.symbol()}"}
        signal = self.strategy.decide(pair, ctx)
        if signal.get("action") == "HOLD":
            self.notifier.info(f"[HOLD] {pair.symbol()} @ {price}")
            return
        sized = self.risk.size(ctx)
        if not sized.get("allow"):
            self.notifier.warn("Risk blocked execution")
            return
        side = Side.BUY if signal.get("action") == "BUY" else Side.SELL
        req = OrderRequest(pair=pair, side=side, qty=sized["qty"], limit_price=sized["limit_price"], client_id=sized["client_id"])
        order_id = self.exchange.place_order(req)
        fill = TradeFill(order_id=order_id, pair=pair, qty=req.qty if side==Side.BUY else -req.qty, price=price, ts_ms=0)
        self.storage.append_trade({"order_id": order_id, "pair": pair.symbol(), "side": side.value, "qty": str(fill.qty), "price": str(price)})
        pos = self.positions.apply(pair, fill)
        self.notifier.info(f"[FILL] {pair.symbol()} {side.value} {fill.qty} @ {price}; pos_qty={pos.qty} avg={pos.avg_price}")
