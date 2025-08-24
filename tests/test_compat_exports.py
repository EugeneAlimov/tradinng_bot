"""
Юнит на совместимые фасады, чтобы не потерять экспорт при рефакторинге.
"""
from __future__ import annotations

import inspect
import importlib


def test_compat_exports_present():
    compat = importlib.import_module("src.backtest.compat")

    required = [
        "fetch_exmo_candles_cached",
        "resample_ohlc",
        "simulate_on_df",
        "normalize_resample_rule",
        "build_bt_config",
        "SimConfig",
        "normalize_metrics",
        "run_backtest_compat",
    ]
    for name in required:
        assert hasattr(compat, name), f"{name} missing in backtest.compat"


def test_run_backtest_compat_signature():
    compat = importlib.import_module("src.backtest.compat")
    fn = getattr(compat, "run_backtest_compat")
    sig = str(inspect.signature(fn))
    # ожидаем простую сигнатуру (bt_cfg: Dict[str, Any]) -> Dict[str, Any]
    assert "bt_cfg" in sig and ")" in sig
