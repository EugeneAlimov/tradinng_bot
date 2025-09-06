# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.indicators.ema import ema
from src.indicators.adx import compute_adx
from src.strategies.utils import build_trades_from_signals

name = "ema_adx"


def signals(
        df: pd.DataFrame,
        *,
        fast: int = 12,
        slow: int = 26,
        adx_len: int = 14,
        on: float = 20.0,
        off: float = 14.0,
        require_di: bool = False,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Возвращает:
      long_on, long_off, ema_fast, ema_slow, adx_series  (все Series одинаковой длины)
    """
    close = df["close"]
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)

    adx_series, pdi, mdi = compute_adx(df, adx_len)

    trend_up = ema_fast > ema_slow
    strong = adx_series >= on
    weak = adx_series <= off

    if require_di:
        di_filter = pdi > mdi
        trend_up = trend_up & di_filter

    long_on = (trend_up & strong).fillna(False)
    long_off = ((~trend_up) | weak).fillna(False)

    idx = df.index
    long_on = long_on.reindex(idx, fill_value=False)
    long_off = long_off.reindex(idx, fill_value=False)
    ema_fast = ema_fast.reindex(idx)
    ema_slow = ema_slow.reindex(idx)
    adx_series = adx_series.reindex(idx)

    return long_on, long_off, ema_fast, ema_slow, adx_series


def build(
        df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]:
    """
    Унифицированный build: возвращает (trades, pnl, extra)
    """
    fees_bps: float = float(params.get("fees_bps", 0.0))
    slippage_bps: float = float(params.get("slippage_bps", 0.0))
    size: float = float(params.get("size", 100.0))
    sl_mult: float = float(params.get("sl_mult", 0.0))
    tp_mult: float = float(params.get("tp_mult", 0.0))
    trail_mult: float = float(params.get("trail_mult", 0.0))

    allowed = {"fast", "slow", "adx_len", "on", "off", "require_di"}
    sig_cfg = {k: params[k] for k in allowed if k in params}

    long_on, long_off, ema_f, ema_s, adx_s = signals(df, **sig_cfg)

    trades, pnls = build_trades_from_signals(
        df=df,
        long_on=long_on,
        long_off=long_off,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        size=size,
        sl_mult=sl_mult,
        tp_mult=tp_mult,
        trail_mult=trail_mult,
        vol_series=None,
    )

    extra = {
        "ema_fast": ema_f,
        "ema_slow": ema_s,
        "adx": adx_s,
    }
    return trades, pnls, extra
