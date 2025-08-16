from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any, Optional, Sequence, Tuple

from src.core.domain.models import TradingPair, OrderRequest, Side, TradeFill
from src.core.ports.market_data import MarketDataPort
from src.core.ports.exchange import ExchangePort
from src.core.ports.storage import StoragePort
from src.core.ports.notify import NotifierPort

# Стратегии
from src.domain.strategy.mean_reversion import MeanReversion

# Новая SMA-стратегия (если не используешь — импорт можно убрать)
try:
    from src.domain.strategy.sma_crossover import SmaCrossover, SmaCfg
except Exception:  # на случай, если файл ещё не добавлен
    SmaCrossover = None  # type: ignore


@dataclass
class TradeEngine:
    market: MarketDataPort
    exchange: ExchangePort
    storage: StoragePort
    notifier: NotifierPort
    strategy: Any  # MeanReversion | SmaCrossover | др., лишь бы .decide(pair, ctx) был
    positions: Any  # PositionService
    risk: Any  # RiskService

    # Новые параметры для свечей
    candles_timeframe: Optional[str] = "1m"
    candles_lookback: int = 60  # сколько свечей прокидывать в стратегию

    def run_tick(
            self,
            pair: TradingPair,
            *,
            extra_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Выполняет один «тик»:
          1) Берёт текущую цену
          2) (новое) Подмешивает свечи в ctx, если включено
          3) Запрашивает решение у стратегии
          4) Проверяет риск и исполняет через exchange
          5) Фиксирует fill и обновляет позицию
        """
        price = self.market.get_price(pair)
        ctx: Dict[str, Any] = {
            "last_price": price,
            "client_id": f"paper-{pair.symbol()}",
        }

        # Свечи для стратегий (например, SMA crossover)
        if self.candles_timeframe:
            try:
                candles: Sequence[Tuple[int, Decimal, Decimal, Decimal, Decimal]] = (
                    self.market.get_candles(pair, self.candles_timeframe, self.candles_lookback)
                )
                ctx["candles"] = candles
            except Exception as e:
                self.notifier.warn(f"[candles] fail: {e!r}")

        # Передадим любой внешний контекст (например, индикаторы/флаги)
        if extra_ctx:
            ctx.update(extra_ctx)

        # Решение стратегии
        try:
            signal = self.strategy.decide(pair, ctx)
        except Exception as e:
            self.notifier.error(f"[strategy] error: {e!r}")
            return

        action = (signal or {}).get("action", "HOLD")
        if action == "HOLD":
            self.notifier.info(f"[HOLD] {pair.symbol()} @ {price}")
            return

        # Сайзинг/риск
        sized = self.risk.size(ctx)
        if not sized.get("allow"):
            self.notifier.warn("Risk blocked execution")
            return

        side = Side.BUY if action == "BUY" else Side.SELL
        qty = sized["qty"]
        limit_price = sized.get("limit_price")
        client_id = sized.get("client_id")

        # Создаём запрос и исполняем
        req = OrderRequest(
            pair=pair,
            side=side,
            qty=qty,
            limit_price=limit_price,
            client_id=client_id,
        )
        try:
            order_id = self.exchange.place_order(req)
        except Exception as e:
            self.notifier.error(f"[exec] error: {e!r}")
            return

        # В paper-режиме исполняется мгновенно; создадим fill-представление
        fill = TradeFill(
            order_id=order_id,
            pair=pair,
            qty=qty if side == Side.BUY else -qty,
            price=price,  # фактическая цена может отличаться; для paper_exchange у fill есть своя цена
            ts_ms=0,
        )

        # Лог/хранилище
        try:
            self.storage.append_trade({
                "order_id": order_id,
                "pair": pair.symbol(),
                "side": side.value,
                "qty": str(fill.qty),
                "price": str(price),
                "signal": signal,
            })
        except Exception as e:
            self.notifier.warn(f"[store trade] fail: {e!r}")

        # Обновим позицию
        try:
            pos = self.positions.apply(pair, fill)
            self.notifier.info(
                f"[FILL] {pair.symbol()} {side.value} {fill.qty} @ {price}; "
                f"pos_qty={pos.qty} avg={pos.avg_price}"
            )
        except Exception as e:
            self.notifier.error(f"[position] error: {e!r}")
