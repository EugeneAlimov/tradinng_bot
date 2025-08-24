# src/backtest/sweep.py
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Iterable, List, Tuple, Union, Optional, Dict, Any
from types import SimpleNamespace
import time
import pandas as pd

# НИЧЕГО не импортируем из сторонних датаклассов конфигов (BtConfig и т.п.).
# Используем только функцию векторного бэктеста.
from .vectorized_bt import run_backtest_vectorized


# -----------------------------
# Парсеры списков параметров
# -----------------------------
def _parse_int_list(spec: Union[str, Iterable[int]]) -> List[int]:
    """
    Поддерживаем:
      - "5,10,15"
      - "5:20:5"  (start:stop:step), stop ИСКЛЮЧИТСЯ (как в range)
    """
    if isinstance(spec, str):
        s = spec.strip()
        if ":" in s:
            parts = s.split(":")
            if len(parts) not in (2, 3):
                raise ValueError(f"Bad int list spec: {spec}")
            start = int(parts[0])
            stop = int(parts[1])
            step = int(parts[2]) if len(parts) == 3 else 1
            if step == 0:
                raise ValueError("Step must be non-zero for int range spec")
            return list(range(start, stop, step))
        else:
            return [int(x.strip()) for x in s.split(",") if x.strip()]
    else:
        return [int(x) for x in spec]


def _parse_float_list(spec: Union[str, Iterable[float]]) -> List[float]:
    """
    Поддерживаем:
      - "0.1,0.2,0.5"
      - "0:1:0.25" (start:stop:step), stop ИСКЛЮЧИТСЯ
    """
    if isinstance(spec, str):
        s = spec.strip()
        if ":" in s:
            parts = s.split(":")
            if len(parts) not in (2, 3):
                raise ValueError(f"Bad float list spec: {spec}")
            start = float(parts[0])
            stop = float(parts[1])
            step = float(parts[2]) if len(parts) == 3 else 1.0
            if step == 0:
                raise ValueError("Step must be non-zero for float range spec")
            out: List[float] = []
            val = start
            # Полуоткрытый диапазон
            if step > 0:
                while val < stop:
                    out.append(round(val, 12))
                    val += step
            else:
                while val > stop:
                    out.append(round(val, 12))
                    val += step
            return out
        else:
            return [float(x.strip()) for x in s.split(",") if x.strip()]
    else:
        return [float(x) for x in spec]


# Экспорт без подчёркивания для совместимости с main.py
def parse_int_list(spec: Union[str, Iterable[int]]) -> List[int]:
    return _parse_int_list(spec)


def parse_float_list(spec: Union[str, Iterable[float]]) -> List[float]:
    return _parse_float_list(spec)


@dataclass
class SweepCfg:
    pair: str
    span: str                     # напр. "1m:5000"
    resample: Optional[str]       # напр. "5m" или None
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]
    fee_bps: int = 10
    slip_bps: int = 2
    max_daily_loss_bps: int = 0
    out_dir: Path = Path("data/sweep")
    enter_on_start: bool = False


def _mk_cfg_for_bt(
    base: SweepCfg,
    fast: int,
    slow: int,
    hyst: int,
    cd: int,
    qty: float,
) -> SimpleNamespace:
    """
    Формируем «плоский» конфиг для run_backtest_vectorized.
    Поля именами совпадают с теми, что вы уже передавали через CLI.
    """
    return SimpleNamespace(
        pair=base.pair,
        span=base.span,
        resample=base.resample,
        fast=int(fast),
        slow=int(slow),
        hysteresis_bps=int(hyst),
        cooldown_bars=int(cd),
        fee_bps=int(base.fee_bps),
        slip_bps=int(base.slip_bps),
        qty_eur=float(qty),
        max_daily_loss_bps=int(base.max_daily_loss_bps),
        enter_on_start=bool(base.enter_on_start),
        vectorized=True,
    )


def run_sweep(cfg: SweepCfg) -> str:
    """
    Выполняет параметрический перебор и сохраняет CSV с результатами.
    Возвращает путь к CSV (str). В CSV кладём только сериализуемое + колонку 'error'.
    """
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out_csv = cfg.out_dir / f"sweep_{cfg.pair}_{cfg.resample or 'raw'}_{stamp}.csv"

    rows: List[Dict[str, Any]] = []

    for fast, slow, hyst, cd, qty in product(cfg.fast_list, cfg.slow_list, cfg.hyst_list, cfg.cooldown_list, cfg.qty_list):
        base_row = dict(
            pair=cfg.pair,
            fast=int(fast), slow=int(slow),
            hysteresis_bps=int(hyst), cooldown_bars=int(cd),
            qty_eur=float(qty),
            fee_bps=int(cfg.fee_bps), slip_bps=int(cfg.slip_bps),
            max_daily_loss_bps=int(cfg.max_daily_loss_bps),
        )

        # Базовая валидация
        if int(fast) >= int(slow):
            rows.append({**base_row, "error": "fast>=slow"})
            continue

        try:
            bt_cfg = _mk_cfg_for_bt(cfg, fast, slow, hyst, cd, qty)
            metrics: Dict[str, Any] = run_backtest_vectorized(bt_cfg)

            safe_keys = [
                "pair", "bars", "trades", "winrate_pct", "total_return_pct",
                "max_drawdown_pct", "final_equity_eur", "start_equity_eur",
                "profit_factor", "avg_trade_eur", "exposure_pct", "sharpe",
                "cagr_pct", "calmar", "bars_per_year", "trades_csv", "equity_csv",
            ]
            safe_metrics = {k: metrics.get(k, None) for k in safe_keys}
            rows.append({**base_row, **safe_metrics, "error": ""})
        except Exception as e:
            rows.append({**base_row, "error": str(e)})

    df = pd.DataFrame(rows)

    # Единый порядок колонок (и добиваем отсутствующие)
    col_order = [
        "pair", "bars", "trades", "winrate_pct", "total_return_pct", "max_drawdown_pct",
        "final_equity_eur", "start_equity_eur", "profit_factor", "avg_trade_eur",
        "exposure_pct", "sharpe", "cagr_pct", "calmar", "bars_per_year",
        "fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur",
        "fee_bps", "slip_bps", "max_daily_loss_bps",
        "trades_csv", "equity_csv", "error",
    ]
    for c in col_order:
        if c not in df.columns:
            df[c] = None
    df = df[col_order]

    df.to_csv(out_csv, index=False)
    return str(out_csv)
