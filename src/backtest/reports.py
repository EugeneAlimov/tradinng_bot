# src/backtest/reports.py
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _choose_pnl_field(sample: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Выбираем приоритетное поле PnL из сделки: net_notional -> net -> pnl -> pnl_gross_notional -> pnl_gross.
    Возвращает (field_name, is_notional).
    """
    for f in ("pnl_net_notional", "pnl_net", "pnl", "pnl_gross_notional", "pnl_gross"):
        if f in sample:
            return f, f.endswith("_notional")
    return "pnl", False


def summarize_trades(trades: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    trades = list(trades)
    if not trades:
        return {
            "schema_version": "trades_summary.v1",
            "closed_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_bars_held": 0.0,
            "med_bars_held": 0.0,
            "avg_hold_seconds": 0.0,
            "med_hold_seconds": 0.0,
            "exit_reason_counts": {},
            "span_utc": {"first": None, "last": None},
        }

    # Выбор поля pnl
    sample_with_pnl = next((t for t in trades if any(
        k in t for k in ("pnl_net_notional", "pnl_net", "pnl", "pnl_gross_notional", "pnl_gross"))), None)
    pnl_field, _ = _choose_pnl_field(sample_with_pnl or {})

    pnls: List[float] = []
    bars: List[float] = []
    secs: List[float] = []
    reasons = Counter()

    for t in trades:
        if pnl_field in t:
            pnls.append(_to_float(t[pnl_field]))
        if "bars_held" in t:
            bars.append(_to_float(t["bars_held"]))
        if "hold_seconds" in t:
            secs.append(_to_float(t["hold_seconds"]))
        if "exit_reason" in t:
            reasons[str(t["exit_reason"])] += 1

    n = len(pnls)
    total = float(sum(pnls))
    avg = float(total / n) if n else 0.0
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    win_rate = float(len(wins) / n) if n else 0.0
    gross_win = float(sum(wins)) if wins else 0.0
    gross_loss = float(-sum(losses)) if losses else 0.0
    profit_factor = float(gross_win / gross_loss) if gross_loss > 1e-15 else (float("inf") if gross_win > 0 else 0.0)

    # временной охват
    def ts_to_iso(v):
        try:
            return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
        except Exception:
            return None

    entry_ts = [t.get("entry_ts") for t in trades if "entry_ts" in t]
    exit_ts = [t.get("exit_ts") for t in trades if "exit_ts" in t]
    span_first = ts_to_iso(min(entry_ts)) if entry_ts else None
    span_last = ts_to_iso(max(exit_ts)) if exit_ts else None

    return {
        "schema_version": "trades_summary.v1",
        "closed_trades": n,
        "win_rate": win_rate,
        "total_pnl": total,
        "avg_pnl": avg,
        "profit_factor": profit_factor,
        "avg_bars_held": float(mean(bars)) if bars else 0.0,
        "med_bars_held": float(median(bars)) if bars else 0.0,
        "avg_hold_seconds": float(mean(secs)) if secs else 0.0,
        "med_hold_seconds": float(median(secs)) if secs else 0.0,
        "exit_reason_counts": dict(reasons.most_common()),
        "span_utc": {"first": span_first, "last": span_last},
        "pnl_field_used": pnl_field,
    }
