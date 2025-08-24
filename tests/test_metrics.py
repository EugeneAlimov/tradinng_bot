import numpy as np
import pandas as pd

from src.backtest.metrics import compute_equity_metrics, estimate_bars_per_year


def test_metrics_basic():
    # синтетика: равномерный рост +1 bp на бар на 1000 баров
    idx = pd.date_range("2024-01-01", periods=1000, freq="5min", tz="UTC")
    eq = pd.Series(1000.0, index=idx)
    # имитируем плавный рост
    eq = eq * (1.0 + 0.0001) ** np.arange(len(eq))

    trade_pnls = [1.0, -0.5, 0.3, 0.2]  # PF > 1
    metrics = compute_equity_metrics(
        equity=eq,
        trade_pnls=trade_pnls,
        n_wins=3,
        n_trades=4,
        exposure_pct=50.0,
        start_equity=1000.0,
        risk_free=0.0,
    )
    assert metrics.bars == 1000
    assert metrics.trades == 4
    assert metrics.winrate_pct > 0
    assert metrics.profit_factor > 1.0
    assert metrics.max_drawdown_pct <= 0.0
    assert metrics.cagr_pct > 0.0
    assert metrics.calmar > 0.0
    assert 50000 < metrics.bars_per_year < 200000  # 5m crypto: ~105120
