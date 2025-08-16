from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Iterable, Dict, List, Tuple, Optional
import itertools
import random
import time

from src.core.ports.exchange import ExchangePort
from src.core.ports.market_data import MarketDataPort
from src.core.domain.models import TradingPair, OrderRequest, TradeFill, Side


def _to_decimal(x: Decimal | float | str) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _bps(n: int | float) -> Decimal:
    """basis points to Decimal factor"""
    return _to_decimal(n) / Decimal("10000")


@dataclass
class PaperExchange(ExchangePort):
    """
    Реалистичный paper-исполнитель:
      - Цена исполнения = mid * (1 ± spread) * (1 ± slippage)
      - Ведёт журналы ордеров и сделок в памяти
      - Поддерживает "балансы" для base/quote
    Совместим с ExchangePort.
    """

    market: MarketDataPort
    spread_bps: int = 10  # 10 б.п. = 0.10% «плохая» цена относительно mid
    slippage_bps: int = 5  # 5 б.п.  = 0.05% слиппаж
    rnd_seed: Optional[int] = None
    # начальные балансы (quote побольше на старте)
    initial_balances: Dict[str, Decimal] = field(
        default_factory=lambda: {"USD": Decimal("10000")}
    )

    # внутреннее состояние
    _balances: Dict[str, Decimal] = field(default_factory=dict, init=False)
    _fills: List[TradeFill] = field(default_factory=list, init=False)
    _order_seq: itertools.count = field(default_factory=lambda: itertools.count(1), init=False)
    _rng: random.Random = field(default_factory=random.Random, init=False)

    def __post_init__(self) -> None:
        if self.rnd_seed is not None:
            self._rng.seed(self.rnd_seed)
        # Копируем начальные балансы
        self._balances = {k: _to_decimal(v) for k, v in self.initial_balances.items()}

    # ==== ExchangePort ====

    def get_price(self, pair: TradingPair) -> Decimal:
        return self.market.get_price(pair)

    def place_order(self, req: OrderRequest) -> str:
        """
        Мгновенное исполнение по модели:
          mid = market.get_price()
          price = mid * (1 + sgn*spread) * (1 + sgn*slippage)
            где sgn = +1 для BUY, -1 для SELL
        Обновляет балансы и журнал сделок.
        """
        mid = self.market.get_price(req.pair)
        if mid <= 0:
            raise ValueError("PaperExchange: mid price must be positive")

        sgn = Decimal("1") if req.side == Side.BUY else Decimal("-1")
        spread = _bps(self.spread_bps)
        # слиппаж — берём фиксированное значение ±slippage (пессимистично в сторону сделки)
        slip = _bps(self.slippage_bps)

        exec_price = mid * (Decimal("1") + sgn * spread) * (Decimal("1") + sgn * slip)
        exec_price = exec_price.quantize(Decimal("0.00000001"))  # 8 знаков — достаточно для крипто

        # количество по запросу
        qty = req.qty
        if qty <= 0:
            raise ValueError("PaperExchange: qty must be positive")

        # Проводим балансы
        base = req.pair.base
        quote = req.pair.quote

        # Убедимся, что в балансе есть ключи
        self._ensure_asset(base)
        self._ensure_asset(quote)

        if req.side == Side.BUY:
            cost = (qty * exec_price).quantize(Decimal("0.00000001"))
            self._balances[quote] -= cost
            self._balances[base] += qty
        else:
            # SELL — списываем базовый актив, зачисляем котируемый
            proceeds = (qty * exec_price).quantize(Decimal("0.00000001"))
            self._balances[base] -= qty
            self._balances[quote] += proceeds

        # Создадим order_id и fill
        order_id = f"paper-{next(self._order_seq)}"
        ts_ms = int(time.time() * 1000)
        fill_qty = qty if req.side == Side.BUY else -qty
        fill = TradeFill(
            order_id=order_id,
            pair=req.pair,
            qty=fill_qty,
            price=exec_price,
            ts_ms=ts_ms,
        )
        self._fills.append(fill)
        return order_id

    def cancel(self, order_id: str) -> None:
        # В этой простой модели исполнение мгновенное — отменять нечего.
        return None

    def get_fills(self, client_id: str) -> Iterable[TradeFill]:
        """
        Простая реализация: возвращаем все накопленные fill'ы (клиент не фильтруется).
        В дальнейшем можно привязать по client_id.
        """
        return list(self._fills)

    def get_balance(self, asset: str) -> Decimal:
        self._ensure_asset(asset)
        return self._balances[asset]

    # ==== Helpers ====

    def _ensure_asset(self, asset: str) -> None:
        if asset not in self._balances:
            # если неизвестная валюта — добавим с нулём
            self._balances[asset] = Decimal("0")

    # ==== Диагностика ====

    def snapshot(self) -> Dict[str, object]:
        """Снимок состояния: балансы и последние сделки."""
        return {
            "balances": {k: str(v) for k, v in self._balances.items()},
            "fills": [
                {
                    "order_id": f.order_id,
                    "pair": f"{f.pair.base}_{f.pair.quote}",
                    "qty": str(f.qty),
                    "price": str(f.price),
                    "ts_ms": f.ts_ms,
                }
                for f in self._fills[-50:]
            ],
        }

    # ==== Утилиты для тестов ====

    @classmethod
    def with_quote_funds(
            cls,
            market: MarketDataPort,
            quote_asset: str,
            amount: Decimal | str | float,
            **kwargs,
    ) -> "PaperExchange":
        """
        Удобный конструктор для тестов: задать стартовый кэш в котируемой валюте.
        """
        inst = cls(
            market=market,
            initial_balances={quote_asset: _to_decimal(amount)},
            **kwargs,
        )
        return inst
