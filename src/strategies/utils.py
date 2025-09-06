# src/strategies/utils.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _to_bps(x: float) -> float:
    return float(x) / 10_000.0


def build_trades_from_signals(
        df: pd.DataFrame,
        long_on: pd.Series,
        long_off: pd.Series,
        *,
        fees_bps: float = 0.0,
        slippage_bps: float = 0.0,
        size: float = 100.0,
        sl_mult: float = 0.0,
        tp_mult: float = 0.0,
        trail_mult: float = 0.0,
        vol_series: Optional[pd.Series] = None,
) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    Простейший симулятор: заходим по close на баре long_on, выходим по close на баре long_off.
    Комиссии и слиппедж применяются как пропорциональные стоимости сделки (в bps).
    Возвращает (list trades dicts, np.ndarray pnls).
    """
    close = df['close'].astype(float).reset_index(drop=True)
    ts = df['dt'] if 'dt' in df.columns else pd.to_datetime(df['timestamp'], unit='s', utc=True)
    ts = ts.reset_index(drop=True)
    long_on = long_on.reset_index(drop=True).astype(bool)
    long_off = long_off.reset_index(drop=True).astype(bool)

    fee = _to_bps(fees_bps)
    slip = _to_bps(slippage_bps)

    trades: List[Dict[str, Any]] = []
    in_pos = False
    entry_px = 0.0
    entry_ts = 0

    for i in range(len(close)):
        if not in_pos and long_on.iloc[i]:
            in_pos = True
            entry_px = float(close.iloc[i]) * (1.0 + slip)
            entry_ts = int(ts.iloc[i].timestamp())
            trades.append({
                "side": "LONG", "entry_px": entry_px, "entry_ts": entry_ts,
                "entry_dt": datetime.fromtimestamp(entry_ts, tz=timezone.utc).isoformat()
            })
            continue

        if in_pos and long_off.iloc[i]:
            exit_px = float(close.iloc[i]) * (1.0 - slip)
            exit_ts = int(ts.iloc[i].timestamp())
            gross = (exit_px - entry_px) / entry_px
            pnl = size * (gross - 2.0 * fee)  # комиссия при входе и выходе
            last = trades[-1]
            last.update({
                "exit_px": exit_px, "exit_ts": exit_ts,
                "exit_dt": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
                "bars_held": i,
                "pnl": float(pnl),
            })
            in_pos = False

    # закрываем на последнем баре если открыта позиция
    if in_pos:
        i = len(close) - 1
        exit_px = float(close.iloc[i]) * (1.0 - slip)
        exit_ts = int(ts.iloc[i].timestamp())
        gross = (exit_px - entry_px) / entry_px
        pnl = size * (gross - 2.0 * fee)
        last = trades[-1]
        last.update({
            "exit_px": exit_px, "exit_ts": exit_ts,
            "exit_dt": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
            "exit_reason": "close_on_last_bar",
            "bars_held": last.get("bars_held", 0),
            "pnl": float(pnl),
        })

    pnls = np.asarray([t.get("pnl", 0.0) for t in trades if "pnl" in t], dtype=float)
    return trades, pnls
