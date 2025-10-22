# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Dict, Any, Tuple

from src.exchanges.exmo.market_meta import MarketInfo


@dataclass
class UniverseFilter:
    budget_quote_ccy: str  # валюта баланса, например "EUR"
    budget_amount: float  # доступная сумма, например 20.44
    max_fee_pct: Optional[float] = None  # например 0.3 (если None — без фильтра)
    include_assets: Optional[List[str]] = None  # список базовых монет, которые хотим (DOGE, BTC, ...)
    exclude_assets: Optional[List[str]] = None  # исключения


def suggest_pairs(
        markets: Iterable[MarketInfo],
        uf: UniverseFilter,
        top: Optional[int] = None,
) -> List[MarketInfo]:
    """
    Фильтрует и сортирует пары под бюджет.
    Правила:
      - котировка пары должна совпадать с валютой бюджета (quote == budget_quote_ccy)
      - min_sum <= budget_amount
      - fee_pct <= max_fee_pct (если задан)
      - include/exclude по базовым активам
    Сортировка: по fee_pct ASC, затем по min_sum ASC, затем по pair ASC.
    """
    inc = set(x.upper() for x in (uf.include_assets or []))
    exc = set(x.upper() for x in (uf.exclude_assets or []))

    def _ok(mi: MarketInfo) -> bool:
        if mi.quote.upper() != uf.budget_quote_ccy.upper():
            return False
        if mi.min_sum > uf.budget_amount:
            return False
        if uf.max_fee_pct is not None and mi.fee_pct > uf.max_fee_pct:
            return False
        if inc and mi.base.upper() not in inc:
            return False
        if mi.base.upper() in exc:
            return False
        return True

    filtered = [mi for mi in markets if _ok(mi)]
    filtered.sort(key=lambda x: (x.fee_pct, x.min_sum, x.pair))
    if top is not None:
        filtered = filtered[:top]
    return filtered


def to_rows(markets: Iterable[MarketInfo]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for mi in markets:
        rows.append(
            {
                "pair": mi.pair,
                "base": mi.base,
                "quote": mi.quote,
                "min_sum": mi.min_sum,
                "min_qty": mi.min_qty,
                "fee_pct": mi.fee_pct,
                "fee_fraction": mi.fee_fraction,
            }
        )
    return rows
