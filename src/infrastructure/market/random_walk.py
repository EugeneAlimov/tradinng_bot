from __future__ import annotations

import time
import random
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Sequence, Tuple, List, Dict, Optional

from src.core.domain.models import TradingPair
from src.core.ports.market_data import MarketDataPort

# финансовые расчёты: больше точности
getcontext().prec = 34


def _dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


_TIMEFRAMES_SEC: Dict[str, int] = {
    "1s": 1,
    "5s": 5,
    "10s": 10,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


@dataclass
class _Candle:
    ts_ms: int
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal

    def update(self, price: Decimal) -> None:
        if price > self.h:
            self.h = price
        if price < self.l:
            self.l = price
        self.c = price


@dataclass
class RandomWalkMarket(MarketDataPort):
    """
    Простая модель рынка с рандом-воком:
      price_{t+1} = price_t * (1 + drift_bps + noise_bps),
    где noise_bps ~ N(0, vol_bps) (гауссов шум в базисных пунктах).

    Поддерживает:
      - get_price(pair)
      - get_candles(pair, timeframe, limit)
      - tick(n=1) для сдвига времени и цены
    """

    start_price: Decimal = Decimal("0.1")
    drift_bps: float = 0.0  # средний дрейф в б.п. за тик
    vol_bps: float = 20.0  # стандартное отклонение в б.п. за тик
    seed: Optional[int] = None
    max_candles: int = 2000
    tick_seconds: int = 1  # «логическая» длительность одного tick() в секундах

    _price: Decimal = field(default=Decimal("0"), init=False)
    _rng: random.Random = field(default_factory=random.Random, init=False)
    _now_ms: int = field(default=0, init=False)
    _candles: Dict[str, List[_Candle]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.seed is not None:
            self._rng.seed(self.seed)
        self._price = _dec(self.start_price)
        self._now_ms = int(time.time() * 1000)
        # инициализируем пустые буферы для всех известных таймфреймов
        for tf in _TIMEFRAMES_SEC:
            self._candles[tf] = []
            self._roll_candle(tf, init=True)

    # ========== API ==========

    def get_price(self, pair: TradingPair) -> Decimal:
        return self._price

    def get_candles(
            self,
            pair: TradingPair,
            timeframe: str,
            limit: int,
    ) -> Sequence[Tuple[int, Decimal, Decimal, Decimal, Decimal]]:
        tf = self._normalize_tf(timeframe)
        buf = self._candles.get(tf, [])
        # гарантируем, что текущая незакрытая свеча обновлена последней ценой
        # (она уже обновляется в tick, так что тут только выдать)
        out = buf[-limit:] if limit > 0 else buf[:]
        return [(c.ts_ms, c.o, c.h, c.l, c.c) for c in out]

    # ========== Симуляция ==========

    def tick(self, n: int = 1) -> None:
        """
        Сделать n шагов рандом-вока. Каждый шаг сдвигает «время» на tick_seconds
        и пересчитывает цену.
        """
        if n <= 0:
            return
        for _ in range(n):
            self._step_once()

    # ========== Внутреннее ==========

    def _step_once(self) -> None:
        # 1) обновляем «текущее время»
        self._now_ms += int(self.tick_seconds * 1000)

        # 2) генерируем процентное изменение в б.п.
        # noise ~ N(0, vol_bps)
        noise_bps = self._gauss(0.0, self.vol_bps)
        total_bps = Decimal(str(self.drift_bps + noise_bps))
        pct = total_bps / Decimal("10000")  # bps -> fraction

        # 3) новая цена
        new_price = (self._price * (Decimal("1") + pct)).quantize(Decimal("0.00000001"))
        # минимальная цена > 0
        if new_price <= 0:
            new_price = Decimal("0.00000001")
        self._price = new_price

        # 4) обновление всех свечей (по всем tf)
        for tf in _TIMEFRAMES_SEC:
            self._update_candle(tf, new_price)

    def _gauss(self, mu: float, sigma: float) -> float:
        # random.gauss даёт float — этого хватает, дальше переводим в Decimal
        return self._rng.gauss(mu, sigma)

    def _normalize_tf(self, tf: str) -> str:
        if tf not in _TIMEFRAMES_SEC:
            # fallback к 1s, если неизвестный tf
            return "1s"
        return tf

    def _roll_candle(self, tf: str, init: bool = False) -> None:
        """Открыть новую свечу для tf, опционально при инициализации."""
        secs = _TIMEFRAMES_SEC[tf]
        # якорим начало свечи на кратный интервал
        base_ms = (self._now_ms // (secs * 1000)) * (secs * 1000)
        c = _Candle(ts_ms=base_ms, o=self._price, h=self._price, l=self._price, c=self._price)
        if init:
            self._candles[tf].append(c)
        else:
            buf = self._candles[tf]
            buf.append(c)
            if len(buf) > self.max_candles:
                # ограничиваем длину буфера
                del buf[: len(buf) - self.max_candles]

    def _update_candle(self, tf: str, price: Decimal) -> None:
        secs = _TIMEFRAMES_SEC[tf]
        buf = self._candles[tf]
        if not buf:
            self._roll_candle(tf, init=True)
            buf = self._candles[tf]

        cur = buf[-1]
        # если шаг перешёл в новый слот tf — закроем текущую и откроем новую
        if self._now_ms >= cur.ts_ms + secs * 1000:
            self._roll_candle(tf)
            cur = buf[-1]
        # обновляем текущую свечу новой ценой
        cur.update(price)
