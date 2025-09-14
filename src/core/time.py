# src/core/time.py
from __future__ import annotations
from typing import Union
import pandas as pd
import numpy as np


def to_utc(ts: Union[int, float, str, pd.Timestamp]) -> pd.Timestamp:
    """
    Normalize any timestamp to tz-aware UTC pandas.Timestamp.
    - int/float -> epoch seconds
    - str -> parsed by pandas (assumed UTC if no tz)
    - Timestamp -> localized to UTC if naive
    """
    if isinstance(ts, pd.Timestamp):
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if isinstance(ts, (int, float, np.integer, np.floating)):
        return pd.to_datetime(ts, unit="s", utc=True)
    # string
    out = pd.to_datetime(ts, utc=True, errors="coerce")
    if not isinstance(out, pd.Timestamp) or pd.isna(out):
        raise ValueError(f"Cannot parse timestamp: {ts}")
    return out
