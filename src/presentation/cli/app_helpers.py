# src/presentation/cli/app_helpers.py
from __future__ import annotations

from typing import Any, Optional


def as_int_or_none(value: Any) -> Optional[int]:
    """
    Безопасно приводит к int:
      - None, "" → None
      - "0" → 0
      - 0 → 0
      - "  15  " → 15
    Бросает ValueError только если значение непустое и непереводимое.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):  # защита от NaN/инф
        if value != value:  # NaN
            return None
        return int(value)
    if isinstance(value, (bytes, bytearray)):
        s = value.decode("utf-8", errors="ignore").strip()
        return int(s) if s else None
    s = str(value).strip()
    return int(s) if s else None


def as_float_or_none(value: Any) -> Optional[float]:
    """
    Аналогично as_int_or_none, но для float.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        s = value.decode("utf-8", errors="ignore").strip()
        return float(s) if s else None
    s = str(value).strip()
    return float(s) if s else None


def pct01_or_none(value: Any) -> Optional[float]:
    """
    Процент как доля (0..1). Принимает:
      - 0.25 → 0.25
      - "0.25" → 0.25
      - 25 → 0.25 (если нужно трактовать как %, меняется логика — здесь оставляем долю)
    Сейчас интерпретируем как долю, чтобы не путать 25% и 0.25.
    """
    f = as_float_or_none(value)
    if f is None:
        return None
    if f < 0:
        return None
    return f


def bps_or_none(value: Any) -> Optional[int]:
    """
    Бейзисные пункты как int:
      - 10 → 10
      - "10" → 10
      - None/"" → None
    """
    i = as_int_or_none(value)
    if i is None:
        return None
    if i < 0:
        return None
    return i
