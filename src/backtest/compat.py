# -*- coding: utf-8 -*-
"""
Compat helpers for backtesting modules:
- normalize resample rules
- dynamic resolution of BtConfig / backtest callable
- safe call with supported kwargs
- metrics normalization for CSV/JSON
"""
from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Union

log = logging.getLogger(__name__)


# ---------- small utils ----------

def normalize_resample_rule(rule: Optional[str]) -> Optional[str]:
    """
    Pandas accepts both '5T' and '5min'/'5m'. Normalize to uppercase alias.
    Returns None if rule is falsy.
    """
    if not rule:
        return None
    s = str(rule).strip()
    # common quick normalizations
    s = s.replace("min", "m").replace("MIN", "m")
    s = s.replace("hour", "h").replace("HOUR", "h")
    s = s.replace("sec", "s").replace("SEC", "s")

    # '5m' -> '5T', '1h' -> '1H', '1d' -> '1D'
    if s.endswith("m"):
        return s[:-1] + "T"
    if s.endswith("h"):
        return s[:-1] + "H"
    if s.endswith("d"):
        return s[:-1] + "D"
    return s


def _filter_kwargs_by_signature(fn: Any, src: Dict[str, Any]) -> Dict[str, Any]:
    """Return only kwargs accepted by callable/class `fn`."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # Builtin or no signature – pass nothing
        return {}
    allowed = set(sig.parameters.keys())
    return {k: v for k, v in src.items() if k in allowed}


# ---------- dynamic resolution of vectorized_bt API ----------

@dataclass
class BacktestAPI:
    module: Any
    BtConfig: Optional[Any]
    run_bt: Any  # callable


def resolve_backtest_api() -> BacktestAPI:
    """
    Import `src.backtest.vectorized_bt` and resolve a callable:
    prefer: run_backtest, run, backtest, run_bt
    """
    mod = importlib.import_module("src.backtest.vectorized_bt")

    BtConfig = getattr(mod, "BtConfig", None)
    run_bt = None
    for name in ("run_backtest", "run", "backtest", "run_bt"):
        cand = getattr(mod, name, None)
        if callable(cand):
            run_bt = cand
            break
    if run_bt is None:
        raise ImportError(
            "No backtest callable found in src.backtest.vectorized_bt "
            "(tried: run_backtest, run, backtest, run_bt)"
        )
    return BacktestAPI(module=mod, BtConfig=BtConfig, run_bt=run_bt)


def build_bt_config(**kwargs) -> Any:
    """
    Build BtConfig instance if class exists; otherwise return kwargs dict.
    Filters unsupported kwargs by signature to stay compatible across versions.
    """
    api = resolve_backtest_api()
    if api.BtConfig is None:
        # fallback to plain dict config
        return dict(kwargs)
    # filter by BtConfig signature
    filtered = _filter_kwargs_by_signature(api.BtConfig, kwargs)
    return api.BtConfig(**filtered)


def run_backtest_compat(config_obj: Any, **maybe_kwargs) -> Any:
    """
    Run backtest using resolved callable.
    Supports different call signatures:
      - fn(config)
      - fn(config=config)
      - fn(cfg=config, **extra)
      - fn(**kwargs)  (if it expects decomposed fields)
    """
    api = resolve_backtest_api()
    fn = api.run_bt
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # no signature -> try the simplest: fn(config_obj)
        return fn(config_obj)

    params = set(sig.parameters.keys())

    # Variant 1: single positional param
    if len(params) == 1 and next(iter(params)) not in ("**",):
        try:
            return fn(config_obj)
        except TypeError:
            pass

    # Variant 2: keyword 'config' or 'cfg'
    call_kwargs = {}
    if "config" in params:
        call_kwargs["config"] = config_obj
    elif "cfg" in params:
        call_kwargs["cfg"] = config_obj

    # attach supported extras (e.g. out_dir, write_csv, etc.)
    call_kwargs.update(_filter_kwargs_by_signature(fn, maybe_kwargs))

    # Variant 3: function expects decomposed fields instead of object
    if not call_kwargs and isinstance(config_obj, dict):
        call_kwargs = _filter_kwargs_by_signature(fn, config_obj)
        call_kwargs.update(_filter_kwargs_by_signature(fn, maybe_kwargs))

    return fn(**call_kwargs)


# ---------- metrics normalization ----------

_SERIALIZABLE_BASE = (int, float, str, bool, type(None))


def _to_primitive(x: Any) -> Any:
    """Convert common numpy/pandas scalars to python primitives."""
    try:
        import numpy as np  # type: ignore
        if isinstance(x, (np.generic,)):
            return x.item()
    except Exception:
        pass
    try:
        import pandas as pd  # type: ignore
        if isinstance(x, (pd.Timestamp,)):
            return x.isoformat()
    except Exception:
        pass
    return x


def normalize_metrics(obj: Any) -> Dict[str, Any]:
    """
    Try to extract plain serializable metrics from backtest result.
    Supported forms:
      - dict with metrics directly
      - dict with {"metrics": dict, "trades_df": df, "equity_df": df, ...}
      - tuple (metrics_dict, trades_df?, equity_df?)
    """
    out: Dict[str, Any] = {
        "metrics": {},
        "trades_df": None,
        "equity_df": None,
        "trades_csv": None,
        "equity_csv": None,
    }

    # unbox
    if isinstance(obj, dict):
        if "metrics" in obj and isinstance(obj["metrics"], dict):
            out["metrics"] = obj["metrics"]
            out["trades_df"] = obj.get("trades_df")
            out["equity_df"] = obj.get("equity_df")
            out["trades_csv"] = obj.get("trades_csv")
            out["equity_csv"] = obj.get("equity_csv")
        else:
            out["metrics"] = obj
    elif isinstance(obj, tuple):
        if len(obj) >= 1 and isinstance(obj[0], dict):
            out["metrics"] = obj[0]
        if len(obj) >= 2:
            out["trades_df"] = obj[1]
        if len(obj) >= 3:
            out["equity_df"] = obj[2]
    else:
        # unknown form – try to convert to dict
        try:
            out["metrics"] = dict(obj)
        except Exception:
            out["metrics"] = {"value": obj}

    # strip non-serializable
    cleaned: Dict[str, Any] = {}
    for k, v in out["metrics"].items():
        v = _to_primitive(v)
        if isinstance(v, _SERIALIZABLE_BASE):
            cleaned[k] = v
            continue
        # numpy/pandas scalars
        try:
            cleaned[k] = _to_primitive(v)
            if isinstance(cleaned[k], _SERIALIZABLE_BASE):
                continue
        except Exception:
            pass
        # last resort: string
        try:
            cleaned[k] = str(v)
        except Exception:
            cleaned[k] = None

    out["metrics"] = cleaned
    return out
