from .backtest import run_backtest_sma
from .metrics import (
    compute_metrics_from_equity,
    _compute_metrics_from_equity,  # совместимость
)
__all__ = ["run_backtest_sma", "compute_metrics_from_equity", "_compute_metrics_from_equity"]
