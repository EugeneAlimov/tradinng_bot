# src/backtest/pnl.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Dict, Any, List, Tuple

import math

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # будет работать и без numpy

from src.backtest.metrics import compute_equity_metrics  # используем твою реализацию


PnlMode = Literal["return", "price"]


@dataclass
class Trade:
    """
    Унифицированная модель сделки.
    Если в твоём коде уже формируются словари с этими полями — их можно подавать как **dict**,
    а мы приведём к Trade автоматически.
    """
    entry_time: Any
    exit_time: Any
    side: str              # "long" / "short"
    entry_price: float
    exit_price: float
    qty: float = 1.0       # используется только в price-режиме
    fees: float = 0.0      # абсолютные комиссии на сделку
    slippage: float = 0.0  # абсолютное проскальзывание, если не учтено в цене


def _as_trade_list(trades: Iterable[Trade] | Iterable[Dict[str, Any]]) -> List[Trade]:
    out: List[Trade] = []
    for t in trades:
        if isinstance(t, Trade):
            out.append(t)
        else:
            out.append(Trade(**t))  # приведём dict к Trade
    return out


def compute_trade_pnl_vector(
    trades: Iterable[Trade] | Iterable[Dict[str, Any]],
    mode: PnlMode = "return",
) -> Tuple[List[float], List[Trade]]:
    """
    Возвращает (вектор pnl по сделкам, список Trade).
    - mode='return': pnl = sign * (exit/entry - 1) - fees - slippage
    - mode='price':  pnl = sign * (exit - entry) * qty - fees - slippage
    """
    ts = _as_trade_list(trades)
    out: List[float] = []
    for t in ts:
        sign = 1.0 if str(t.side).lower() == "long" else -1.0
        if mode == "return":
            base = (t.exit_price / t.entry_price - 1.0) if t.entry_price > 0 else 0.0
            pnl = sign * base
        else:
            pnl = sign * (t.exit_price - t.entry_price) * float(t.qty or 1.0)
        pnl -= float(t.fees or 0.0)
        pnl -= float(t.slippage or 0.0)
        out.append(float(pnl))
    return out, ts


def trades_to_equity(
    per_trade_pnl: Iterable[float],
    mode: PnlMode = "return",
    start_equity: float = 1.0,
) -> List[float]:
    """
    Строит кумулятивную equity:
      - mode='return': equity = start * cumprod(1 + pnl_i)
      - mode='price':  equity = start + cumsum(pnl_i)
    """
    eq: List[float] = []
    cur = float(start_equity)
    if mode == "return":
        eq.append(cur)
        for r in per_trade_pnl:
            cur *= (1.0 + float(r))
            eq.append(cur)
    else:
        eq.append(cur)
        for p in per_trade_pnl:
            cur += float(p)
            eq.append(cur)
    return eq


def evaluate_from_trades(
    trades: Iterable[Trade] | Iterable[Dict[str, Any]],
    mode: PnlMode = "return",
    start_equity: float = 1.0,
    bars_per_year: float | None = None,
) -> Dict[str, Any]:
    """
    Удобный «всё-в-одном»:
      1) считаем pnl по сделкам (return/price),
      2) строим equity,
      3) считаем метрики через src.backtest.metrics.compute_equity_metrics(...).

    Возвращает расширенный словарь метрик из твоего metrics.py + добавляет:
      - n_trades, n_wins пересчитанные по сделкам
      - win_rate (%)
      - avg_pnl, total_pnl (в тех же единицах, что и pnl: проценты или цена)
    """
    pnls, ts = compute_trade_pnl_vector(trades, mode=mode)
    n_trades = len(pnls)
    n_wins = sum(1 for x in pnls if x > 0)
    win_rate = (n_wins / n_trades * 100.0) if n_trades > 0 else 0.0
    avg_pnl = (sum(pnls) / n_trades) if n_trades > 0 else 0.0
    total_pnl = sum(pnls) if n_trades > 0 else 0.0

    eq = trades_to_equity(pnls, mode=mode, start_equity=start_equity)
    # equity-моду отдаём: trade_pnls и bars_per_year (если есть)
    m = compute_equity_metrics(
        equity=eq,
        trade_pnls=pnls,
        n_wins=n_wins,
        n_trades=n_trades,
        bars_per_year=bars_per_year,
        start_equity=start_equity,
    )

    # Для удобства добавим наши «локальные» поля (совместимо с тем, что печатает CLI)
    m.update({
        "win_rate": float(win_rate),
        "avg_pnl": float(avg_pnl),
        "total_pnl": float(total_pnl),
    })
    return m
