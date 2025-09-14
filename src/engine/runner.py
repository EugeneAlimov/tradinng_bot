# src/engine/runner.py
from __future__ import annotations
from typing import Optional, Dict, Any
import pandas as pd

from src.data.resampler import resample_ohlc, normalize_resample_rule
from src.engine.pipeline import Pipeline
from src.infra.log import NdjsonWriter


def run_observe(
        df: pd.DataFrame,
        *,
        resample: Optional[str],
        strategy: str,
        strategy_params: Optional[Dict[str, Any]] = None,
        out_json: Optional[str] = None,
        pure_json: bool = False,
) -> Dict[str, Any]:
    """
    Observe-mode runner: resample -> strategy -> one JSON line.
    Returns the JSON dict (also prints/writes if requested).
    """
    if resample:
        df = resample_ohlc(df, normalize_resample_rule(resample))
    if df.empty:
        msg = {"type": "signal", "side": "FLAT", "reason": "empty_data"}
        if not pure_json:
            print("[engine] empty dataframe -> FLAT")
        NdjsonWriter(out_json).write(msg) if (pure_json or out_json) else None
        return msg

    pipe = Pipeline(strategy="ema_crossover" if strategy is None else strategy, params=strategy_params)
    sig = pipe.on_df(df)
    last = df.iloc[-1]
    payload = {
        "type": "signal",
        "time": df.index[-1].isoformat(),
        "price": float(last["close"]),
        "side": sig.side,
        "indicators": sig.indicators,
        "lookback": int(min(len(df), 500)),
    }
    if pure_json or out_json:
        NdjsonWriter(out_json).write(payload)
    else:
        print(payload)
    return payload
