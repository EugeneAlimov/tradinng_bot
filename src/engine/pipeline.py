# src/engine/pipeline.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd
from src.core.types import Signal


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def ema_crossover_signal(df: pd.DataFrame, *, fast: int = 10, slow: int = 20) -> Signal:
    close = pd.to_numeric(df["close"], errors="coerce")
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    if len(close) == 0 or pd.isna(ema_fast.iloc[-1]) or pd.isna(ema_slow.iloc[-1]):
        return Signal(side="FLAT", indicators={"ema_fast": float("nan"), "ema_slow": float("nan")})
    side = "LONG" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "SHORT"
    return Signal(side=side, indicators={"ema_fast": float(ema_fast.iloc[-1]), "ema_slow": float(ema_slow.iloc[-1])})


@dataclass
class Pipeline:
    """
    Minimal pipeline placeholder (observe-mode).
    Later we'll plug risk, sizing and brokers here.
    """
    strategy: str = "ema_crossover"
    params: Optional[Dict[str, Any]] = None

    def on_df(self, df: pd.DataFrame) -> Signal:
        p = self.params or {}
        # right now only built-in minimal strategy is wired;
        # real strategies will be plugged via registry in the next iterations
        if self.strategy == "ema_crossover":
            return ema_crossover_signal(df, **{k: v for k, v in p.items() if k in ("fast", "slow")})
        # fallback to flat
        return Signal(side="FLAT")
