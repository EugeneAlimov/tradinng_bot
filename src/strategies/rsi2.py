# src/backtest/strategies/rsi2.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd

BuildTrades = Tuple[List[Dict[str, Any]], np.ndarray]

def _rsi(series: pd.Series, length: int) -> pd.Series:
    length = max(1, int(length))
    delta = series.diff()
    up = delta.clip(lower=0.0)
    dn = -delta.clip(upper=0.0)
    # Wilder
    roll_up = up.ewm(alpha=1/length, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)

def build(df: pd.DataFrame, params: Dict[str, Any]) -> BuildTrades:
    rl = int(params.get("rsi_len", 2))
    buy_below = float(params.get("buy_below", 10.0))
    sell_above = float(params.get("sell_above", 90.0))
    close = df["close"].astype(float).to_numpy()
    rsi = _rsi(df["close"].astype(float), rl).to_numpy()

    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []
    pos = None  # entry price
    entry_i = None

    for i in range(1, len(close)):
        if pos is None and rsi[i] < buy_below:
            pos = float(close[i])
            entry_i = i
        elif pos is not None and rsi[i] > sell_above:
            pnl = (float(close[i]) / pos) - 1.0
            pnls.append(pnl)
            trades.append(dict(entry_dt=str(df["dt"].iloc[entry_i]),
                               exit_dt=str(df["dt"].iloc[i]),
                               side="long", entry_price=pos, exit_price=float(close[i]), pnl=pnl))
            pos = None
            entry_i = None

    # закрыть в конце, если открыты
    if pos is not None:
        i = len(close) - 1
        pnl = (float(close[i]) / pos) - 1.0
        pnls.append(pnl)
        trades.append(dict(entry_dt=str(df["dt"].iloc[entry_i]),
                           exit_dt=str(df["dt"].iloc[i]),
                           side="long", entry_price=pos, exit_price=float(close[i]), pnl=pnl))
    return trades, np.asarray(pnls, dtype=float)
