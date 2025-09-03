# src/backtest/strategies/bbands.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd

BuildTrades = Tuple[List[Dict[str, Any]], np.ndarray]

def build(df: pd.DataFrame, params: Dict[str, Any]) -> BuildTrades:
    n = int(params.get("bb_len", 20))
    k = float(params.get("bb_k", 2.0))
    close = df["close"].astype(float)
    mid = close.rolling(n, min_periods=n).mean()
    std = close.rolling(n, min_periods=n).std(ddof=0)
    up = mid + k * std
    lo = mid - k * std

    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []
    pos = None
    entry_i = None
    c = close.to_numpy()

    for i in range(1, len(close)):
        if np.isnan(up.iloc[i]) or np.isnan(mid.iloc[i]):
            continue
        # breakout вверх -> long, выход при возврате под mid
        if pos is None and c[i - 1] <= up.iloc[i - 1] and c[i] > up.iloc[i]:
            pos = float(c[i])
            entry_i = i
        elif pos is not None and c[i] < mid.iloc[i]:
            pnl = (float(c[i]) / pos) - 1.0
            pnls.append(pnl)
            trades.append(dict(entry_dt=str(df["dt"].iloc[entry_i]),
                               exit_dt=str(df["dt"].iloc[i]),
                               side="long", entry_price=pos, exit_price=float(c[i]), pnl=pnl))
            pos = None
            entry_i = None

    if pos is not None:
        i = len(c) - 1
        pnl = (float(c[i]) / pos) - 1.0
        pnls.append(pnl)
        trades.append(dict(entry_dt=str(df["dt"].iloc[entry_i]),
                           exit_dt=str(df["dt"].iloc[i]),
                           side="long", entry_price=pos, exit_price=float(c[i]), pnl=pnl))

    return trades, np.asarray(pnls, dtype=float)
