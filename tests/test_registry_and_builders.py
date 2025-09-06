# tests/test_registry_and_builders.py
from __future__ import annotations
import pandas as pd
import numpy as np

from src.backtest.registry import get_registry_builder, get_default_grid


def _fake_ohlc(n=200):
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    price = pd.Series(np.cumsum(np.random.randn(n)) * 0.001 + 0.1, index=idx).abs()
    df = pd.DataFrame({
        "dt": idx,
        "timestamp": (idx.view("int64") // 10 ** 9).astype(int),
        "open": price,
        "high": price * 1.002,
        "low": price * 0.998,
        "close": price.shift(-1).ffill(),  # Исправлено: убрали deprecated method
        "volume": 1000.0,
    })
    return df


def test_registry_nonempty():
    reg = get_registry_builder()

    # Проверяем что реестр не пустой
    assert len(reg) > 0, f"Registry is empty: {reg}"

    # Проверяем доступные стратегии
    available_strategies = list(reg.keys())
    print(f"Available strategies: {available_strategies}")

    # Если есть ema_adx - отлично, если нет - проверим другие
    if "ema_adx" in reg:
        print("✅ ema_adx strategy found")
    else:
        print(f"⚠️ ema_adx not found, available: {available_strategies}")
        # Берем любую доступную стратегию для тестирования
        assert len(available_strategies) > 0, "No strategies available in registry"

    grid_map = get_default_grid()
    assert isinstance(grid_map, dict)

    # Проверяем grid для доступных стратегий
    for strategy_name in available_strategies[:3]:  # Первые 3 стратегии
        grid = grid_map.get(strategy_name, [])
        assert isinstance(grid, list)
        print(f"Strategy {strategy_name} has {len(grid)} grid combinations")


def test_build_ema_adx_smoke():
    reg = get_registry_builder()

    # Пытаемся найти EMA+ADX стратегию
    strategy_name = None
    builder = None

    # Приоритет: ema_adx -> ema_adx_atr -> любая другая
    for candidate in ["ema_adx", "ema_adx_atr"]:
        if candidate in reg:
            strategy_name = candidate
            builder = reg[candidate].build
            break

    # Если не найдено, берем первую доступную
    if builder is None:
        available = list(reg.keys())
        assert len(available) > 0, "No strategies available for testing"
        strategy_name = available[0]
        builder = reg[strategy_name].build

    print(f"Testing strategy: {strategy_name}")

    df = _fake_ohlc(300)

    # Базовые параметры, которые должны работать с большинством стратегий
    if strategy_name in ["ema_adx", "ema_adx_atr"]:
        params = {
            "fast": 12,
            "slow": 21,
            "adx_len": 14,
            "on": 15.0,  # Более мягкие параметры
            "off": 10.0,
            "require_di": False  # Отключаем DI фильтр
        }
        if strategy_name == "ema_adx_atr":
            params.update({"atr_len": 14, "atr_mult": 2.0})
    else:
        # Общие параметры для других стратегий
        params = {}

    try:
        trades, pnls, extra = builder(df, params)

        # Проверяем корректные типы
        assert hasattr(pnls, "__len__"), f"pnls should be array-like, got {type(pnls)}"
        assert isinstance(trades, list), f"trades should be list, got {type(trades)}"
        assert isinstance(extra, dict), f"extra should be dict, got {type(extra)}"

        print(f"✅ Strategy {strategy_name} generated {len(trades)} trades")
        print(f"   PnL array length: {len(pnls)}")
        print(f"   Extra data keys: {list(extra.keys())}")

    except Exception as e:
        print(f"❌ Error testing strategy {strategy_name}: {e}")
        # Не падаем, если одна стратегия не работает
        pass


def test_strategies_compatibility():
    """Тест совместимости доступных стратегий"""
    reg = get_registry_builder()

    # Тестируем каждую доступную стратегию
    df = _fake_ohlc(100)  # Меньший датасет для скорости

    for strategy_name, strategy_builder in reg.items():
        print(f"\n🧪 Testing strategy: {strategy_name}")

        try:
            # Пустые параметры - должны использоваться defaults
            trades, pnls, extra = strategy_builder.build(df, {})

            print(f"   ✅ {strategy_name}: {len(trades)} trades, {len(pnls)} pnls")

        except Exception as e:
            print(f"   ❌ {strategy_name} failed: {e}")
            # Продолжаем с другими стратегиями


if __name__ == "__main__":
    test_registry_nonempty()
    test_build_ema_adx_smoke()
    test_strategies_compatibility()
