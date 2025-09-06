# src/strategies/ema_adx.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Экспоненциальная скользящая средняя"""
    return series.ewm(span=max(2, period), adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range calculation"""
    prev_close = close.shift(1)
    c1 = high - low
    c2 = (high - prev_close).abs()
    c3 = (low - prev_close).abs()
    return pd.concat([c1, c2, c3], axis=1).max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Average True Range"""
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


# src/strategies/ema_adx.py - полная замена функции _adx

def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """ADX calculation with clean index handling"""
    # Сбрасываем индексы для избежания проблем с типами
    high = high.reset_index(drop=True).astype(float)
    low = low.reset_index(drop=True).astype(float)
    close = close.reset_index(drop=True).astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    # Теперь все операции с чистым RangeIndex
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Пересчитываем ATR с теми же сброшенными индексами
    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()
    atr_safe = atr.replace(0.0, np.nan)

    plus_di_raw = plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr_safe
    minus_di_raw = minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr_safe

    plus_di = (100.0 * plus_di_raw).fillna(0.0)
    minus_di = (100.0 * minus_di_raw).fillna(0.0)

    dx_denominator = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (plus_di - minus_di).abs() / dx_denominator * 100.0
    dx = dx.fillna(0.0)

    adx = dx.ewm(alpha=1 / length, adjust=False).mean().fillna(0.0)
    return adx


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
    """Generate EMA+ADX signals"""

    # Исправляем deprecated методы
    close = pd.to_numeric(close, errors="coerce").ffill()
    high = pd.to_numeric(high, errors="coerce").ffill()
    low = pd.to_numeric(low, errors="coerce").ffill()

    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    adx = _adx(high, low, close, adx_len)

    # Простые EMA кроссы
    spread = ema_fast - ema_slow
    side = np.sign(spread).astype(int)

    # Детекция кроссов
    signals = np.zeros(len(close), dtype=int)
    prev_side = side.shift(1).fillna(0).astype(int)

    # Кросс вверх
    cross_up = (prev_side <= 0) & (side > 0)
    # Кросс вниз
    cross_down = (prev_side >= 0) & (side < 0)

    # ADX фильтр с гистерезисом
    adx_state = np.zeros(len(adx), dtype=bool)
    current_state = False

    for i, adx_val in enumerate(adx):
        if not current_state and adx_val >= on:
            current_state = True
        elif current_state and adx_val <= off:
            current_state = False
        adx_state[i] = current_state

    # Применяем сигналы
    signals[cross_up & adx_state] = 1
    signals[cross_down] = -1  # Выход всегда разрешен

    return signals.tolist()


def build_trades(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]:
    """Build trades from EMA+ADX strategy"""

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

    # Исправляем deprecated метод
    close = pd.to_numeric(df["close"], errors="coerce").ffill().to_numpy(float)

    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []
    entry_px = None
    entry_i = None

    for i, s in enumerate(sig):
        if s == 1 and entry_px is None:
            entry_px = float(close[i])
            entry_i = i
        elif s == -1 and entry_px is not None:
            exit_px = float(close[i])
            pnl = exit_px - entry_px
            ret = pnl / entry_px if entry_px != 0 else 0.0

            trades.append({
                "enter_i": entry_i,
                "exit_i": i,
                "entry_price": entry_px,
                "exit_price": exit_px,
                "pnl": pnl,
                "return": ret
            })
            pnls.append(pnl)
            entry_px = None
            entry_i = None

    extra = {
        "ema_fast": _ema(pd.Series(close), fast),
        "ema_slow": _ema(pd.Series(close), slow),
        "adx": _adx(pd.Series(df["high"]), pd.Series(df["low"]), pd.Series(close), adx_len),
        "signals": sig
    }

    return trades, np.asarray(pnls, dtype=float), extra


# backtest.registry ожидает .build()
build = build_trades

# Для совместимости
name = "ema_adx"
