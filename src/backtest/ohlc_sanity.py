# src/backtest/ohlc_sanity.py
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

_MIN_COLS = ("timestamp", "open", "high", "low", "close")


def sanity_check_ohlc(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Базовый sanity-чек входного OHLC:
      - наличие минимального набора колонок
      - числовые типы и очистка NaN
      - сортировка по времени
      - удаление дубликатов таймштампов
      - корректность high/low относительно open/close (только мягкие правки)
    Возвращает (очищенный DataFrame, список предупреждений).
    На пустых/битых данных не падает — вернёт пустой DataFrame.
    """
    warns: List[str] = []

    if df is None or df.empty:
        return pd.DataFrame(columns=_MIN_COLS), ["ohlc: empty dataframe"]

    missing = [c for c in _MIN_COLS if c not in df.columns]
    if missing:
        warns.append(f"ohlc: missing columns: {missing}")
        return pd.DataFrame(columns=_MIN_COLS), warns

    out = df.copy()

    # Типы и NaN
    out["timestamp"] = pd.to_numeric(out["timestamp"], errors="coerce").astype("Int64")
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    before = len(out)
    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"])
    dropped = before - len(out)
    if dropped > 0:
        warns.append(f"ohlc: dropped {dropped} rows with NaN in OHLC")

    # Сортировка по времени
    if not out["timestamp"].is_monotonic_increasing:
        out = out.sort_values("timestamp").reset_index(drop=True)
        warns.append("ohlc: timestamps were not monotonic, sorted ascending")

    # Дубликаты таймштампов
    dup_mask = out["timestamp"].duplicated(keep="last")
    dup_count = int(dup_mask.sum())
    if dup_count > 0:
        out = out.loc[~dup_mask].reset_index(drop=True)
        warns.append(f"ohlc: removed {dup_count} duplicated timestamps (kept last)")

    # Мягкая корректировка high/low относительно open/close
    # high >= max(open, close); low <= min(open, close); и high >= low
    hi_ref = np.maximum(out["open"].values, out["close"].values)
    lo_ref = np.minimum(out["open"].values, out["close"].values)

    hi_new = np.maximum(out["high"].values, hi_ref)
    lo_new = np.minimum(out["low"].values, lo_ref)

    # high >= low
    lo_new = np.minimum(lo_new, hi_new)

    hi_changed = int(np.count_nonzero(hi_new != out["high"].to_numpy()))
    lo_changed = int(np.count_nonzero(lo_new != out["low"].to_numpy()))
    if hi_changed or lo_changed:
        warns.append(f"ohlc: adjusted {hi_changed} high and {lo_changed} low values to envelope open/close")

    out["high"] = hi_new
    out["low"] = lo_new

    # Приводим timestamp к int64 для совместимости downstream
    out["timestamp"] = out["timestamp"].astype("int64")

    # Переупорядочим колонки (минимальный набор впереди)
    front = [c for c in _MIN_COLS if c in out.columns]
    tail = [c for c in out.columns if c not in front]
    out = out.loc[:, front + tail]

    return out, warns
