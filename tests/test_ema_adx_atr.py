# tests/test_ema_adx_atr.py
import math
import numpy as np
from src.domain.strategy import registry as reg


def _ohlc(n=500):
    """Создаем более волатильные тестовые данные для генерации сигналов"""
    ts = list(range(n))

    # Создаем синусоидальный тренд с шумом для лучшего ADX
    base_trend = 100.0
    close = []
    high = []
    low = []
    open_ = []

    for i in ts:
        # Комбинируем тренд + волатильность + шум
        trend = base_trend + i * 0.01  # слабый восходящий тренд
        volatility = 5.0 * math.sin(i * 0.1) + 2.0 * math.sin(i * 0.3)  # циклическая волатильность
        noise = 0.5 * math.sin(i * 0.7) * math.cos(i * 0.23)  # шум

        c = trend + volatility + noise

        # Добавляем реалистичные high/low/open относительно close
        daily_range = abs(volatility) * 0.3 + 0.5  # дневной диапазон
        h = c + daily_range * 0.6
        l = c - daily_range * 0.4
        o = c + noise * 0.2

        close.append(c)
        high.append(h)
        low.append(l)
        open_.append(o)

    return dict(ts=ts, open=open_, high=high, low=low, close=close)


def test_signals_and_status():
    """Тест с более чувствительными параметрами и волатильными данными"""
    o = _ohlc(600)
    defn = reg.get("ema_adx_atr")

    # Используем более чувствительные параметры для гарантии сигналов
    sig = defn.generate_signals(
        close=o["close"],
        high=o["high"],
        low=o["low"],
        fast=5,  # более быстрые EMA для частых кроссов
        slow=15,  #
        adx_len=10,  # более короткий ADX
        on=10,  # низкий порог включения ADX
        off=8,  # низкий порог выключения ADX
        require_di=False,  # отключаем фильтр DI
        atr_len=10,  # короткий ATR
        atr_mult=2.0  # менее агрессивный стоп
    )

    assert isinstance(sig, list) and len(sig) == len(o["close"])

    # Проверяем, что есть хотя бы один сигнал
    signal_count = sum(1 for x in sig if x != 0)
    assert signal_count > 0, f"ожидали хотя бы один сигнал, получили {signal_count} из {len(sig)} баров"

    # Проверяем status с теми же параметрами
    txt, state = defn.status(
        close=o["close"],
        high=o["high"],
        low=o["low"],
        fast=5, slow=15, adx_len=10, on=10, off=8,
        require_di=False, atr_len=10, atr_mult=2.0
    )

    assert isinstance(txt, str)
    assert state in (-1, 0, 1)

    # Дополнительная диагностика для отладки
    print(f"Generated {signal_count} signals from {len(sig)} bars")
    print(f"Status: {txt}")
    print(f"State: {state}")


def test_signals_with_default_params():
    """Дополнительный тест с дефолтными параметрами и экстремально волатильными данными"""
    # Создаем экстремально волатильные данные
    n = 300
    close = [100.0]
    high = [102.0]
    low = [98.0]

    # Создаем сильные движения для срабатывания ADX
    for i in range(1, n):
        if i < 50:
            # Сильный восходящий тренд
            c = close[-1] * (1 + 0.02)
        elif i < 100:
            # Коррекция
            c = close[-1] * (1 - 0.015)
        elif i < 150:
            # Боковик с волатильностью
            c = close[-1] * (1 + 0.01 * math.sin(i * 0.5))
        else:
            # Сильный восходящий тренд снова
            c = close[-1] * (1 + 0.025)

        h = c * 1.01
        l = c * 0.99

        close.append(c)
        high.append(h)
        low.append(l)

    defn = reg.get("ema_adx_atr")
    sig = defn.generate_signals(
        close=close, high=high, low=low,
        fast=9, slow=21, adx_len=14, on=18, off=14,
        require_di=False, atr_len=14, atr_mult=3.0
    )

    signal_count = sum(1 for x in sig if x != 0)
    print(f"Default params test: {signal_count} signals from {len(sig)} bars")

    # С такими данными должен быть хотя бы один сигнал
    assert signal_count > 0, f"С экстремальными данными ожидали сигналы, получили {signal_count}"
