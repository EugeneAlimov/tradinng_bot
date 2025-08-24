#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Команда CLI: trade-live — безопасный запуск "живой" торговли.

Интеграция сделана модульно: этот файл ничего не меняет в существующем CLI.
Чтобы подключить команду к вашему текущему main.py, добавьте:
    from src.presentation.cli.trade_live_cmd import register_trade_live

и вызовите:
    register_trade_live(subparsers)

где `subparsers` — результат parser.add_subparsers(dest="command").

Команда опирается на:
- ImprovedExmoPrivate / ExmoPrivate (что найдётся)
- SafeExmoWrapper и ExchangeDataValidator (если есть)
- ImprovedOrderManager (если есть)
- ThreadSafeNonceManager (если есть)
- настройки из src.config.settings (ENV/.env/YAML)
"""

from __future__ import annotations

import argparse
import inspect
import logging
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _import_optional(path: str):
    """Безопасный импорт модуля по dotted-path."""
    try:
        module = __import__(path, fromlist=["*"])
        return module
    except Exception as e:
        logger.debug("Optional import failed for %s: %s", path, e)
        return None


def _build_exchange_stack(settings) -> Dict[str, Any]:
    """
    Собирает стек обмена:
      - экзотики нет: пытаемся взять ImprovedExmoPrivate, иначе ExmoPrivate
      - оборачиваем SafeExmoWrapper при наличии
      - создаём ImprovedOrderManager при наличии
    """
    # 1) EXMO client (improved -> fallback)
    exmo_mod = _import_optional("src.integrations.exmo_private")
    exmo_client = None

    if exmo_mod is not None:
        cls = getattr(exmo_mod, "ImprovedExmoPrivate", None) or getattr(exmo_mod, "ExmoPrivate", None)
        if cls is not None:
            exmo_client = cls(
                api_key=settings.exmo_api_key or "",
                api_secret=settings.exmo_api_secret or "",
                base_url=settings.exmo_base_url or "https://api.exmo.com/v1.1",
                timeout=getattr(settings, "exmo_timeout", 20),
            )

    if exmo_client is None:
        raise RuntimeError("Не удалось инициализировать EXMO клиент (нет ExmoPrivate/ImprovedExmoPrivate).")

    # 2) Wrap with validator if present
    safe_wrapper = None
    validator_mod = _import_optional("src.infrastructure.exchange.validator")
    if validator_mod is not None:
        SafeExmoWrapper = getattr(validator_mod, "SafeExmoWrapper", None)
        if SafeExmoWrapper is not None:
            safe_wrapper = SafeExmoWrapper(exmo_client)

    # 3) Order manager (client_id uniqueness & retries)
    order_manager = None
    om_mod = _import_optional("src.infrastructure.exchange.order_manager")
    if om_mod is not None:
        ImprovedOrderManager = getattr(om_mod, "ImprovedOrderManager", None)
        if ImprovedOrderManager is not None:
            # Менеджеру передаём либо safe_wrapper, либо сырой exmo_client
            order_manager = ImprovedOrderManager(safe_wrapper or exmo_client)

    return {
        "exmo": exmo_client,
        "safe": safe_wrapper,
        "order_manager": order_manager,
    }


def _call_run_live_trade(pair: str,
                         max_notional_eur: float,
                         maker: bool,
                         iterations: int,
                         tick_ms: int,
                         settings) -> int:
    """
    Вызывает run_live_trade из src.presentation.live_trade безопасно:
      - передаём только те kwargs, которые реально есть в сигнатуре функции
    """
    live_mod = _import_optional("src.presentation.live_trade")
    if live_mod is None:
        raise RuntimeError("Модуль src.presentation.live_trade не найден.")

    run_fn = getattr(live_mod, "run_live_trade", None)
    if run_fn is None or not callable(run_fn):
        raise RuntimeError("Функция run_live_trade не найдена в src.presentation.live_trade.")

    # Собираем зависимости
    stack = _build_exchange_stack(settings)

    # Базовые аргументы по ТЗ
    payload: Dict[str, Any] = dict(
        pair=pair,
        max_notional_eur=max_notional_eur,
        maker=maker,
        iterations=iterations,
        tick_ms=tick_ms,
        exchange=(stack["safe"] or stack["exmo"]),
        order_manager=stack["order_manager"],
        settings=settings,
    )

    # Оставляем только те kwargs, которые реально принимает run_live_trade
    sig = inspect.signature(run_fn)
    accepted = {k: v for k, v in payload.items() if k in sig.parameters}

    logger.info("Запуск live trading: %s", {k: accepted[k] for k in sorted(accepted.keys())})

    result = run_fn(**accepted)
    # Если функция ничего не возвращает — считаем успехом
    return int(result) if isinstance(result, int) else 0


def register_trade_live(subparsers: argparse._SubParsersAction) -> None:
    """
    Регистрирует подкоманду `trade-live` на общем парсере (subparsers).
    """
    from src.config.settings import load_settings

    cmd = subparsers.add_parser(
        "trade-live",
        help="Запуск безопасной 'живой' торговли с валидацией, уникальными client_id и ретраями.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    cmd.add_argument("--exmo-pair", dest="exmo_pair", required=True, type=str,
                     help="Пара EXMO, например DOGE_EUR")
    cmd.add_argument("--max-notional-eur", dest="max_notional_eur", type=float, default=100.0,
                     help="Лимит позиции в EUR (notional)")
    cmd.add_argument("--maker", dest="maker", action="store_true", default=True,
                     help="Размещать лимитные ордера (maker). Для отключения — добавьте --no-maker")
    cmd.add_argument("--no-maker", dest="maker", action="store_false",
                     help="Размещать как taker (по рынку/агрессивно)")
    cmd.add_argument("--iterations", dest="iterations", type=int, default=0,
                     help="Сколько итераций цикла сделать (0 — бесконечно)")
    cmd.add_argument("--tick-ms", dest="tick_ms", type=int, default=1000,
                     help="Пауза между тиками цикла, мс")

    def _handler(args: argparse.Namespace) -> None:
        settings = load_settings()  # читаем ENV/.env/YAML
        exit_code = _call_run_live_trade(
            pair=str(args.exmo_pair),
            max_notional_eur=float(args.max_notional_eur),
            maker=bool(args.maker),
            iterations=int(args.iterations),
            tick_ms=int(args.tick_ms),
            settings=settings,
        )
        sys.exit(exit_code)

    cmd.set_defaults(func=_handler)
