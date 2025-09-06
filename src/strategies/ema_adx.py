# src/strategies/ema_adx.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd


# простые индикаторы (без внешних зависимостей)
def _ema(s: pd.Series, n: int) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").ewm(span=max(1, int(n)), adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    length = max(1, int(length))
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = _true_range(high, low, close)
    atr = tr.rolling(length).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / length, adjust=False).mean()
    return adx.fillna(0.0)


name = "ema_adx"


def generate_signals(
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        fast: int = 12,
        slow: int = 21,
        adx_len: int = 14,
        on: float = 23.0,
        off: float = 17.0,
        require_di: bool = True,
) -> List[int]:
    close = pd.to_numeric(close, errors="coerce").fillna(method="ffill")
    high = pd.to_numeric(high, errors="coerce").fillna(method="ffill")
    low = pd.to_numeric(low, errors="coerce").fillna(method="ffill")

    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    adx = _adx(high, low, close, adx_len)

    sig = np.zeros(len(close), dtype=int)
    long_on = (ema_f > ema_s) & (adx >= on)
    long_off = (ema_f <= ema_s) | (adx <= off)

    in_pos = False
    for i in range(len(close)):
        if not in_pos and bool(long_on.iloc[i]):
            sig[i] = 1
            in_pos = True
        elif in_pos and bool(long_off.iloc[i]):
            sig[i] = -1
            in_pos = False
        else:
            sig[i] = 0
    return list(map(int, sig))


def build_trades(
        df: pd.DataFrame,
        params: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]:
    """Совместимый контракт: вернуть (trades, pnls, extra)."""
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 21))
    adx_len = int(params.get("adx_len", 14))
    on = float(params.get("on", 23.0))
    off = float(params.get("off", 17.0))
    require_di = bool(params.get("require_di", True))

    sig = generate_signals(
        close=df["close"], high=df["high"], low=df["low"],
        fast=fast, slow=slow, adx_len=adx_len, on=on, off=off, require_di=require_di,
    )
    # на коленке: PnL = разница закрытия между enter/exit
    close = pd.to_numeric(df["close"], errors="coerce").fillna(method="ffill").to_numpy(float)
    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []
    entry_px = None
    for i, s in enumerate(sig):
        if s == 1 and entry_px is None:
            entry_px = float(close[i])
        elif s == -1 and entry_px is not None:
            pnl = float(close[i] - entry_px)
            trades.append({"enter_i": i, "exit_i": i, "pnl": pnl})
            pnls.append(pnl)
            entry_px = None

    extra = {
        "ema_fast": _ema(pd.Series(close), fast),
        "ema_slow": _ema(pd.Series(close), slow),
        "adx": _adx(pd.Series(df["high"]), pd.Series(df["low"]), pd.Series(close), adx_len),
    }
    return trades, np.asarray(pnls, dtype=float), extra


# backtest.registry ожидает .build()
build = build_trades
