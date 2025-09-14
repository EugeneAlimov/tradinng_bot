# src/data/csv_source.py
from __future__ import annotations
from typing import Optional, Iterator
import pandas as pd
from src.core.types import Bar
from .normalize import normalize_ohlcv_df


class CsvSource:
    def __init__(self, path: str):
        self.path = path

    def fetch(self, *, pair: Optional[str] = None, span: Optional[str] = None,
              path: Optional[str] = None) -> pd.DataFrame:
        p = path or self.path
        df = pd.read_csv(p)
        return normalize_ohlcv_df(df)

    def stream(self, *, pair: Optional[str] = None, freq: str = "1min") -> Iterator[Bar]:
        df = self.fetch()
        for t, row in df.iterrows():
            yield Bar(time=t, open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                      volume=row["volume"])
