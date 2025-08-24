# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import math

from .compat import (
    build_bt_config,
    normalize_metrics,
    normalize_resample_rule,
    run_backtest_compat,
)

log = logging.getLogger(__name__)


def parse_int_list(spec: Union[str, Sequence[int]]) -> List[int]:
    """
    "5:20:5" -> [5,10,15,20]
    "0,3,5,8" -> [0,3,5,8]
    [1,2] -> [1,2]
    """
    if isinstance(spec, (list, tuple)):
        return [int(x) for x in spec]
    s = str(spec).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            start, stop = int(parts[0]), int(parts[1])
            step = 1
        else:
            start, stop, step = int(parts[0]), int(parts[1]), int(parts[2])
        if step == 0:
            raise ValueError("step cannot be 0")
        if (stop - start) * step < 0:
            step = -abs(step) if stop < start else abs(step)
        out = list(range(start, stop + (1 if step > 0 else -1), step))
        return out
    if s == "":
        return []
    return [int(x.strip()) for x in s.split(",") if x.strip() != ""]


def parse_float_list(spec: Union[str, Sequence[float]]) -> List[float]:
    if isinstance(spec, (list, tuple)):
        return [float(x) for x in spec]
    s = str(spec).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            start, stop = float(parts[0]), float(parts[1])
            step = 1.0
        else:
            start, stop, step = float(parts[0]), float(parts[1]), float(parts[2])
        if step == 0:
            raise ValueError("step cannot be 0")
        out: List[float] = []
        x = start
        if step > 0:
            while x <= stop + 1e-12:
                out.append(round(x, 10))
                x += step
        else:
            while x >= stop - 1e-12:
                out.append(round(x, 10))
                x += step
        return out
    if s == "":
        return []
    return [float(x.strip()) for x in s.split(",") if x.strip() != ""]


@dataclass
class SweepCfg:
    pair: str
    span: str  # e.g. "1m:5000"
    resample: Optional[str]  # e.g. "5m"
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int
    out_dir: Path


_HEADERS = [
    "pair", "bars", "trades", "winrate_pct", "total_return_pct", "max_drawdown_pct",
    "final_equity_eur", "start_equity_eur", "profit_factor", "avg_trade_eur",
    "exposure_pct", "sharpe", "cagr_pct", "calmar", "bars_per_year",
    "fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur", "fee_bps", "slip_bps",
    "max_daily_loss_bps", "trades_csv", "equity_csv", "error"
]


def _safe_get(m: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in m:
            return m[k]
    return default


def run_sweep(cfg: SweepCfg) -> str:
    """
    Build grid and run vectorized bt for each point.
    Writes CSV and returns its path (string for historical compatibility).
    """
    out_dir: Path = cfg.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    res = normalize_resample_rule(cfg.resample) or "raw"
    sweep_path = out_dir / f"sweep_{cfg.pair}_{res}_{stamp}.csv"

    combos: List[Tuple[int, int, int, int, float]] = []
    for f in cfg.fast_list:
        for s in cfg.slow_list:
            if f >= s:
                continue  # common-sense constraint for MA-like setups
            for h in cfg.hyst_list:
                for cd in cfg.cooldown_list:
                    for qty in cfg.qty_list:
                        combos.append((f, s, h, cd, qty))

    with open(sweep_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(_HEADERS)

        for (fast, slow, hyst, cd, qty) in combos:
            error_txt = ""
            try:
                bt_cfg = build_bt_config(
                    pair=cfg.pair,
                    span=cfg.span,
                    resample=normalize_resample_rule(cfg.resample),
                    fast=int(fast),
                    slow=int(slow),
                    hysteresis_bps=int(hyst),
                    cooldown_bars=int(cd),
                    qty_eur=float(qty),
                    fee_bps=int(cfg.fee_bps),
                    slip_bps=int(cfg.slip_bps),
                    max_daily_loss_bps=int(cfg.max_daily_loss_bps),
                )

                bt_out = run_backtest_compat(bt_cfg, write_csv=False)
                norm = normalize_metrics(bt_out)
                m = norm["metrics"]

                row = [
                    cfg.pair,
                    _safe_get(m, "bars"),
                    _safe_get(m, "trades"),
                    round(float(_safe_get(m, "winrate_pct", default=0) or 0), 12),
                    round(float(_safe_get(m, "total_return_pct", default=0) or 0), 12),
                    float(_safe_get(m, "max_drawdown_pct", default=0) or 0),
                    float(_safe_get(m, "final_equity_eur", default=0) or 0),
                    float(_safe_get(m, "start_equity_eur", default=0) or 0),
                    float(_safe_get(m, "profit_factor", default=0) or 0),
                    float(_safe_get(m, "avg_trade_eur", default=0) or 0),
                    float(_safe_get(m, "exposure_pct", default=0) or 0),
                    float(_safe_get(m, "sharpe", default=0) or 0),
                    float(_safe_get(m, "cagr_pct", default=0) or 0),
                    float(_safe_get(m, "calmar", default=0) or 0),
                    _safe_get(m, "bars_per_year"),
                    fast, slow, hyst, cd, qty, cfg.fee_bps, cfg.slip_bps, cfg.max_daily_loss_bps,
                    norm.get("trades_csv"),
                    norm.get("equity_csv"),
                    "",  # error
                ]
            except Exception as e:
                log.warning("sweep point failed f=%s s=%s h=%s cd=%s qty=%s: %s",
                            fast, slow, hyst, cd, qty, e)
                error_txt = str(e)
                row = [
                    cfg.pair, "", "", "", "", "", "", "", "", "", "", "", "", "", "",
                    fast, slow, hyst, cd, qty, cfg.fee_bps, cfg.slip_bps, cfg.max_daily_loss_bps,
                    "", "", error_txt
                ]
            wr.writerow(row)

    return str(sweep_path)
