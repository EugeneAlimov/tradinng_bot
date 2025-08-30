# src/backtest/execution.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np


@dataclass
class ExecConfig:
    """Параметры исполнения сделок в бэктесте."""
    size: float = 1.0  # количество базовой валюты (например, 100 DOGE)
    fees_bps: float = 0.0  # комиссия в б.п. (25 bps = 0.25%)
    slippage_bps: float = 0.0  # проскальзывание в б.п. на каждую сторону (вход/выход)


def _bps(value: float) -> float:
    return float(value) / 10_000.0


def _apply_side_costs(px: float, fees_bps: float, slippage_bps: float, is_entry: bool) -> Tuple[float, float]:
    """
    Возвращает (effective_px, fee_quote). Предполагаем рыночные сделки (taker).
    Проскальзывание моделируем как увеличение цены для покупок и уменьшение для продаж.
    Комиссия берётся как % от notional.
    """
    px_eff = float(px)

    # Проскальзывание: вход (покупка long) дороже, выход (продажа) дешевле.
    s = _bps(slippage_bps)
    if is_entry:
        px_eff *= (1.0 + s)
    else:
        px_eff *= (1.0 - s)

    # Комиссия (в quote), считается от фактического исполненного notional
    fee = px_eff * _bps(fees_bps)
    return px_eff, fee


def enrich_trades_with_costs(
        trades: Iterable[Dict[str, Any]],
        cfg: ExecConfig,
) -> List[Dict[str, Any]]:
    """
    Принимает сделки с полями: entry_px, exit_px, (опц.) entry_ts/exit_ts, и т.п.
    Возвращает новые сделки, дополненные полями:
      - entry_px_eff / exit_px_eff
      - fee_entry / fee_exit (в quote)
      - pnl_gross (на 1 единицу базовой валюты)
      - pnl_net   (на 1 единицу базовой валюты)
      - pnl_gross_notional / pnl_net_notional  (с учётом размера cfg.size)
    """
    out: List[Dict[str, Any]] = []
    for t in trades:
        # пропускаем незакрытые
        if "entry_px" not in t or "exit_px" not in t:
            out.append(dict(t))
            continue

        e_px = float(t["entry_px"])
        x_px = float(t["exit_px"])

        e_eff, fee_e = _apply_side_costs(e_px, cfg.fees_bps, cfg.slippage_bps, is_entry=True)
        x_eff, fee_x = _apply_side_costs(x_px, cfg.fees_bps, cfg.slippage_bps, is_entry=False)

        pnl_gross = float(x_px - e_px)
        pnl_net = float(x_eff - e_eff) - (fee_e + fee_x)

        size = float(cfg.size)
        t_en = dict(t)
        t_en.update(
            {
                "size": size,
                "fees_bps": float(cfg.fees_bps),
                "slippage_bps": float(cfg.slippage_bps),
                "entry_px_eff": e_eff,
                "exit_px_eff": x_eff,
                "fee_entry": fee_e * size,
                "fee_exit": fee_x * size,
                "pnl_gross": pnl_gross,
                "pnl_net": pnl_net,
                "pnl_gross_notional": pnl_gross * size,
                "pnl_net_notional": pnl_net * size,
            }
        )
        out.append(t_en)
    return out


def pnls_from_trades(
        trades: Iterable[Dict[str, Any]],
        use_net: bool = True,
        size_field: str = "size",
) -> np.ndarray:
    """
    Извлекает массив pnl из enriched-сделок.
    По умолчанию возвращает pnl_net_notional; если нет, пытается собрать из полей сделки.
    """
    vals: List[float] = []
    for t in trades:
        if use_net:
            v = t.get("pnl_net_notional")
            if v is not None:
                vals.append(float(v))
                continue
            # если не обогащали — посчитаем на лету по базовым полям
            if "entry_px_eff" in t and "exit_px_eff" in t:
                fee_e = float(t.get("fee_entry", 0.0))
                fee_x = float(t.get("fee_exit", 0.0))
                size = float(t.get(size_field, 1.0))
                pnl = (float(t["exit_px_eff"]) - float(t["entry_px_eff"])) * size - (fee_e + fee_x)
                vals.append(pnl)
                continue

        # fallback: bruto * size
        if "pnl" in t:
            size = float(t.get(size_field, 1.0))
            vals.append(float(t["pnl"]) * size)
    return np.asarray(vals, dtype=float)


def equity_curve(pnls: np.ndarray) -> np.ndarray:
    """Кумулятивная доходность (equity)."""
    return np.cumsum(pnls) if pnls.size else np.asarray([], dtype=float)
