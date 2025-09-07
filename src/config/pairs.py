# src/config/pairs.py
from __future__ import annotations

import os
from typing import Iterable, Tuple


def _normalize_pair(s: str) -> str:
    """
    Приводим разные форматы к EXMO-формату: 'DOGE_EUR'
    Поддерживаем: 'DOGE_EUR', 'DOGE/EUR', 'DOGE-EUR', 'DOGE EUR'
    """
    t = s.strip().upper().replace("/", "_").replace("-", "_").replace(" ", "_")
    # уберём возможные двойные подчёркивания
    t = "_".join([x for x in t.split("_") if x])
    return t


def normalize_pairs(pairs: Iterable[str]) -> Tuple[str, ...]:
    out = []
    for p in pairs:
        if not p:
            continue
        out.append(_normalize_pair(p))
    # dedupe preserving order
    seen = set()
    uniq = []
    for p in out:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return tuple(uniq)


def parse_pairs_from_env() -> Tuple[str, ...]:
    """
    1) Если есть TRADE_PAIRS="DOGE_EUR,BTC_EUR" — используем его.
    2) Иначе используем TRADING_PAIR_1/TRADING_PAIR_2 (по умолчанию DOGE/EUR).
    """
    tp = os.getenv("TRADE_PAIRS")
    if tp:
        raw = [x.strip() for x in tp.split(",")]
        return normalize_pairs(raw)

    a = os.getenv("TRADING_PAIR_1", "DOGE").strip()
    b = os.getenv("TRADING_PAIR_2", "EUR").strip()
    return normalize_pairs([f"{a}_{b}"])
