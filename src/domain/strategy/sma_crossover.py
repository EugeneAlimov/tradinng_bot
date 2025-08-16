from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Dict, Any, Sequence, Tuple, Optional

from src.core.domain.models import TradingPair

# чуть больше точности для финансовых расчётов
getcontext().prec = 34


def _dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _sma(values: Sequence[Decimal]) -> Optional[Decimal]:
    n = len(values)
    if n == 0:
        return None
    s = sum(values, Decimal("0"))
    return (s / _dec(n)).quantize(Decimal("0.00000001"))


@dataclass
class SmaCfg:
    timeframe: str = "1m"
    fast: int = 10
    slow: int = 30
    min_gap_bps: Decimal = Decimal("2")  # минимальный зазор между SMA в б.п. для подтверждения сигнала

    def lookback(self) -> int:
        # возьмём +2, чтобы корректно проверить факт «пересечения» между предыдущей и текущей свечой
        return max(self.fast, self.slow) + 2


@dataclass
class SmaCrossover:
    """
    Простая стратегия SMA crossover:
      BUY  — если fast пересекает slow снизу вверх (и gap >= min_gap_bps)
      SELL — если fast пересекает slow сверху вниз (и gap >= min_gap_bps)
      HOLD — иначе
    В ctx ожидается:
      ctx["candles"] = Sequence[(ts_ms, o,h,l,c)]
      ctx["last_price"] = Decimal (опционально, для логов)
    """
    cfg: SmaCfg = field(default_factory=SmaCfg)

    def decide(self, pair: TradingPair, ctx: Dict[str, Any]) -> Dict[str, Any]:
        candles: Sequence[Tuple[int, Decimal, Decimal, Decimal, Decimal]] = ctx.get("candles") or ()
        if not candles or len(candles) < self.cfg.lookback():
            return {"action": "HOLD", "reason": "not_enough_candles"}

        closes = [c[4] for c in candles]  # close = c
        # вычислим SMA fast и slow на предыдущей и текущей «точках»
        if len(closes) < self.cfg.slow + 1:
            return {"action": "HOLD", "reason": "not_enough_history"}

        # текущие SMA
        fast_now = _sma(closes[-self.cfg.fast:])
        slow_now = _sma(closes[-self.cfg.slow:])

        # предыдущие SMA (на один шаг назад)
        fast_prev = _sma(closes[-self.cfg.fast - 1:-1])
        slow_prev = _sma(closes[-self.cfg.slow - 1:-1])

        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return {"action": "HOLD", "reason": "sma_none"}

        # Проверка пересечения
        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        # Минимальный зазор в б.п. для подтверждения
        gap_now_bps = self._gap_bps(fast_now, slow_now)

        if crossed_up and gap_now_bps >= self.cfg.min_gap_bps:
            return {
                "action": "BUY",
                "reason": "fast_cross_up",
                "fast": str(fast_now),
                "slow": str(slow_now),
                "gap_bps": str(gap_now_bps),
            }

        if crossed_down and gap_now_bps >= self.cfg.min_gap_bps:
            return {
                "action": "SELL",
                "reason": "fast_cross_down",
                "fast": str(fast_now),
                "slow": str(slow_now),
                "gap_bps": str(gap_now_bps),
            }

        return {
            "action": "HOLD",
            "reason": "no_confirmed_cross",
            "fast": str(fast_now),
            "slow": str(slow_now),
            "gap_bps": str(gap_now_bps),
        }

    @staticmethod
    def _gap_bps(a: Decimal, b: Decimal) -> Decimal:
        # |a-b| / avg(a,b) * 10000
        avg = (a + b) / Decimal("2")
        if avg <= 0:
            return Decimal("0")
        return (abs(a - b) / avg * Decimal("10000")).quantize(Decimal("0.0001"))
