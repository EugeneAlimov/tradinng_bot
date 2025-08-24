# src/domain/strategy/bbands_meanrev.py
from __future__ import annotations

from typing import List, Optional, Tuple

from .registry import StrategyDef, register


def _rolling_mean_std(series: List[float], window: int) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    Простая скользящая mean/std по окну window. O(n*window) — для 1-5k баров ок.
    """
    n = max(2, int(window))
    means: List[Optional[float]] = [None] * len(series)
    stds: List[Optional[float]] = [None] * len(series)
    for i in range(len(series)):
        if i < n - 1:
            continue
        win = series[i - n + 1 : i + 1]
        mu = sum(win) / n
        var = sum((x - mu) ** 2 for x in win) / n
        means[i] = mu
        stds[i] = var ** 0.5
    return means, stds


def generate_signals(
    prices: List[float],
    length: int = 20,
    mult: float = 2.0,
    exit_rule: str = "mid",  # 'mid' или 'upper'
) -> List[int]:
    """
    Bollinger Bands mean-reversion (по Close):
      +1 — если Close пересекает нижнюю полоску вниз (сверху-вниз),
      -1 — выход: по пересечению средины ('mid') или верхней ('upper') — конфигурируемо.
    """
    length = max(2, int(length))
    mult = float(mult)
    exit_rule = (exit_rule or "mid").lower()
    mean, std = _rolling_mean_std(prices, length)
    upper = [None if mean[i] is None or std[i] is None else mean[i] + mult * std[i] for i in range(len(prices))]
    lower = [None if mean[i] is None or std[i] is None else mean[i] - mult * std[i] for i in range(len(prices))]

    signals = [0] * len(prices)
    prev_c = None
    for i, c in enumerate(prices):
        m = mean[i]
        u = upper[i]
        l = lower[i]
        if m is None or u is None or l is None:
            prev_c = c
            continue
        # вход — когда пересекли вниз нижнюю
        if prev_c is not None and prev_c >= l and c < l:
            signals[i] = +1
        else:
            # выход — или по mid, или по upper
            if exit_rule == "mid":
                if prev_c is not None and prev_c <= m and c > m:
                    signals[i] = -1
            else:  # 'upper'
                if prev_c is not None and prev_c <= u and c > u:
                    signals[i] = -1
        prev_c = c
    return signals


def status(prices: List[float], length: int = 20, mult: float = 2.0, exit_rule: str = "mid") -> Tuple[str, int]:
    mean, std = _rolling_mean_std(prices, max(2, int(length)))
    i = len(prices) - 1
    if i < 0 or mean[i] is None or std[i] is None:
        return f"BB(len={length}, mult={mult}) μ=?, σ=?", 0
    mu = float(mean[i])
    sigma = float(std[i])
    c = float(prices[i])
    u = mu + float(mult) * sigma
    l = mu - float(mult) * sigma
    # state: ниже нижней => 1 (покупать), выше верхней => -1 (продавать), иначе 0
    state = 1 if c < l else (-1 if c > u else 0)
    return f"BB(len={length}, mult={mult}) μ={mu:.6f} σ={sigma:.6f} U={u:.6f} L={l:.6f}", state


register(StrategyDef(
    name="bbands",
    generate_signals=generate_signals,
    status=status,
    defaults={"length": 20, "mult": 2.0, "exit_rule": "mid"},
))
