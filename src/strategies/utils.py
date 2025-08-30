# src/strategies/utils.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def build_trades_from_signals(
        df: pd.DataFrame,
        long_on: pd.Series,
        long_off: pd.Series,
        *,
        ema_fast: Optional[pd.Series] = None,
        ema_slow: Optional[pd.Series] = None,
        adx: Optional[pd.Series] = None,
) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    Универсальная сборка сделок из сигналов (только long, без flip).
    Возвращает (list of trades, np.ndarray pnl) — pnl в базовых единицах.
    Поля сделки:
      - trade_id: int
      - entry_bar_idx / exit_bar_idx: индексы баров в df
      - entry_ts/entry_dt, exit_ts/exit_dt: времена в Unix секундах / ISO UTC
      - entry_px/exit_px: цены входа/выхода
      - entry_reason/exit_reason: причины входа/выхода
      - bars_held: длительность в барах
      - hold_seconds: длительность в секундах
      - pnl: результат сделки в базовых единицах (до комиссий и проскальзывания)
    """
    if df.empty:
        return [], np.asarray([], dtype=float)

    # приведение типов
    close = df["close"].astype(float).to_numpy()
    ts = df["timestamp"].astype(int).to_numpy()

    pos = False
    entry_px = 0.0
    entry_i = -1
    next_trade_id = 1

    trades: List[Dict[str, Any]] = []

    n = len(df)
    for i in range(n):
        if (not pos) and bool(long_on.iat[i]):
            # Открытие позиции
            pos = True
            entry_px = float(close[i])
            entry_i = i
            e_ts = int(ts[i])

            reason = "ema_cross_up"
            if adx is not None and ema_fast is not None and ema_slow is not None:
                parts: List[str] = []
                if ema_fast.iat[i] > ema_slow.iat[i]:
                    parts.append("ema_fast>ema_slow")
                parts.append(f"adx={float(adx.iat[i]):.2f}")
                reason = "+".join(parts)

            trades.append(
                {
                    "trade_id": next_trade_id,
                    "side": "long",
                    "entry_bar_idx": i,
                    "entry_px": entry_px,
                    "entry_ts": e_ts,
                    "entry_dt": datetime.fromtimestamp(e_ts, tz=timezone.utc).isoformat(),
                    "entry_reason": reason,
                }
            )
            # trade_id назначаем на открытии, чтобы он сохранился даже при закрытии на последнем баре
            next_trade_id += 1

        elif pos and bool(long_off.iat[i]):
            # Закрытие позиции по сигналу
            exit_px = float(close[i])
            exit_ts = int(ts[i])
            pnl = float(exit_px - entry_px)

            bars_held = int(i - entry_i) if entry_i >= 0 else 0
            hold_seconds = int(exit_ts - int(ts[entry_i])) if entry_i >= 0 else 0

            reason = "exit_signal"
            if ema_fast is not None and ema_slow is not None and adx is not None:
                if ema_fast.iat[i] < ema_slow.iat[i]:
                    reason = "ema_cross_down"
                elif adx.iat[i] <= adx.iat[max(i - 1, 0)] and adx.iat[i] < 20:
                    reason = "weak_trend"
                elif adx.iat[i] <= 0:
                    reason = "adx_off"

            # обновляем последнюю открытую сделку (без exit_px)
            for j in range(len(trades) - 1, -1, -1):
                if "exit_px" not in trades[j]:
                    trades[j].update(
                        {
                            "exit_bar_idx": i,
                            "exit_px": exit_px,
                            "exit_ts": exit_ts,
                            "exit_dt": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
                            "exit_reason": reason,
                            "bars_held": bars_held,
                            "hold_seconds": hold_seconds,
                            "pnl": pnl,
                        }
                    )
                    break

            pos = False
            entry_px = 0.0
            entry_i = -1

    # Закрытие на последнем баре, если позиция осталась открытой
    if pos:
        i = n - 1
        exit_px = float(close[-1])
        exit_ts = int(ts[-1])
        pnl = float(exit_px - entry_px)

        bars_held = int(i - entry_i) if entry_i >= 0 else 0
        hold_seconds = int(exit_ts - int(ts[entry_i])) if entry_i >= 0 else 0

        for j in range(len(trades) - 1, -1, -1):
            if "exit_px" not in trades[j]:
                trades[j].update(
                    {
                        "exit_bar_idx": i,
                        "exit_px": exit_px,
                        "exit_ts": exit_ts,
                        "exit_dt": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
                        "exit_reason": "close_on_last_bar",
                        "bars_held": bars_held,
                        "hold_seconds": hold_seconds,
                        "pnl": pnl,
                    }
                )
                break

    # Вектор PnL только по закрытым сделкам
    pnls = np.asarray([t.get("pnl", 0.0) for t in trades if "pnl" in t], dtype=float)
    return trades, pnls
