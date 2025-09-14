# src/data/cache.py
from __future__ import annotations
import os
from pathlib import Path
import pandas as pd
from .normalize import normalize_ohlcv_df

_DEFAULT_ROOT = Path(".cache/ohlcv")


def cache_path(*, vendor: str, pair: str, span: str) -> Path:
    # span '1m:5000' -> '1m_5000'
    safe_span = span.replace(":", "_")
    return _DEFAULT_ROOT / vendor / pair / f"{safe_span}.parquet"


def load_cached(*, vendor: str, pair: str, span: str) -> pd.DataFrame:
    p = cache_path(vendor=vendor, pair=pair, span=span)
    if not p.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.read_parquet(p)
    return normalize_ohlcv_df(df)


def save_cache(df: pd.DataFrame, *, vendor: str, pair: str, span: str) -> None:
    p = cache_path(vendor=vendor, pair=pair, span=span)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.reset_index().to_parquet(p, index=False)
