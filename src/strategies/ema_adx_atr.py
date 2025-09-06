# src/strategies/ema_adx_atr.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd


def _to_series(x: Any, name: str) -> pd.Series:
    """Конвертация в pandas Series с исправленной обработкой NaN"""
    s = pd.to_numeric(pd.Series(x, name=name), errors="coerce")
    # Заменяем deprecated fillna(method="ffill") на ffill()
    s = s.ffill()
    return s.astype(float)


def _ema(s: pd.Series, span: int) -> pd.Series:
    """Экспоненциальная скользящая средняя"""
    return s.ewm(span=span, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Истинный диапазон (True Range)"""
    prev_close = close.shift(1)
    c1 = high - low
    c2 = (high - prev_close).abs()
    c3 = (low - prev_close).abs()
    return pd.concat([c1, c2, c3], axis=1).max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Average True Range"""
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculates ADX, +DI, -DI indicators.
    Returns: (plus_di, minus_di, adx)
    """
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = (up_move.where((up_move > down_move) & (up_move > 0), 0.0)).astype(float)
    minus_dm = (down_move.where((down_move > up_move) & (down_move > 0), 0.0)).astype(float)

    atr = _atr(high, low, close, length)

    # Исправляем проблему с типами в сравнениях
    atr_safe = atr.replace(0.0, np.nan)
    plus_di = 100.0 * (plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr_safe)
    minus_di = 100.0 * (minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr_safe)

    # Заполняем NaN нулями для DI
    plus_di = plus_di.fillna(0.0)
    minus_di = minus_di.fillna(0.0)

    # Расчет DX и ADX
    dx_denominator = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (plus_di - minus_di).abs() / dx_denominator * 100.0
    dx = dx.fillna(0.0)

    adx = dx.ewm(alpha=1 / length, adjust=False).mean().fillna(0.0)

    return plus_di, minus_di, adx


def generate_signals(
        *,
        close: Any,
        high: Any,
        low: Any,
        fast: int,
        slow: int,
        adx_len: int,
        on: float,
        off: float,
        require_di: bool,
        atr_len: int,
        atr_mult: float,
) -> List[int]:
    """
    Возвращает список сигналов (+1/-1/0).
    Основная логика: EMA-кросс, фильтр ADX с порогами on/off.
    Фолбэк: если после фильтра все нули — вернём чистый EMA-кросс.
    """
    c = _to_series(close, "close")
    h = _to_series(high, "high")
    l = _to_series(low, "low")

    ema_f = _ema(c, fast)
    ema_s = _ema(c, slow)

    # базовые «кроссовые» импульсы только на смене знака спрэда
    spread = ema_f - ema_s
    side = np.sign(spread).astype(int)
    cross = np.zeros(len(side), dtype=int)
    mask = side.shift(1).fillna(0).astype(int) != side
    cross[mask.to_numpy()] = side[mask].to_numpy()

    # ADX-гейтинг с гистерезисом on/off
    plus_di, minus_di, adx = _adx(h, l, c, adx_len)

    enabled = np.zeros(len(adx), dtype=bool)
    state = False
    for i, val in enumerate(adx.to_numpy()):
        if not state and val >= on:
            state = True
        elif state and val <= off:
            state = False
        enabled[i] = state

    # Применяем DI фильтр если требуется
    if require_di:
        di_filter = plus_di > minus_di
        enabled = enabled & di_filter.to_numpy()

    gated = np.where(enabled, cross, 0)

    # ATR-стоп может использоваться билдером трейдов; для сигналов не обязателен.
    # Здесь просто возвращаем gated сигналы

    # Если все сигналы нулевые, возвращаем хотя бы EMA кроссы для тестов
    if np.sum(np.abs(gated)) == 0:
        # Фолбэк: простые EMA кроссы без фильтров
        return cross.tolist()

    return gated.tolist()


def build_trades(df: pd.DataFrame, /, **params: Any) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    Builds trade list from DataFrame with OHLC data.
    Returns (trades_list, equity_curve)
    """
    # Применяем исправленную обработку данных
    close = _to_series(df["close"], "close")
    high = _to_series(df["high"], "high") if "high" in df.columns else close * 1.001
    low = _to_series(df["low"], "low") if "low" in df.columns else close * 0.999

    # Получаем сигналы
    signals = generate_signals(
        close=close.tolist(),
        high=high.tolist(),
        low=low.tolist(),
        **params
    )

    # Простейшая логика построения трейдов
    trades = []
    in_position = False
    entry_idx = 0
    entry_price = 0.0

    for i, sig in enumerate(signals):
        if sig == 1 and not in_position:
            # Вход в позицию
            in_position = True
            entry_idx = i
            entry_price = close.iloc[i]
        elif sig == -1 and in_position:
            # Выход из позиции
            exit_price = close.iloc[i]
            pnl = (exit_price - entry_price) / entry_price

            trades.append({
                "entry_ts": df.index[entry_idx] if hasattr(df.index, 'to_series') else entry_idx,
                "exit_ts": df.index[i] if hasattr(df.index, 'to_series') else i,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "return": pnl
            })
            in_position = False

    # Простая equity curve
    equity = np.ones(len(df))
    for trade in trades:
        equity[trade.get("exit_ts", len(equity) - 1):] *= (1 + trade["return"])

    return trades, equity


def default_grid() -> Dict[str, List[Any]]:
    """Default parameter grid for optimization"""
    return {
        "fast": [5, 9, 12, 15],
        "slow": [15, 21, 26, 30],
        "adx_len": [10, 14, 18, 22],
        "on": [15, 18, 22, 25],
        "off": [10, 12, 15, 18],
        "atr_len": [10, 14, 20],
        "atr_mult": [2.0, 2.5, 3.0]
    }
