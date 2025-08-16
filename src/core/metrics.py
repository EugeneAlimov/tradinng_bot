# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Optional
import math
import numpy as np
import pandas as pd


def _time_spacing_seconds(time_series: pd.Series) -> float:
    """Оцениваем медианный шаг таймстампов (в секундах). Без .view()."""
    if time_series is None or len(time_series) < 2:
        return 60.0
    # для tz-aware datetime64[ns, UTC] вернёт наносекунды
    ints = time_series.astype("int64").to_numpy()
    diffs = np.diff(ints)
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return 60.0
    return float(np.median(diffs) / 1e9)


def _max_drawdown(equity: np.ndarray) -> float:
    """Максимальная просадка в долях (0..1)."""
    if equity.size < 2:
        return 0.0
    cummax = np.maximum.accumulate(equity)
    dd = equity / np.where(cummax == 0, 1.0, cummax) - 1.0
    return float(abs(np.min(dd)))


def _sharpe(equity_df: pd.DataFrame) -> float:
    """Sharpe по приростам equity с приведением к секундам."""
    if equity_df is None or equity_df.empty or len(equity_df) < 3:
        return 0.0
    e = equity_df["equity"].astype(float).to_numpy()
    if np.allclose(e.std(), 0):
        return 0.0
    # доходности между соседними точками
    ret = np.diff(e) / np.where(e[:-1] == 0, 1.0, e[:-1])
    if not np.isfinite(ret).any():
        return 0.0
    mu = float(np.mean(ret))
    sd = float(np.std(ret, ddof=1)) if len(ret) > 1 else 0.0
    if sd <= 0:
        return 0.0
    dt_seconds = _time_spacing_seconds(pd.to_datetime(equity_df["time"], utc=True))
    # условно приводим к "в секунду"
    scale = math.sqrt(max(1e-9, 1.0 / dt_seconds))
    return float(mu / sd * scale)


def _roundtrip_pnls(trades: List[Dict[str, Any]]) -> List[float]:
    """
    Собираем PnL завершённых 'продаж' (в run_backtest_sma он пишется в sell['pnl']).
    Если pnl нет, считаем 0 (консервативно).
    """
    if not trades:
        return []
    pnls = []
    for t in trades:
        if t.get("side") == "sell":
            p = t.get("pnl")
            if p is None:
                # на всякий случай
                p = 0.0
            pnls.append(float(p))
    return pnls


def compute_metrics_from_equity(
        equity_df: Optional[pd.DataFrame],
        trades: List[Dict[str, Any]],
        start_eur: float
) -> Dict[str, Any]:
    """
    Унифицированный расчёт метрик.
    - Если есть equity_df — берём end, sharpe, dd отсюда.
    - PF/win_rate считаем по pnl закрытий (sell).
    - Если equity_df пуст, оцениваем конечный баланс по списку сделок.
    """
    # end
    if equity_df is not None and not equity_df.empty:
        end_equity = float(equity_df["equity"].iloc[-1])
    else:
        # грубая реконструкция по сделкам (pos в конце в бэктесте закрывается)
        eq = float(start_eur)
        for t in trades or []:
            side = t.get("side")
            qty = float(t.get("qty", 0.0) or 0.0)
            price = float(t.get("price", 0.0) or 0.0)
            fee = float(t.get("fee", 0.0) or 0.0)
            slip = float(t.get("slip", 0.0) or 0.0)
            notional = qty * price
            if side == "buy":
                eq -= (notional + fee + slip)
            elif side == "sell":
                eq += (notional - fee - slip)
        end_equity = float(eq)

    # Sharpe/DD
    sharpe = _sharpe(equity_df) if (equity_df is not None and not equity_df.empty) else 0.0
    max_dd = _max_drawdown(equity_df["equity"].astype(float).to_numpy()) if (
                equity_df is not None and not equity_df.empty) else 0.0

    # PF / win-rate / trades
    pnls = _roundtrip_pnls(trades or [])
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    wins_sum = float(np.sum(wins)) if wins else 0.0
    losses_sum = float(np.sum(losses)) if losses else 0.0
    if losses_sum == 0.0:
        profit_factor: Any = ("inf" if wins_sum > 0.0 else 0.0)
    else:
        profit_factor = (wins_sum / losses_sum)
    win_rate = (len(wins) / len(pnls) * 100.0) if pnls else 0.0

    return {
        "start": float(start_eur),
        "end": end_equity,
        "total_pnl": float(end_equity - float(start_eur)),
        "trades": int(len(pnls)),
        "win_rate": float(win_rate),
        "profit_factor": profit_factor,
        "max_drawdown": float(max_dd),
        "sharpe": float(sharpe),
    }


# совместимость со старым названием
def _compute_metrics_from_equity(equity_df, trades, start_eur):
    return compute_metrics_from_equity(equity_df, trades, start_eur)


def parse_range(spec: str) -> List[int]:
    """'5:30:1' -> [5..30]; '10:50:5' -> [10,15,...,50]; '20' -> [20]."""
    if not spec:
        return []
    parts = [int(x) for x in str(spec).split(":")]
    if len(parts) == 1:
        return parts
    if len(parts) == 2:
        a, b = parts
        s = 1
    else:
        a, b, s = parts[:3]
    if s == 0:
        s = 1
    if a > b:
        a, b = b, a
    return list(range(a, b + 1, s))


def needs_equity(metric: str) -> bool:
    m = (metric or "").lower()
    return m in ("sharpe", "max_drawdown", "dd")


def risk_based_qty(
        equity_eur: float,
        entry_price: float,
        stop_price: float,
        risk_pct: float,
        price_tick: float,
        qty_step: float,
        min_quote: float,
) -> float:
    """К-во базовой монеты из % риска на сделку."""
    import math
    import numpy as np

    if risk_pct <= 0.0 or not np.isfinite(entry_price) or not np.isfinite(stop_price):
        return 0.0
    dist = abs(entry_price - stop_price)
    if dist <= 0.0:
        return 0.0
    risk_eur = equity_eur * (risk_pct / 100.0)
    raw = risk_eur / dist
    if qty_step and qty_step > 0:
        raw = math.floor(raw / qty_step) * qty_step
    px = max(entry_price, price_tick or entry_price)
    if min_quote and min_quote > 0:
        raw = max(raw, (min_quote / px))
        if qty_step and qty_step > 0:
            raw = math.ceil(raw / qty_step) * qty_step
    return max(0.0, float(raw))
