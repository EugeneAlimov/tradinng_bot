# src/core/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, Literal, Optional
import pandas as pd

Side = Literal["LONG", "SHORT", "FLAT"]


@dataclass(frozen=True)
class Bar:
    time: pd.Timestamp  # tz-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    side: Side
    strength: float = 1.0
    price: Optional[float] = None
    indicators: Dict[str, float] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
