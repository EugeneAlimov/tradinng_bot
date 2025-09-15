# src/utils/timefmt.py
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Union

CANONICAL_FMT = "%Y-%m-%dT%H:%M:%S%z"  # e.g. 2025-09-14T16:15:00+0000
_TZ_RE = re.compile(r"([+-]\d{2}):(\d{2})$")  # "+hh:mm" -> "+hhmm"


def to_utc_str(dt_or_str: Union[datetime, str]) -> str:
    """
    Вернёт строку времени в едином формате UTC ISO-8601 без двоеточия в офсете:
      YYYY-MM-DDTHH:MM:SS+0000

    Принимает: datetime (naive/aware) или строку ISO (в т.ч. с 'Z' и '+hh:mm').
    """
    dt: datetime
    if isinstance(dt_or_str, str):
        s = dt_or_str.strip().replace("Z", "+00:00")
        s = _TZ_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}", s)
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            # Если строка уже в нужном виде или нестандартная — вернём как есть
            return s
    else:
        dt = dt_or_str

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    dt = dt.replace(microsecond=0)
    return dt.strftime(CANONICAL_FMT)
