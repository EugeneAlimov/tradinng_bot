# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Dict, Any

_LINE_RE = re.compile(
    r"""
    ^\s*(?:✅\s*)?                # галочка может быть
    (?P<pair>[A-Z0-9_]+)          # символ пары, напр. DOGE_EUR
    \s*\|\s*Мин\.сумма:\s*(?P<min_sum>[0-9.]+)
    \s*\|\s*Мин\.кол-во:\s*(?P<min_qty>[0-9.]+)
    \s*\|\s*Комиссия:\s*(?P<fee_pct>[0-9.]+)%
    """,
    re.X,
)


@dataclass(frozen=True)
class MarketInfo:
    pair: str  # e.g. "DOGE_EUR"
    base: str  # DOGE
    quote: str  # EUR
    min_sum: float  # минимальная НОМИНАЛЬНАЯ сумма ордера в валюте котировки (из "Мин.сумма")
    min_qty: float  # минимальное количество базового актива (из "Мин.кол-во")
    fee_pct: float  # процент комиссии, например 0.3 -> 0.3%

    @property
    def fee_fraction(self) -> float:
        return self.fee_pct / 100.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["fee_fraction"] = self.fee_fraction
        return d


def _parse_line(line: str) -> Optional[MarketInfo]:
    m = _LINE_RE.search(line)
    if not m:
        return None
    pair = m.group("pair").strip()
    if "_" not in pair:
        return None
    base, quote = pair.split("_", 1)
    return MarketInfo(
        pair=pair,
        base=base,
        quote=quote,
        min_sum=float(m.group("min_sum")),
        min_qty=float(m.group("min_qty")),
        fee_pct=float(m.group("fee_pct")),
    )


def load_from_text(text: str) -> List[MarketInfo]:
    """
    Парсит весь текст целиком и возвращает список MarketInfo.
    Пропускает любые разделы/заголовки, извлекает только строки с парами.
    """
    out: List[MarketInfo] = []
    for line in text.splitlines():
        mi = _parse_line(line)
        if mi:
            out.append(mi)
    # Уникализируем по pair (на случай повторов)
    uniq: Dict[str, MarketInfo] = {mi.pair: mi for mi in out}
    return list(uniq.values())


def load_from_file(path: str | Path, encoding: str = "utf-8") -> List[MarketInfo]:
    p = Path(path)
    text = p.read_text(encoding=encoding, errors="ignore")
    return load_from_text(text)
