# -*- coding: utf-8 -*-
"""
walk-forward: валидация с фиксированными параметрами стратегии.
Добавлено:
- флаги --ema-fast/--ema-slow и их прокидка в WFConfig
"""

from __future__ import annotations


def register(subparsers):
    sub = subparsers.add_parser(
        "walk-forward",
        help="Walk-forward валидация для фиксированных параметров стратегии",
    )
    sub.add_argument("--pair", type=str, help="Пара, напр. BTC_EUR")
    sub.add_argument("--exmo-pair", dest="exmo_pair", type=str, help="Пара EXMO, напр. BTC_EUR")
    sub.add_argument("--candles", type=str, help="Правило загрузки свечей, напр. 1m:5000")
    sub.add_argument("--exmo-candles", dest="exmo_candles", type=str, help="Правило загрузки EXMO, напр. 1m:5000")
    sub.add_argument("--resample", type=str, default="5m")
    sub.add_argument("--folds", type=int, default=4)

    # НОВОЕ: явная передача EMA параметров
    sub.add_argument("--ema-fast", type=int, default=10, help="быстрая EMA")
    sub.add_argument("--ema-slow", type=int, default=20, help="медленная EMA")

    sub.set_defaults(_handler=_handle_walk_forward)
    return sub


def _handle_walk_forward(args):
    from src.backtest.walkforward import WFConfig, run_walkforward

    pair = args.exmo_pair or args.pair
    span = args.exmo_candles or args.candles
    if not pair or not span:
        raise SystemExit("нужны --exmo-pair/--pair и --exmo-candles/--candles")

    cfg = WFConfig(
        pair=pair,
        span=span,
        resample=args.resample,
        fast=args.ema_fast,
        slow=args.ema_slow,
        folds=args.folds,
        # если у WFConfig есть доп.поля (fee/slip/min_train_bars/etc) — оставьте их умолчаниями
    )
    return run_walkforward(cfg, print_json=True)
