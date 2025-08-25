# tests/test_walkforward_api.py
import numpy as np
import pandas as pd

from src.backtest.walkforward import WFConfig, run_walkforward


def _make_df(n=1200, freq="5min"):
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 0.05, size=n)), index=idx)
    return pd.DataFrame({"close": close})


def test_wf_contract():
    df = _make_df(1200, "5min")
    cfg = WFConfig(
        pair="TEST_EUR",
        span="1m:5000",
        resample="5m",
        fast=10, slow=20,
        hysteresis_bps=0,
        cooldown_bars=5,
        fee_bps=10, slip_bps=2, qty_eur=100.0,
        folds=4, min_train_bars=150, min_valid_bars=100,
    )
    out = run_walkforward(cfg, df_override=df, print_json=False)
    for k in [
        "oos_total_return_pct_mean", "oos_max_drawdown_pct_mean", "oos_profit_factor_mean",
        "oos_sharpe_mean", "oos_cagr_pct_mean", "oos_calmar_mean",
        "oos_trades_mean", "oos_exposure_pct_mean", "oos_avg_trade_eur_mean"
    ]:
        assert k in out
