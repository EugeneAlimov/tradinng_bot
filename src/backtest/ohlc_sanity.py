from __future__ import annotations

import logging
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def sanity_check_ohlc(
        df: pd.DataFrame,
        required: Iterable[str] = ("timestamp", "open", "high", "low", "close"),
        allow_volume: bool = True,
        sort: bool = True,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Базовая проверка входных свечей:
    - наличие обязательных колонок
    - сортировка по времени по возрастанию
    - удаление дубликатов таймстемпов
    - проверка диапазонов (high >= open/close/low; low <= open/close/high)
    - NaN: не удаляем, а предупреждаем (обработка на стороне стратегий/загрузчика)

    Возвращает (исправленный_df, warnings)
    """
    warnings: List[str] = []

    cols = list(required)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        warnings.append(f"Missing required OHLC columns: {missing}")
        # добавим недостающие колонки NaN, чтобы дальше не падать
        for c in missing:
            df[c] = np.nan

    # Отсортируем
    if sort and "timestamp" in df.columns:
        if not df["timestamp"].is_monotonic_increasing:
            df = df.sort_values("timestamp", ascending=True)

    # Удалим дубликаты таймстемпов, оставляя последний
    if "timestamp" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        if len(df) != before:
            warnings.append(f"Dropped {before - len(df)} duplicate rows by timestamp")

    # Диапазоны
    for idx, row in df.iterrows():
        hi = row.get("high", np.nan)
        lo = row.get("low", np.nan)
        o = row.get("open", np.nan)
        c = row.get("close", np.nan)
        if pd.isna(hi) or pd.isna(lo) or pd.isna(o) or pd.isna(c):
            continue
        bad_hi = hi < max(o, c, lo)
        bad_lo = lo > min(o, c, hi)
        if bad_hi or bad_lo:
            warnings.append(f"Row {idx} has inconsistent OHLC: {row.to_dict()}")
            # минимально валидное исправление
            hi2 = max(hi, o, c, lo)
            lo2 = min(lo, o, c, hi)
            df.at[idx, "high"] = hi2
            df.at[idx, "low"] = lo2

    # Объем необязателен
    if allow_volume and "volume" not in df.columns:
        df["volume"] = np.nan

    return df.reset_index(drop=True), warnings
