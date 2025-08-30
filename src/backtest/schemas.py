# src/backtest/schemas.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


def _typename(v: Any) -> str:
    if v is None:
        return "null"
    t = type(v)
    if t in (int,):
        return "int"
    if t in (float,):
        return "float"
    if t in (bool,):
        return "bool"
    if t in (str,):
        return "str"
    if isinstance(v, (list, tuple)):
        return "array"
    if isinstance(v, dict):
        return "object"
    return t.__name__


# краткие описания известных полей
_FIELD_DOCS: Dict[str, str] = {
    "trade_id": "Сквозной ID сделки (int, начинается с 1)",
    "side": "Направление сделки (строка: 'long')",
    "entry_bar_idx": "Индекс бара входа в исходном DataFrame",
    "exit_bar_idx": "Индекс бара выхода в исходном DataFrame",
    "entry_ts": "Unix-время входа (сек, UTC)",
    "exit_ts": "Unix-время выхода (сек, UTC)",
    "entry_dt": "ISO8601 время входа (UTC)",
    "exit_dt": "ISO8601 время выхода (UTC)",
    "entry_px": "Цена входа (close бара входа)",
    "exit_px": "Цена выхода",
    "entry_reason": "Причина входа (например, ema_fast>ema_slow+adx=..)",
    "exit_reason": "Причина выхода (ema_cross_down / weak_trend / adx_off / sl_hit / trail_hit / tp1_hit / tp2_hit / tp_hit / close_on_last_bar)",
    "bars_held": "Время удержания позиции в барах",
    "hold_seconds": "Время удержания позиции в секундах",
    "qty_frac": "Доля позиции, закрытая этой сделкой (0..1). Если отсутствует — 1.0",
    "pnl": "Результат сделки в базовых единицах (до комиссий/проскальзывания); с учётом qty_frac, если он был",
    "size": "Размер позиции (в базовой валюте) после учёта qty_frac",
    "fees_bps": "Комиссия в б.п.",
    "slippage_bps": "Проскальзывание в б.п. на сторону",
    "entry_px_eff": "Эффективная цена входа с проскальзыванием",
    "exit_px_eff": "Эффективная цена выхода с проскальзыванием",
    "fee_entry": "Комиссия на вход (в quote), умноженная на size",
    "fee_exit": "Комиссия на выход (в quote), умноженная на size",
    "pnl_gross": "P&L за сделку на 1 базовую единицу (до комиссий/проскальзывания)",
    "pnl_net": "P&L за сделку на 1 базовую единицу (после комиссий/проскальзывания)",
    "pnl_gross_notional": "P&L за сделку * size (до комиссий/проскальзывания)",
    "pnl_net_notional": "P&L за сделку * size (после комиссий/проскальзывания)",
}


def build_trades_schema(trades: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Собирает схему журнала: перечень возможных полей, их наблюдаемые типы и краткие описания.
    """
    keys: List[str] = []
    sample_types: Dict[str, str] = {}
    for t in trades:
        for k, v in t.items():
            if k not in sample_types:
                sample_types[k] = _typename(v)
            if k not in keys:
                keys.append(k)

    fields: List[Dict[str, Any]] = []
    for k in keys:
        fields.append(
            {
                "name": k,
                "dtype": sample_types.get(k, "unknown"),
                "doc": _FIELD_DOCS.get(k, ""),
            }
        )

    return {
        "schema_version": "trades.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
    }
