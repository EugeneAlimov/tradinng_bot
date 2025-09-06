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
        "close": price.shift(-1).fillna(method="ffill"),
        "volume": 1000.0,
    })
    return df


def test_registry_nonempty():
    reg = get_registry_builder()
    assert "ema_adx" in reg
    grid_map = get_default_grid()
    assert isinstance(grid_map, dict)
    assert isinstance(grid_map.get("ema_adx", []), list)


def test_build_ema_adx_smoke():
    reg = get_registry_builder()
    builder = reg["ema_adx"].build
    df = _fake_ohlc(300)
    params = {"fast": 12, "slow": 21, "adx_len": 14, "on": 23.0, "off": 17.0, "require_di": True}
    trades, pnls, extra = builder(df, params)
    # корректные типы
    assert hasattr(pnls, "__len__")
    assert isinstance(trades, list)
