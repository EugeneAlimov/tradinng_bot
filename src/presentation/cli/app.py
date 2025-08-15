# src/presentation/cli/app.py
from __future__ import annotations
import argparse
import os
import logging
from typing import Optional

from ...infrastructure.exchange.exmo_api import ExmoApi

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

def run_cli():
    parser = argparse.ArgumentParser(prog="exmo-bot", description="EXMO trading bot CLI")
    parser.add_argument("--mode", choices=["paper", "live", "hybrid", "legacy"], default="paper")
    parser.add_argument("--validate", action="store_true", help="Validate config and exit")
    parser.add_argument("--exmo-debug", action="store_true", help="Enable verbose EXMO HTTP trace")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    parser.add_argument("--pair", default=os.getenv("EXMO_PAIR", "DOGE_EUR"))
    parser.add_argument("--resolution", type=int, default=1)
    parser.add_argument("--from-ts", type=int, default=0)
    parser.add_argument("--to-ts", type=int, default=0)
    args = parser.parse_args()

    # Логи
    setup_logging(args.log_level)

    # EXMO_DEBUG переключатель (совместим с переменной окружения)
    if args.exmo_debug:
        os.environ["EXMO_DEBUG"] = "1"

    if args.validate:
        logging.info("Validation OK (stub). ENV keys: EXMO_API_KEY=%s, EXMO_API_SECRET=%s",
                     "set" if os.getenv("EXMO_API_KEY") else "missing",
                     "set" if os.getenv("EXMO_API_SECRET") else "missing")
        return

    # Пример «probe» вызова свечей (замена _exmo_probe)
    if args.from_ts and args.to_ts:
        api = ExmoApi()
        data = api.candles_history(args.pair, args.resolution, args.from_ts, args.to_ts)
        logging.info("Candles fetched: keys=%s", list(data.keys()))
        # здесь можно распечатать несколько первых свечей/метаданных
        return

    logging.info("Run mode=%s (entry point). Подключи сюда запуск основного бота.", args.mode)
