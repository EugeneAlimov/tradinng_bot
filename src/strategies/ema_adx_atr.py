# src/strategies/ema_adx_atr.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

from src.indicators.atr import atr as atr_wilder
from src.strategies.ema_adx import signals as ema_adx_signals
from src.strategies.utils import build_trades_from_signals


def build_trades(df: pd.DataFrame, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    ema_adx_atr с поддержкой:
      - сигнального выхода ema/adx (как в ema_adx)
      - фиксированного SL/TP от ATR
      - трейлинг-стопа от ATR
      - частичной фиксации: TP1 (доля позиции) и опциональный TP2 по остатку

    Параметры:
      fast, slow, adx_len, on, off, require_di
      atr_len: int = 14
      sl_mult: float = 0.0        # 0 => выкл; SL = entry_px - sl_mult * ATR
      tp_mult: float = 0.0        # 0 => выкл; TP = entry_px + tp_mult * ATR (полный выход)
      trail_mult: float = 0.0     # 0 => выкл; trailing = HH_since_entry - trail_mult * ATR(i)

      # частичная фиксация:
      tp1_mult: float = 0.0       # 0 => выкл; TP1 = entry_px + tp1_mult * ATR (частичный выход)
      tp1_frac: float = 0.0       # доля позиции, которую фиксируем на TP1 (0..1)
      tp2_mult: float = 0.0       # 0 => выкл; TP2 = entry_px + tp2_mult * ATR (выход остатка)

    Приоритет на баре (для long) — консервативный:
      1) SL (включая трейлинг),
      2) TP/TP1/TP2,
      3) сигнальный выход (ema/adx).

    Журнал сделки дополняется полем:
      - qty_frac: доля позиции, закрытая в данной сделке (для частичных выходов).
    """
    if df.empty:
        return [], np.asarray([], dtype=float)

    # Разбор параметров
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 21))
    adx_len = int(params.get("adx_len", 14))
    on = float(params.get("on", 25.0))
    off = float(params.get("off", 16.0))
    require_di = bool(params.get("require_di", True))

    atr_len = int(params.get("atr_len", 14))
    sl_mult = float(params.get("sl_mult", 0.0))
    tp_mult = float(params.get("tp_mult", 0.0))
    trail_mult = float(params.get("trail_mult", 0.0))

    tp1_mult = float(params.get("tp1_mult", 0.0))
    tp1_frac = float(params.get("tp1_frac", 0.0))
    tp2_mult = float(params.get("tp2_mult", 0.0))

    # sanity для фракции
    if not (0.0 <= tp1_frac <= 1.0):
        tp1_frac = 0.0

    # Сигналы EMA+ADX
    long_on, long_off, ema_f, ema_s, adx = ema_adx_signals(
        df, fast=fast, slow=slow, adx_len=adx_len, on=on, off=off, require_di=require_di
    )

    # ATR для SL/TP/трейлинга
    atr_series = atr_wilder(df, atr_len).fillna(0.0)

    # Если все ATR-множители выключены и нет частичных TP — поведение = ema_adx
    partial_mode = (tp1_mult > 0.0 and 0.0 < tp1_frac < 1.0)
    if sl_mult <= 0.0 and tp_mult <= 0.0 and trail_mult <= 0.0 and not partial_mode and tp2_mult <= 0.0:
        return build_trades_from_signals(df, long_on, long_off, ema_fast=ema_f, ema_slow=ema_s, adx=adx)

    # --- Сборка сделок c SL/TP/Trailing/Partial ---
    close = df["close"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    ts = df["timestamp"].astype(int).to_numpy()
    atr_vals = atr_series.to_numpy()

    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []

    pos = False
    entry_px = 0.0
    entry_i = -1
    next_trade_id = 1

    # уровни
    sl_px: Optional[float] = None  # фиксированный SL от entry
    tp_px: Optional[float] = None  # фиксированный TP (полный выход)
    tr_px: Optional[float] = None  # трейлинговый SL
    hh_since_entry: float = float("-inf")

    # частичный TP
    tp1_px: Optional[float] = None
    tp2_px: Optional[float] = None
    took_tp1: bool = False
    remaining_frac: float = 1.0

    n = len(df)
    for i in range(n):
        if (not pos) and bool(long_on.iat[i]):
            # Открытие
            pos = True
            entry_px = float(close[i])
            entry_i = i
            e_ts = int(ts[i])

            atr_i = float(atr_vals[i])
            sl_px = entry_px - sl_mult * atr_i if sl_mult > 0.0 else None
            tp_px = entry_px + tp_mult * atr_i if tp_mult > 0.0 else None

            # трейлинг
            hh_since_entry = float(high[i])
            tr_px = None  # появится на следующем баре

            # partial
            if partial_mode:
                tp1_px = entry_px + tp1_mult * atr_i if tp1_mult > 0.0 else None
                tp2_px = entry_px + tp2_mult * atr_i if tp2_mult > 0.0 else None
                took_tp1 = False
                remaining_frac = 1.0
            else:
                tp1_px = None
                tp2_px = None
                took_tp1 = False
                remaining_frac = 1.0

            trades.append(
                {
                    "trade_id": next_trade_id,
                    "side": "long",
                    "entry_bar_idx": i,
                    "entry_px": entry_px,
                    "entry_ts": e_ts,
                    "entry_dt": pd.Timestamp(e_ts, unit="s", tz="UTC").isoformat(),
                    "entry_reason": "ema_adx_on",
                    # для полного выхода qty_frac поставим при закрытии; для частичного — в сделке TP1
                }
            )
            next_trade_id += 1

        elif pos:
            # Обновляем high-high и трейлинг
            hh_since_entry = max(hh_since_entry, float(high[i]))
            if trail_mult > 0.0:
                tr_candidate = hh_since_entry - trail_mult * float(atr_vals[i])
                tr_px = max(tr_px or tr_candidate, tr_candidate)

            # Проверка выходов
            exit_reason = None
            exit_px = None
            exit_frac = None  # какая доля закрывается этой сделкой (если частичный)

            # 1) SL (фиксированный) и Trailing SL — приоритет
            effective_sl_list: List[Tuple[str, float]] = []
            if sl_px is not None:
                effective_sl_list.append(("sl_hit", float(sl_px)))
            if tr_px is not None:
                effective_sl_list.append(("trail_hit", float(tr_px)))

            if effective_sl_list:
                best_name, best_px = max(effective_sl_list, key=lambda kv: kv[1])  # для long — максимальный порог
                if low[i] <= best_px:
                    exit_reason = best_name
                    exit_px = float(best_px)
                    exit_frac = remaining_frac  # всё, что осталось

            # 2) TP/Partial TP, если SL не сработал
            if exit_reason is None:
                if partial_mode:
                    # TP1 (если ещё не брали)
                    if (not took_tp1) and (tp1_px is not None) and high[i] >= tp1_px:
                        # закрываем долю tp1_frac
                        frac = max(0.0, min(tp1_frac, remaining_frac))
                        if frac > 0.0:
                            exit_reason = "tp1_hit"
                            exit_px = float(tp1_px)
                            exit_frac = frac
                            took_tp1 = True
                            remaining_frac = max(0.0, remaining_frac - frac)

                            # оформляем отдельную сделку (частичный выход)
                            exit_ts = int(ts[i])
                            bars_held = int(i - entry_i) if entry_i >= 0 else 0
                            hold_seconds = int(exit_ts - int(ts[entry_i])) if entry_i >= 0 else 0
                            pnl = float((exit_px - entry_px) * frac)

                            trades.append(
                                {
                                    "trade_id": next_trade_id,
                                    "side": "long",
                                    "entry_bar_idx": entry_i,
                                    "entry_px": entry_px,
                                    "entry_ts": int(ts[entry_i]),
                                    "entry_dt": pd.Timestamp(int(ts[entry_i]), unit="s", tz="UTC").isoformat(),
                                    "entry_reason": "ema_adx_on",
                                    "exit_bar_idx": i,
                                    "exit_px": exit_px,
                                    "exit_ts": exit_ts,
                                    "exit_dt": pd.Timestamp(exit_ts, unit="s", tz="UTC").isoformat(),
                                    "exit_reason": exit_reason,
                                    "bars_held": bars_held,
                                    "hold_seconds": hold_seconds,
                                    "pnl": pnl,
                                    "qty_frac": frac,
                                }
                            )
                            pnls.append(pnl)
                            next_trade_id += 1

                            # после частичной фиксации продолжаем проверять TP2 на том же баре
                            exit_reason = None
                            exit_px = None
                            exit_frac = None

                    # TP2 по остатку (если задан) — на том же баре
                    if exit_reason is None and (tp2_px is not None) and remaining_frac > 0.0 and high[i] >= tp2_px:
                        exit_reason = "tp2_hit"
                        exit_px = float(tp2_px)
                        exit_frac = remaining_frac  # остаток

                else:
                    # Обычный TP (полный выход)
                    if tp_px is not None and high[i] >= tp_px:
                        exit_reason = "tp_hit"
                        exit_px = float(tp_px)
                        exit_frac = remaining_frac

            # 3) сигнальный выход
            if exit_reason is None and bool(long_off.iat[i]):
                exit_reason = (
                    "ema_cross_down"
                    if ema_f.iat[i] < ema_s.iat[i]
                    else ("weak_trend" if (adx.iat[i] <= adx.iat[max(i - 1, 0)] and adx.iat[i] < 20) else "adx_off")
                )
                exit_px = float(close[i])
                exit_frac = remaining_frac

            # Закрытие позиции (полное) — когда exit_frac == остаток
            if exit_reason is not None and exit_px is not None and exit_frac is not None and exit_frac > 0.0:
                exit_ts = int(ts[i])
                bars_held = int(i - entry_i) if entry_i >= 0 else 0
                hold_seconds = int(exit_ts - int(ts[entry_i])) if entry_i >= 0 else 0
                pnl = float((exit_px - entry_px) * exit_frac)

                # обновляем исходную «основную» сделку (первая запись в списке без exit)
                for j in range(len(trades) - 1, -1, -1):
                    if "exit_px" not in trades[j] and trades[j].get("entry_bar_idx") == entry_i:
                        trades[j].update(
                            {
                                "exit_bar_idx": i,
                                "exit_px": exit_px,
                                "exit_ts": exit_ts,
                                "exit_dt": pd.Timestamp(exit_ts, unit="s", tz="UTC").isoformat(),
                                "exit_reason": exit_reason,
                                "bars_held": bars_held,
                                "hold_seconds": hold_seconds,
                                "pnl": pnl,
                                "qty_frac": exit_frac,
                            }
                        )
                        break

                pnls.append(pnl)
                pos = False
                entry_px = 0.0
                entry_i = -1
                sl_px = None
                tp_px = None
                tr_px = None
                hh_since_entry = float("-inf")
                tp1_px = None
                tp2_px = None
                took_tp1 = False
                remaining_frac = 1.0

    # Закрытие на последнем баре (если позиция осталась)
    if pos and remaining_frac > 0.0:
        i = n - 1
        exit_px = float(close[-1])
        exit_ts = int(ts[-1])
        bars_held = int(i - entry_i) if entry_i >= 0 else 0
        hold_seconds = int(exit_ts - int(ts[entry_i])) if entry_i >= 0 else 0
        pnl = float((exit_px - entry_px) * remaining_frac)

        for j in range(len(trades) - 1, -1, -1):
            if "exit_px" not in trades[j] and trades[j].get("entry_bar_idx") == entry_i:
                trades[j].update(
                    {
                        "exit_bar_idx": i,
                        "exit_px": exit_px,
                        "exit_ts": exit_ts,
                        "exit_dt": pd.Timestamp(exit_ts, unit="s", tz="UTC").isoformat(),
                        "exit_reason": "close_on_last_bar",
                        "bars_held": bars_held,
                        "hold_seconds": hold_seconds,
                        "pnl": pnl,
                        "qty_frac": remaining_frac,
                    }
                )
                break
        pnls.append(pnl)

    return trades, np.asarray(pnls, dtype=float)
