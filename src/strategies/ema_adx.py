# src/strategies/ema_adx.py - Исправленная версия
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Tuple


def _to_series(data, name: str) -> pd.Series:
    """Конвертирует в pandas Series с валидацией"""
    if isinstance(data, pd.Series):
        return data
    return pd.Series(data, name=name)


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average"""
    return series.ewm(span=period).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Simplified ADX calculation"""
    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    # Directional Indicators
    plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / tr.rolling(period).mean()
    minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / tr.rolling(period).mean()

    # ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(period).mean()

    return adx.fillna(0)


def generate_signals(
        close, high, low, *,
        fast: int = 12,
        slow: int = 21,
        adx_len: int = 14,
        on: float = 23.0,
        off: float = 17.0,
        require_di: bool = True
) -> List[int]:
    """
    Генерирует торговые сигналы на основе EMA кроссовера и ADX фильтра

    Returns:
        List[int]: Массив сигналов (1=buy, -1=sell, 0=hold)
    """
    c = _to_series(close, "close")
    h = _to_series(high, "high")
    l = _to_series(low, "low")

    # EMA расчеты
    ema_fast = _ema(c, fast)
    ema_slow = _ema(c, slow)

    # Кроссоверы
    signal = np.zeros(len(c), dtype=int)
    prev_fast = ema_fast.shift(1)
    prev_slow = ema_slow.shift(1)

    # Bullish crossover: fast EMA crosses above slow EMA
    bullish = (ema_fast > ema_slow) & (prev_fast <= prev_slow)
    # Bearish crossover: fast EMA crosses below slow EMA
    bearish = (ema_fast < ema_slow) & (prev_fast >= prev_slow)

    signal[bullish] = 1
    signal[bearish] = -1

    # ADX фильтр
    adx = _adx(h, l, c, adx_len)

    # Применяем ADX фильтр с гистерезисом
    filtered_signal = np.zeros_like(signal)
    in_trend = False

    for i in range(len(signal)):
        current_adx = adx.iloc[i] if i < len(adx) else 0

        # Включаем тренд если ADX превышает порог "on"
        if not in_trend and current_adx >= on:
            in_trend = True
        # Выключаем тренд если ADX падает ниже порога "off"
        elif in_trend and current_adx <= off:
            in_trend = False

        # Пропускаем сигналы только если находимся в тренде
        if in_trend:
            filtered_signal[i] = signal[i]

    return filtered_signal.tolist()


def build_trades(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], np.ndarray, Dict[str, Any]]:
    """
    Строит список трейдов из DataFrame с OHLC данными

    Args:
        df: DataFrame с колонками open, high, low, close
        params: Параметры стратегии

    Returns:
        Tuple[trades, pnls, extra_data]
    """
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 21))
    adx_len = int(params.get("adx_len", 14))
    on = float(params.get("on", 23.0))
    off = float(params.get("off", 17.0))
    require_di = bool(params.get("require_di", True))

    # Генерируем сигналы
    signals = generate_signals(
        close=df["close"],
        high=df["high"],
        low=df["low"],
        fast=fast,
        slow=slow,
        adx_len=adx_len,
        on=on,
        off=off,
        require_di=require_di,
    )

    # Конвертируем цены
    close = pd.to_numeric(df["close"], errors="coerce").fillna(method='ffill').to_numpy(float)

    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []
    entry_px = None
    entry_i = None

    # Строим трейды
    for i, signal in enumerate(signals):
        if signal == 1 and entry_px is None:  # Открытие позиции
            entry_px = float(close[i])
            entry_i = i
        elif signal == -1 and entry_px is not None:  # Закрытие позиции
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

    # Дополнительные данные для анализа
    extra = {
        "ema_fast": _ema(pd.Series(close), fast).tolist(),
        "ema_slow": _ema(pd.Series(close), slow).tolist(),
        "adx": _adx(
            pd.Series(df["high"]),
            pd.Series(df["low"]),
            pd.Series(close),
            adx_len
        ).tolist(),
        "signals": signals
    }

    return trades, np.asarray(pnls, dtype=float), extra


# Для совместимости с разными системами регистрации
build = build_trades  # алиас
name = "ema_adx"


# Функция для создания сетки параметров
def default_grid() -> List[Dict[str, Any]]:
    """Создает сетку параметров для оптимизации"""
    grid = []
    for fast in [8, 12, 16]:
        for slow in [21, 26, 34]:
            for on in [20.0, 23.0, 25.0]:
                for off in [14.0, 16.0, 18.0]:
                    for require_di in [False, True]:
                        grid.append({
                            "fast": fast,
                            "slow": slow,
                            "adx_len": 14,
                            "on": on,
                            "off": off,
                            "require_di": require_di
                        })
    return grid
