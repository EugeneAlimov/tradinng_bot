import pytest

from src.backtest.registry import get_default_grid, get_registry_builder


# from src.domain.strategy.registry import get_default_grid, get_builder


@pytest.mark.parametrize("name", ["ema_adx", "ema_adx_atr", "macd_cross", "donchian"])
def test_default_grid_not_empty(name):
    grid = get_default_grid(name)
    assert isinstance(grid, list) and len(grid) > 0, f"default grid empty for {name}"
    assert all(isinstance(p, dict) for p in grid)


@pytest.mark.parametrize("name", ["ema_adx", "ema_adx_atr", "macd_cross", "donchian"])
def test_builder_contract(name):
    builder = get_registry_builder(name)
    # билдер должен быть вызываемым и возвращать кортеж (trades, pnls, extra) для тестового каркаса
    assert callable(builder)
