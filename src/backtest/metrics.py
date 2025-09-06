# src/backtest/metrics.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EquityMetrics:
    bars: int
    n_trades: int
    n_wins: int
    total_pnl: float
    winrate: float
    exposure_pct: float
    start_equity: float
    end_equity: float
    cagr: float
    sharpe: float
    max_dd: float
    profit_factor: float

    @property
    def trades(self) -> int:
        return self.n_trades

    @property
    def winrate_pct(self) -> float:
        return float(self.winrate) * 100.0

    @property
    def max_drawdown_pct(self) -> float:
        return float(self.max_dd) * 100.0  # (<= 0)

    @property
    def cagr_pct(self) -> float:
        return float(self.cagr) * 100.0

    @property
    def calmar(self) -> float:
        dd = abs(float(self.max_dd))
        if dd == 0.0:
            return float("inf") if self.cagr > 0 else 0.0
        return float(self.cagr) / dd


def _max_drawdown(equity: pd.Series) -> float:
    run_max = equity.cummax()
    dd = (equity / run_max - 1.0).fillna(0.0)
    return float(dd.min())


def _annualization_factor(idx: pd.DatetimeIndex) -> float:
    if len(idx) < 2:
        return 0.0
    dt = (idx[-1] - idx[0]).total_seconds() / max(1, len(idx) - 1)
    if dt <= 0:
        return 0.0
    bars_per_day = 86400.0 / dt
    return 365.0 * bars_per_day


def compute_equity_metrics(
        equity: pd.Series,
        trade_pnls: Sequence[float] | Iterable[float],
        n_wins: int,
        n_trades: int,
        exposure_pct: float,
        start_equity: float,
        risk_free: float = 0.0,
) -> EquityMetrics:
    equity = pd.to_numeric(equity, errors="coerce").ffill().astype(float)
    bars = int(len(equity))
    end_equity = float(equity.iloc[-1]) if bars else float(start_equity)
    pnls = list(trade_pnls)
    total_pnl = float(np.nansum(pnls))
    winrate = float(n_wins) / float(n_trades) if n_trades else 0.0

    pos = sum(x for x in pnls if x > 0)
    neg = -sum(x for x in pnls if x < 0)
    if neg == 0:
        profit_factor = float("inf") if pos > 0 else 0.0
    else:
        profit_factor = float(pos) / float(neg)

    years = (equity.index[-1] - equity.index[0]).days / 365.0 if bars > 1 else 0.0
    if years <= 0:
        cagr = 0.0
    else:
        cagr = (end_equity / float(start_equity)) ** (1.0 / years) - 1.0

    rets = equity.pct_change().dropna()
    ann = _annualization_factor(equity.index)
    if len(rets) > 1 and ann > 0:
        mu = float(rets.mean()) - risk_free / max(1.0, ann)
        sd = float(rets.std(ddof=1))
        sharpe = (mu / sd) * (ann ** 0.5) if sd > 0 else 0.0
    else:
        sharpe = 0.0

    max_dd = _max_drawdown(equity)

    return EquityMetrics(
        bars=bars,
        n_trades=int(n_trades),
        n_wins=int(n_wins),
        total_pnl=total_pnl,
        winrate=winrate,
        exposure_pct=float(exposure_pct),
        start_equity=float(start_equity),
        end_equity=float(end_equity),
        cagr=float(cagr),
        sharpe=float(sharpe),
        max_dd=float(max_dd),
        profit_factor=float(profit_factor),
    )
