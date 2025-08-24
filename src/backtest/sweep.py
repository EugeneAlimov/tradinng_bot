# src/backtest/sweep.py
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .compat import (
    fetch_exmo_candles_cached,
    normalize_resample_rule,
    resample_ohlc,
    SimConfig,
    simulate_on_df,
)


# ------------------------ parsing helpers ------------------------

def _parse_range_token(tok: str) -> Iterable[int]:
    """
    Parse 'start:end:step' (inclusive of start, exclusive of end) into ints.
    Example: '5:20:5' -> [5,10,15]
    """
    parts = tok.split(":")
    if len(parts) != 3:
        raise ValueError(f"Bad range token '{tok}', expected start:end:step")
    s, e, st = (int(parts[0]), int(parts[1]), int(parts[2]))
    if st == 0:
        raise ValueError("step must be non-zero")
    # как в Python range: end не включаем
    return range(s, e, st)


def parse_int_list(spec: str) -> List[int]:
    """
    Accepts comma-separated ints OR range tokens 'a:b:c'.
    Examples:
      '5,10,15' -> [5,10,15]
      '5:20:5'  -> [5,10,15]
      '5:20:5,25' -> [5,10,15,25]
    """
    out: List[int] = []
    for tok in [t.strip() for t in spec.split(",") if t.strip()]:
        if ":" in tok:
            out.extend(list(_parse_range_token(tok)))
        else:
            out.append(int(tok))
    # dedup but keep order
    seen = set()
    uniq: List[int] = []
    for v in out:
        if v not in seen:
            uniq.append(v)
            seen.add(v)
    return uniq


def parse_float_list(spec: str) -> List[float]:
    out: List[float] = []
    for tok in [t.strip() for t in spec.split(",") if t.strip()]:
        if ":" in tok:
            rng = list(_parse_range_token(tok))
            out.extend([float(x) for x in rng])
        else:
            out.append(float(tok))
    # dedup keep order
    seen = set()
    uniq: List[float] = []
    for v in out:
        if v not in seen:
            uniq.append(v)
            seen.add(v)
    return uniq


# ------------------------ config ------------------------

@dataclass
class SweepCfg:
    pair: str
    span: str                 # ex: "1m:5000"
    resample: str = "5m"      # "5m" | "5T" | "1H" ...
    fast_list: Sequence[int] = (10,)
    slow_list: Sequence[int] = (20,)
    hyst_list: Sequence[int] = (0,)
    cooldown_list: Sequence[int] = (0, 3, 5)
    qty_list: Sequence[float] = (100.0,)
    fee_bps: int = 10
    slip_bps: int = 2
    max_daily_loss_bps: int = 0
    out_dir: Path | str = Path("data/sweep")


# ------------------------ core ------------------------

def run_sweep(cfg: SweepCfg) -> str:
    """
    Выполняет свип всех комбинаций и пишет один CSV.
    Возвращает путь к CSV (str).
    """
    rr_user = cfg.resample
    rr = normalize_resample_rule(rr_user)

    out_root = Path(cfg.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # в имени файла придерживаемся твоей схемы: 5T для минут
    file_resample = rr.replace("T", "m") if rr.endswith("T") else rr
    # но в успешных логах у тебя встречались и 5m и 5T — оставим 5m для читаемости
    file_resample = "5m" if rr in ("5T", "5m") else rr
    out_csv = out_root / f"sweep_{cfg.pair}_{file_resample}_{timestamp}.csv"

    rows: List[dict] = []

    # 1) fetch & resample один раз
    try:
        raw = fetch_exmo_candles_cached(cfg.pair, cfg.span)
        df = resample_ohlc(raw, rr)
        if df.empty:
            raise RuntimeError(f"Empty resampled candles for {cfg.pair} {cfg.span} -> {rr}")
    except Exception as e:
        # записываем компактный CSV с ошибкой
        pd.DataFrame(
            [{"pair": cfg.pair, "error": f"fetch_or_resample_failed: {e}"}]
        ).to_csv(out_csv, index=False)
        return str(out_csv)

    # 2) перебор комбинаций
    combos = list(itertools.product(
        list(cfg.fast_list),
        list(cfg.slow_list),
        list(cfg.hyst_list),
        list(cfg.cooldown_list),
        list(cfg.qty_list),
    ))

    for fast, slow, hyst, cd, qty in combos:
        row_base = {
            "pair": cfg.pair,
            # метрики заполним после
            "bars_per_year": np.nan,  # заполним из метрик симулятора
            "fast": int(fast),
            "slow": int(slow),
            "hysteresis_bps": int(hyst),
            "cooldown_bars": int(cd),
            "qty_eur": float(qty),
            "fee_bps": int(cfg.fee_bps),
            "slip_bps": int(cfg.slip_bps),
            "max_daily_loss_bps": int(cfg.max_daily_loss_bps),
            "trades_csv": None,
            "equity_csv": None,
        }
        try:
            scfg = SimConfig(
                fast=int(fast),
                slow=int(slow),
                hysteresis_bps=int(hyst),
                cooldown_bars=int(cd),
                fee_bps=int(cfg.fee_bps),
                slip_bps=int(cfg.slip_bps),
                qty_eur=float(qty),
                max_daily_loss_bps=int(cfg.max_daily_loss_bps),
                resample=rr,
            )
            trades_df, equity_df, metrics = simulate_on_df(df, scfg)

            row = {
                **row_base,
                "bars": int(metrics["bars"]),
                "trades": int(metrics["trades"]),
                "winrate_pct": float(metrics["winrate_pct"]),
                "total_return_pct": float(metrics["total_return_pct"]),
                "max_drawdown_pct": float(metrics["max_drawdown_pct"]),
                "final_equity_eur": float(metrics["final_equity_eur"]),
                "start_equity_eur": float(metrics["start_equity_eur"]),
                "profit_factor": float(metrics["profit_factor"]),
                "avg_trade_eur": float(metrics["avg_trade_eur"]),
                "exposure_pct": float(metrics["exposure_pct"]),
                "sharpe": float(metrics["sharpe"]),
                "cagr_pct": float(metrics["cagr_pct"]),
                "calmar": float(metrics["calmar"]),
                "bars_per_year": float(metrics["bars_per_year"]),
                "trades_csv": None,
                "equity_csv": None,
            }
        except Exception as e:
            row = {**row_base, "error": str(e)}

        rows.append(row)

    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return str(out_csv)
