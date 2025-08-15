# -*- coding: utf-8 -*-
from collections import deque
from typing import Optional, NamedTuple

class Bar(NamedTuple):
    ts: int      # unix seconds (UTC)
    o: float; h: float; l: float; c: float; v: float

class Signal(NamedTuple):
    side: str        # "buy" | "sell"
    price: float
    reason: str

class SMA:
    def __init__(self, n: int):
        self.n = n
        self.q = deque()
        self.s = 0.0

    def push(self, x: float) -> Optional[float]:
        self.q.append(x); self.s += x
        if len(self.q) > self.n:
            self.s -= self.q.popleft()
        if len(self.q) == self.n:
            return self.s / self.n
        return None

class SmaCross:
    """Простая стратегия: лонг при пересечении fast вверх slow, выход при обратном пересечении."""
    def __init__(self, fast: int, slow: int):
        assert fast < slow, "fast < slow"
        self.fast = SMA(fast)
        self.slow = SMA(slow)
        self.in_position = False
        self.last = None  # "up" | "down" | None

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        f = self.fast.push(bar.c)
        s = self.slow.push(bar.c)
        if f is None or s is None:
            return None
        if (not self.in_position) and f >= s and self.last != "up":
            self.in_position = True
            self.last = "up"
            return Signal("buy", bar.c, "sma_cross_up")
        if self.in_position and f < s and self.last != "down":
            self.in_position = False
            self.last = "down"
            return Signal("sell", bar.c, "sma_cross_down")
        return None
