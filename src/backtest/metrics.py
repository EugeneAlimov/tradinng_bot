from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple, Optional
import numpy as np
import pandas as pd


YEAR_SECONDS = 365 * 24 * 60 * 60


def _safe_std(x: np.ndarray) -> float:
    if len(x) < 2:
        return 0.0
    return float(np.std(x, ddof=1))


def estimate_bars_per_year(index: pd.DatetimeIndex) -> float:
    """
    Оцениваем число баров в год по медианной длительности бара.
    Работает и для 24/7 крипты, и для нерегулярного ряда.
    """
    if len(index) < 2:
        return 1.0
    dt = np.diff(index.view("i8"))  # наносекунды между барами
    median_ns = np.median(dt)
    if median_ns <= 0:
        return 1.0
    seconds_per_bar = median_ns / 1e9
    return YEAR_SECONDS / seconds_per_bar


def max_drawdown(equity: pd.Series) -> Tuple[float, float, float]:
    """
    Возвращает (max_drawdown_pct, peak_value, trough_value)
    где max_drawdown_pct — отрицательная величина (например, -0.25 == -25%).
    """
    if equity.isna().all() or len(equity) == 0:
        return (0.0, np.nan, np.nan)

    eq = equity.fillna(method="ffill").fillna(method="bfill")
    running_max = eq.cummax()
    dd = eq / running_max - 1.0
    md = float(dd.min())
    # peak/trough значения (не даты)
    trough_idx = int(np.argmin(dd.values))
    peak_val = float(running_max.iloc[: trough_idx + 1].max())
    trough_val = float(eq.iloc[trough_idx])
    return (md, peak_val, trough_val)


def cagr(equity: pd.Series, bars_per_year: float) -> float:
    """
    CAGR с учётом частоты баров.
    """
    if len(equity) < 2:
        return 0.0
    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start <= 0:
        return 0.0
    years = len(equity) / max(bars_per_year, 1.0)
    if years <= 0:
        return 0.0
    return (end / start) ** (1.0 / years) - 1.0


def sharpe_from_equity(equity: pd.Series, bars_per_year: float, risk_free: float = 0.0) -> float:
    """
    Sharpe на основе поминутных/побарных доходностей, далее годовой.
    risk_free задаётся в тех же единицах, что и доходности (на бар).
    """
    if len(equity) < 3:
        return 0.0
    eq = equity.astype(float)
    rets = eq.pct_change().dropna().values
    if len(rets) == 0:
        return 0.0
    mean = float(np.mean(rets) - risk_free)
    std = _safe_std(rets)
    if std == 0.0:
        return 0.0
    return (mean / std) * np.sqrt(max(bars_per_year, 1.0))


def profit_factor(trade_pnls: Iterable[float]) -> float:
    """
    PF = sum(positive) / |sum(negative)|
    """
    pos = 0.0
    neg = 0.0
    for p in trade_pnls:
        if p > 0:
            pos += p
        elif p < 0:
            neg += p
    if neg == 0.0:
        return float("inf") if pos > 0 else 0.0
    return pos / abs(neg)


@dataclass
class EquityMetrics:
    bars: int
    trades: int
    winrate_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    final_equity_eur: float
    start_equity_eur: float
    profit_factor: float
    avg_trade_eur: float
    exposure_pct: float
    sharpe: float
    cagr_pct: float
    calmar: float
    bars_per_year: float


def compute_equity_metrics(
    equity: pd.Series,
    trade_pnls: Iterable[float],
    n_wins: int,
    n_trades: int,
    exposure_pct: float,
    start_equity: float = 1000.0,
    risk_free: float = 0.0,
    bars_per_year_hint: Optional[float] = None,
) -> EquityMetrics:
    """
    Унифицированный расчёт метрик по кривой капитала и PnL сделок.
    """
    equity = equity.astype(float)
    bars = int(equity.size)
    start = float(equity.iloc[0] if bars > 0 else start_equity)
    end = float(equity.iloc[-1] if bars > 0 else start_equity)

    bpy = float(bars_per_year_hint or estimate_bars_per_year(equity.index))
    total_ret = end / max(start, 1e-12) - 1.0
    md, _, _ = max_drawdown(equity)
    shp = sharpe_from_equity(equity, bpy, risk_free=risk_free)
    cg = cagr(equity, bpy)
    calmar = (cg / abs(md)) if abs(md) > 1e-12 else float("inf")
    pf = profit_factor(trade_pnls)

    avg_trade = (np.mean(list(trade_pnls)) if n_trades > 0 else 0.0)

    return EquityMetrics(
        bars=bars,
        trades=n_trades,
        winrate_pct=(100.0 * n_wins / n_trades) if n_trades > 0 else 0.0,
        total_return_pct=100.0 * total_ret,
        max_drawdown_pct=md * 100.0,
        final_equity_eur=end,
        start_equity_eur=start,
        profit_factor=pf,
        avg_trade_eur=avg_trade,
        exposure_pct=exposure_pct,
        sharpe=shp,
        cagr_pct=100.0 * cg,
        calmar=calmar * 100.0,  # чтобы совпадать по шкале с твоими табличками
        bars_per_year=bpy,
    )
