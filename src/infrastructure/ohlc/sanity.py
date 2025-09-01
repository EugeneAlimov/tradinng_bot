# src/infrastructure/ohlc/sanity.py
from __future__ import annotations

from typing import Any, Dict, Tuple, List
import numpy as np
import pandas as pd

REQUIRED_COLS: List[str] = ["timestamp", "open", "high", "low", "close", "volume"]


def _detect_ts_unit(ts: pd.Series) -> Tuple[str, int]:
    """
    Грубая эвристика по масштабу:
      ns  ~ 1e18
      us  ~ 1e15
      ms  ~ 1e12
      s   ~ 1e9
    Возвращает (unit_name, divisor), где divisor — во что делить, чтобы получить секунды.
    """
    med = float(pd.to_numeric(ts, errors="coerce").dropna().median()) if len(ts) else 0.0
    if med > 1e18:
        return "ns", 10 ** 9
    if med > 1e15:
        return "us", 10 ** 6
    if med > 1e12:
        return "ms", 10 ** 3
    return "s", 1


def clean_ohlc(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Приводит OHLC к безопасному виду:
      - проверяет наличие REQUIRED_COLS;
      - приводит к float/int, убирает нечисловые;
      - сортирует по timestamp (возрастающе);
      - удаляет дубликаты по timestamp (оставляет последний);
      - нормализует единицы времени к секундам (если приходят ms/us/ns);
      - создаёт колонку dt (UTC).
    Возвращает (df_clean, report).
    На ошибках — безопасно возвращает пустой DataFrame c REQUIRED_COLS+["dt"].
    """
    report: Dict[str, Any] = {"ok": True}

    if df is None or df.empty:
        empty = pd.DataFrame(columns=REQUIRED_COLS + ["dt"])
        report.update({"ok": True, "reason": "empty_input"})
        return empty, report

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        empty = pd.DataFrame(columns=REQUIRED_COLS + ["dt"])
        report.update({"ok": False, "error": "missing_columns", "missing": missing})
        return empty, report

    work = df.copy()

    # Приводим типы
    for c in REQUIRED_COLS:
        work[c] = pd.to_numeric(work[c], errors="coerce")

    # Удаляем строки с NaN в базовых колонках
    before = int(work.shape[0])
    mask = work[REQUIRED_COLS].apply(np.isfinite).all(axis=1)
    work = work.loc[mask].copy()
    dropped_nonfinite = before - int(work.shape[0])

    # Нормализация единиц времени к секундам
    unit, div = _detect_ts_unit(work["timestamp"])
    if div != 1:
        work["timestamp"] = (work["timestamp"] / div).astype("int64")

    # Сортировка + дубликаты
    was_sorted = bool(work["timestamp"].is_monotonic_increasing)
    work = work.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    dup_cnt = int(work["timestamp"].duplicated(keep="last").sum())
    if dup_cnt:
        work = work.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    # dt (UTC)
    try:
        work["dt"] = pd.to_datetime(work["timestamp"].astype("int64"), unit="s", utc=True)
    except Exception:
        # что-то совсем не так с диапазоном — сдаёмся
        empty = pd.DataFrame(columns=REQUIRED_COLS + ["dt"])
        report.update({"ok": False, "error": "datetime_out_of_bounds"})
        return empty, report

    # На всякий — перетипизируем числовые столбцы
    for c in ["open", "high", "low", "close", "volume"]:
        work[c] = work[c].astype("float64")

    report.update(
        {
            "ok": True,
            "dropped_nonfinite": dropped_nonfinite,
            "duplicates_removed": dup_cnt,
            "was_sorted": was_sorted,
            "ts_unit_detected": unit,
        }
    )
    return work, report
