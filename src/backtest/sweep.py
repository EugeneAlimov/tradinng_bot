# src/backtest/sweep.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd


@dataclass(frozen=True)
class SweepCfg:
    metric: str = "sharpe"
    resample: str = "5min"
    top_n: int = 10


def normalize_resample_rule(rule: str) -> str:
    r = (rule or "").strip().lower()
    if not r:
        return "5min"
    if r.endswith("m"):
        return f"{int(r[:-1])}min"
    if r.endswith("h"):
        return f"{int(r[:-1])}H"
    if r.endswith("d"):
        return f"{int(r[:-1])}D"
    return r


def _normalize_resample_rule(rule: str) -> str:  # compat alias
    return normalize_resample_rule(rule)


def resample_ohlc(df: Any, rule: str) -> pd.DataFrame:
    """Минимальный ресемплинг для тестов: поддержка Series/DF с колонкой close или OHLCV."""
    rr = normalize_resample_rule(rule)
    if isinstance(df, pd.Series):
        s = pd.to_numeric(df, errors="coerce")
        out = s.resample(rr).last().to_frame("close").dropna()
        return out
    if isinstance(df, pd.DataFrame):
        cols = set(df.columns)
        if {"open", "high", "low", "close", "volume"}.issubset(cols):
            agg = {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
            return df.resample(rr).agg(agg).dropna(how="all")
        if "close" in cols:
            s = pd.to_numeric(df["close"], errors="coerce")
            return s.resample(rr).last().to_frame("close").dropna()
    raise TypeError("resample_ohlc: unsupported input type")


def _resample_ohlc(df: Any, rule: str) -> pd.DataFrame:  # compat alias
    return resample_ohlc(df, rule)


# ---- new: safe stub so import works in tests ----
def run_sweep(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Заглушка: возвращает пустой список результатов sweep."""
    return []
