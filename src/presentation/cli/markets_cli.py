# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from src.exchanges.exmo.market_meta import load_from_file, MarketInfo
from src.domain.market_universe import UniverseFilter, suggest_pairs, to_rows


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tb-markets",
        description="Показать доступные торговые пары EXMO под заданный бюджет.",
    )
    p.add_argument(
        "--file",
        required=True,
        help="Путь к тексту с парами и лимитами (например, 'Пары и лимиты для EXMO.txt').",
    )
    p.add_argument("--budget", type=float, required=True, help="Сумма бюджета.")
    p.add_argument("--currency", required=True, help="Валюта бюджета, напр. EUR/USDT/USD/USDC.")
    p.add_argument("--max-fee", type=float, default=None, help="Максимально допустимая комиссия в %, напр. 0.3.")
    p.add_argument("--include", nargs="*", default=None,
                   help="Список базовых активов, которые включать (например: DOGE BTC).")
    p.add_argument("--exclude", nargs="*", default=None, help="Список базовых активов, которые исключать.")
    p.add_argument("--top", type=int, default=20, help="Показать первые N результатов после сортировки.")
    p.add_argument("--json-out", default=None, help="Если задано — сохранить итог в JSON по указанному пути.")
    p.add_argument("--no-table", action="store_true", help="Не печатать таблицу в консоль.")
    return p


def _print_table(markets: List[MarketInfo]) -> None:
    if not markets:
        print("Нет подходящих пар под заданные условия.")
        return
    # компактная табличка
    print(f"{'PAIR':<16} {'BASE':<8} {'QUOTE':<8} {'MIN_SUM':>10} {'MIN_QTY':>10} {'FEE,%':>7}")
    print("-" * 60)
    for m in markets:
        print(f"{m.pair:<16} {m.base:<8} {m.quote:<8} {m.min_sum:>10.4f} {m.min_qty:>10.6f} {m.fee_pct:>7.3f}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = _build_parser()
    ns = ap.parse_args(argv)

    markets = load_from_file(ns.file)
    uf = UniverseFilter(
        budget_quote_ccy=ns.currency,
        budget_amount=ns.budget,
        max_fee_pct=ns.max_fee,
        include_assets=ns.include,
        exclude_assets=ns.exclude,
    )
    picked = suggest_pairs(markets, uf, top=ns.top)

    if not ns.no_table:
        _print_table(picked)

    if ns.json_out:
        out_path = Path(ns.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "budget": {"amount": ns.budget, "currency": ns.currency},
            "filters": {
                "max_fee_pct": ns.max_fee,
                "include": ns.include,
                "exclude": ns.exclude,
            },
            "count": len(picked),
            "pairs": to_rows(picked),
        }
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"Saved JSON: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
