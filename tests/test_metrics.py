# tests/test_metrics.py
import numpy as np
import pandas as pd

from src.backtest.metrics import compute_equity_metrics


def test_metrics_basic():
    idx = pd.date_range("2024-01-01", periods=1000, freq="5min", tz="UTC")
    eq = pd.Series(1000.0, index=idx)
    eq = eq * (1.0 + 0.0001) ** np.arange(len(eq))

    trade_pnls = [1.0, -0.5, 0.3, 0.2]
    m = compute_equity_metrics(
        equity=eq,
        trade_pnls=trade_pnls,
        n_wins=3,
        n_trades=4,
        exposure_pct=50.0,
        start_equity=1000.0,
        risk_free=0.0,
    )
    assert m.bars == 1000
    assert m.trades == 4
    assert m.winrate_pct > 0
    assert m.profit_factor > 1.0
    assert m.max_drawdown_pct <= 0.0
    assert m.cagr_pct > 0.0
    assert m.calmar > 0.0
