# src/data/interfaces.py
from __future__ import annotations
from typing import Iterator, Protocol, Optional
import pandas as pd
from src.core.types import Bar


class IDataSource(Protocol):
    def fetch(self, *, pair: Optional[str] = None, span: Optional[str] = None,
              path: Optional[str] = None) -> pd.DataFrame:
        """Return OHLCV DataFrame with UTC DatetimeIndex and columns: open, high, low, close, volume."""
        ...

    def stream(self, *, pair: Optional[str] = None, freq: str = "1min") -> Iterator[Bar]:
        """Yield bars in real time (optional for offline sources)."""
        ...


class IResampler(Protocol):
    def resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        ...
