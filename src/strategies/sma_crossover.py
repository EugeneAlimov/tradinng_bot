from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Dict, Any, Sequence, Tuple

from src.core.domain.models import TradingPair

getcontext().prec = 34


def _dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _sma(series: Sequence[Decimal], length: int) -> Decimal:
    length = int(length)
    if length <= 0 or len(series) < length:
        return Decimal("0")
    return sum(series[-length:]) / Decimal(length)


@dataclass
class SmaCfg:
    fast: int = 6
    slow: int = 30
    # Порог гистерезиса в б.п. относительно ЦЕНЫ:
    # |fast - slow| / price * 10000 >= min_gap_bps  (0 => без фильтра)
    min_gap_bps: Decimal = Decimal("0")

    def lookback(self) -> int:
        return max(self.fast, self.slow) + 2


@dataclass
class SmaCrossover:
    """
    SMA crossover:
      BUY  — fast пересекает slow снизу вверх И расхождение >= min_gap_bps (в б.п. цены)
      SELL — fast пересекает slow сверху вниз И расхождение >= min_gap_bps
      HOLD — иначе

    ctx:
      ctx["candles"] = Sequence[(ts_ms, o,h,l,c)]
      ctx["last_price"] = Decimal (если нет — возьмём close)
    """
    cfg: SmaCfg = field(default_factory=SmaCfg)

    def decide(self, pair: TradingPair, ctx: Dict[str, Any]) -> Dict[str, Any]:
        candles: Sequence[Tuple[int, Decimal, Decimal, Decimal, Decimal]] = ctx.get("candles") or ()
        if not candles or len(candles) < self.cfg.lookback():
            return {"action": "HOLD", "reason": "not_enough_candles"}

        closes = [_dec(c[4]) for c in candles]
        if len(closes) < self.cfg.slow + 1:
            return {"action": "HOLD", "reason": "not_enough_history"}

        fast_prev = _sma(closes[:-1], self.cfg.fast)
        slow_prev = _sma(closes[:-1], self.cfg.slow)
        fast_now = _sma(closes, self.cfg.fast)
        slow_now = _sma(closes, self.cfg.slow)

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        last_price: Decimal = _dec(ctx.get("last_price") or closes[-1] or 0)
        gap_now_bps = self._gap_bps_price(fast_now, slow_now, last_price)

        if crossed_up and gap_now_bps >= self.cfg.min_gap_bps:
            return {"action": "BUY", "reason": "fast_cross_up",
                    "fast": str(fast_now), "slow": str(slow_now), "gap_bps": str(gap_now_bps)}

        if crossed_down and gap_now_bps >= self.cfg.min_gap_bps:
            return {"action": "SELL", "reason": "fast_cross_down",
                    "fast": str(fast_now), "slow": str(slow_now), "gap_bps": str(gap_now_bps)}

        return {"action": "HOLD", "reason": "no_confirmed_cross",
                "fast": str(fast_now), "slow": str(slow_now), "gap_bps": str(gap_now_bps)}

    @staticmethod
    def _gap_bps_price(a: Decimal, b: Decimal, price: Decimal) -> Decimal:
        # |a-b| / price * 10000
        p = _dec(price)
        if p <= 0:
            return Decimal("0")
        return (abs(a - b) / p * Decimal("10000")).quantize(Decimal("0.0001"))
