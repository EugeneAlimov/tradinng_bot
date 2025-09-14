# src/data/normalize.py
from __future__ import annotations
import pandas as pd
from typing import Iterable, Optional
from src.core.time import to_utc

_OHLCV = ("open", "high", "low", "close", "volume")


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    mapping = {}
    for name in _OHLCV:
        if name in df.columns:
            mapping[name] = name
        elif name in cols:
            mapping[cols[name]] = name
        else:
            raise ValueError(f"Missing required column: {name}")
    if mapping:
        df = df.rename(columns=mapping)
    return df


def normalize_ohlcv_df(
        df: pd.DataFrame,
        *,
        ts_col: Optional[str] = None,
        sort: bool = True,
) -> pd.DataFrame:
    """
    Normalize raw OHLCV to:
      - DatetimeIndex (UTC tz-aware) named 'time'
      - float dtype for ohlcv
      - sorted unique index
    If ts_col is None, try 'timestamp' or 'time' or index.
    """
    if ts_col is None:
        if "timestamp" in df.columns:
            ts_col = "timestamp"
        elif "time" in df.columns:
            ts_col = "time"

    if ts_col:
        ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        if ts.isna().any():
            # try epoch seconds
            ts = pd.to_datetime(df[ts_col].astype("int64"), unit="s", utc=True, errors="coerce")
        df = df.drop(columns=[ts_col]).copy()
        df.index = ts
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("No timestamp column and index is not DatetimeIndex")

    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    df.index.name = "time"

    df = _ensure_columns(df)
    for c in _OHLCV:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=list(_OHLCV))
    if sort:
        df = df[~df.index.duplicated()].sort_index()
    return df
