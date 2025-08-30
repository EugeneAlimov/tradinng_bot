# src/backtest/execution.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

import numpy as np


@dataclass
class ExecConfig:
    size: float = 1.0  # базовая позиция (в базовой валюте)
    fees_bps: float = 0.0  # комиссия на сторону, в б.п.
    slippage_bps: float = 0.0  # проскальзывание на сторону, в б.п.


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def enrich_trades_with_costs(trades: List[Dict[str, Any]], cfg: ExecConfig) -> List[Dict[str, Any]]:
    """
    Обогащает сделки стоимостями исполнения.
    Если сделка содержит 'qty_frac', реальный размер = cfg.size * qty_frac.
    Поля:
      - entry_px_eff / exit_px_eff
      - fee_entry / fee_exit
      - pnl_gross / pnl_net   (на 1 базовую ед.)
      - size                  (реальный размер)
      - pnl_gross_notional / pnl_net_notional
    """
    f = float(cfg.fees_bps) / 10_000.0
    s = float(cfg.slippage_bps) / 10_000.0

    out: List[Dict[str, Any]] = []
    for t in trades:
        if "exit_px" not in t or "entry_px" not in t:
            out.append(t)
            continue

        qty_frac = _to_float(t.get("qty_frac", 1.0), 1.0)
        size = float(cfg.size) * max(0.0, qty_frac)

        entry_px = _to_float(t["entry_px"])
        exit_px = _to_float(t["exit_px"])

        # slippage: покупка дороже, продажа дешевле
        entry_px_eff = entry_px * (1.0 + s)
        exit_px_eff = exit_px * (1.0 - s)

        fee_entry = f * entry_px_eff * size
        fee_exit = f * exit_px_eff * size

        pnl_gross_per_unit = exit_px - entry_px
        pnl_net_per_unit = (exit_px_eff - entry_px_eff) - (fee_entry + fee_exit) / (size if size > 0 else 1.0)

        t = dict(t)  # copy-on-write
        t.update(
            {
                "size": size,
                "fees_bps": float(cfg.fees_bps),
                "slippage_bps": float(cfg.slippage_bps),
                "entry_px_eff": entry_px_eff,
                "exit_px_eff": exit_px_eff,
                "fee_entry": fee_entry,
                "fee_exit": fee_exit,
                "pnl_gross": pnl_gross_per_unit,
                "pnl_net": pnl_net_per_unit,
                "pnl_gross_notional": pnl_gross_per_unit * size,
                "pnl_net_notional": pnl_net_per_unit * size,
            }
        )
        out.append(t)
    return out


def pnls_from_trades(trades: Iterable[Dict[str, Any]], *, use_net: bool = True) -> np.ndarray:
    """
    Возвращает вектор PnL по сделкам:
      - если есть *_notional поля — берём их;
      - иначе берём per-unit (net|gross) * (qty_frac или 1.0).
    """
    vals: List[float] = []
    for t in trades:
        if use_net and "pnl_net_notional" in t:
            vals.append(_to_float(t["pnl_net_notional"]))
        elif (not use_net) and "pnl_gross_notional" in t:
            vals.append(_to_float(t["pnl_gross_notional"]))
        else:
            frac = _to_float(t.get("qty_frac", 1.0), 1.0)
            if use_net and "pnl_net" in t:
                vals.append(_to_float(t["pnl_net"]) * frac)
            elif "pnl_gross" in t:
                vals.append(_to_float(t["pnl_gross"]) * frac)
            elif "pnl" in t:
                vals.append(_to_float(t["pnl"]))  # уже может быть с frac
    return np.asarray(vals, dtype=float)
