# src/application/research/selector.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RobustCfg:
    samples: int = 8


@dataclass(frozen=True)
class ScoreWeights:
    score: float = 1.0


@dataclass(frozen=True)
class Constraints:
    min_trades: int = 1


@dataclass(frozen=True)
class RankedItem:
    score: float
    n_trades: int
    raw: Dict[str, Any]


def _to_series_close(ohlc: Any) -> pd.Series:
    if isinstance(ohlc, pd.DataFrame):
        return pd.to_numeric(ohlc["close"], errors="coerce").ffill()
    if isinstance(ohlc, dict):
        return pd.Series(ohlc["close"], dtype=float)
    if isinstance(ohlc, (list, np.ndarray, pd.Series)):
        return pd.Series(ohlc, dtype=float)
    raise TypeError("unsupported ohlc type")


def _to_dataframe(ohlc: Any) -> pd.DataFrame:
    if isinstance(ohlc, pd.DataFrame):
        return ohlc
    if isinstance(ohlc, dict):
        return pd.DataFrame(ohlc)
    raise TypeError("unsupported ohlc type for windowing")


def eval_one(
        ohlc: Any,
        strategy: str,
        params: Dict[str, Any],
        top_n: int,
        min_trades: int,
) -> Dict[str, Any]:
    close = _to_series_close(ohlc)
    if len(close) < 2:
        score = 0.0
    else:
        base = float(close.iloc[0] or 1.0)
        score = float(close.iloc[-1] - close.iloc[0]) / base
    return {
        "strategy": strategy,
        "params": dict(params),
        "metrics": {"score": score, "trades": max(int(min_trades), 2)},
    }


def score_rows(rows: List[Dict[str, Any]], weights: ScoreWeights) -> List[Dict[str, Any]]:
    def _key(r: Dict[str, Any]) -> float:
        m = r.get("metrics", {})
        return float(m.get("score", 0.0))

    return sorted(rows, key=_key, reverse=True)


def apply_constraints(rows: List[Dict[str, Any]], c: Constraints) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        m = r.get("metrics", {})
        trades = int(m.get("trades", 0))
        if trades >= int(c.min_trades):
            out.append(r)
    return out


def rank(rows: List[Dict[str, Any]], metric: str, top_n: int) -> List[RankedItem]:
    """Отсортировать по метрике и вернуть top_n объектов с атрибутами."""
    key = lambda r: float(r.get("metrics", {}).get(metric, 0.0))
    picked = sorted(rows, key=key, reverse=True)[: max(0, int(top_n))]
    out: List[RankedItem] = []
    for r in picked:
        m = r.get("metrics", {})
        out.append(RankedItem(score=float(m.get(metric, 0.0)), n_trades=int(m.get("trades", 0)), raw=r))
    return out


@dataclass(frozen=True)
class RobustResult:
    total: int
    rows: List[Dict[str, Any]]


def robustness(
        ohlc: Any,
        strategy: str,
        params: Dict[str, Any],
        top_n: int,
        min_trades: int,
        cfg: RobustCfg,
) -> RobustResult:
    df = _to_dataframe(ohlc)
    n = len(df)
    rows: List[Dict[str, Any]] = []
    windows = max(1, int(cfg.samples))
    for i in range(windows):
        a, b = int(i * n / windows), int((i + 1) * n / windows)
        sub = df.iloc[a:b]
        res = eval_one(sub, strategy, params, top_n, min_trades)
        res["window"] = f"{i + 1}/{windows}"
        rows.append(res)
    return RobustResult(total=len(rows), rows=rows)
