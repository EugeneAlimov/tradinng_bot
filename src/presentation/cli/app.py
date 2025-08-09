from __future__ import annotations

import argparse
import time
import json
from decimal import Decimal
from typing import Optional, Dict, Any

from src.config.settings import get_settings
from src.core.domain.models import TradingPair
from src.infrastructure.market.random_walk import RandomWalkMarket
from src.infrastructure.exchange.paper_exchange import PaperExchange
from src.infrastructure.storage.files import FileStorage
from src.infrastructure.notify.log import LogNotifier
from src.application.engine.trade_engine import TradeEngine

# Стратегии
from src.domain.strategy.sma_crossover import SmaCrossover, SmaCfg
from src.domain.strategy.mean_reversion import MeanReversion  # запасной вариант

# Сервисы домена
from src.domain.risk.risk_service import RiskService
from src.domain.portfolio.position_service import PositionService

# EXMO read-only клиент
from src.infrastructure.exchange.exmo_api import ExmoApi, ExmoCredentials


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clean-crypto-bot", description="Simple paper-trading bot (DOGE_EUR)")

    # ===== Основной режим (paper loop) =====
    p.add_argument("--mode", choices=["paper"], default="paper", help="Рабочий режим (пока только paper)")
    p.add_argument("--symbol", default=None, help="Пара вида BASE_QUOTE (пример: DOGE_EUR)")
    p.add_argument("--ticks", type=int, default=1, help="Сколько тиков выполнить")
    p.add_argument("--interval", type=float, default=1.0, help="Пауза между тиками, сек")

    # Рынок (random-walk)
    p.add_argument("--start-price", type=str, default="0.1", help="Начальная цена для random-walk")
    p.add_argument("--drift-bps", type=float, default=0.0, help="Дрейф в б.п. на тик")
    p.add_argument("--vol-bps", type=float, default=20.0, help="Волатильность (σ) в б.п. на тик")
    p.add_argument("--rw-seed", type=int, default=None, help="Seed генератора случайностей")
    p.add_argument("--tick-seconds", type=int, default=1, help="«Длительность» одного тика в секундах (логическая)")

    # Стратегия
    p.add_argument("--strategy", choices=["sma", "mr"], default="sma",
                   help="Стратегия: sma (по умолчанию) или mr (mean reversion-заглушка)")
    p.add_argument("--tf", default="1m", help="Таймфрейм свечей для стратегии")
    p.add_argument("--fast", type=int, default=10, help="Длина быстрой SMA")
    p.add_argument("--slow", type=int, default=30, help="Длина медленной SMA")
    p.add_argument("--min-gap-bps", type=str, default="2",
                   help="Минимальный зазор между SMA в б.п. для подтверждения сигнала")

    p.add_argument("--validate", action="store_true", help="Проверка сборки без запуска цикла")

    # ===== EXMO probe (read-only, безопасно) =====
    ex = p.add_argument_group("EXMO probe (read-only)")
    ex.add_argument("--exmo-ping", action="store_true", help="Проверить доступность EXMO API")
    ex.add_argument("--exmo-ticker", action="store_true", help="Получить общий тикер по всем парам")
    ex.add_argument("--exmo-ticker-pair", type=str, default=None, help="Тикер конкретной пары, напр. DOGE_EUR")
    ex.add_argument("--exmo-order-book", type=int, default=0, metavar="LIMIT",
                    help="Стакан по --symbol (или --exmo-ticker-pair), LIMIT записей (0=пропустить)")
    ex.add_argument("--exmo-trades", type=int, default=0, metavar="LIMIT",
                    help="Последние сделки по паре, LIMIT записей (0=пропустить)")
    ex.add_argument("--exmo-balances", action="store_true", help="Мои балансы (read-only)")
    ex.add_argument("--exmo-open-orders", action="store_true", help="Мои открытые ордера (read-only)")
    ex.add_argument("--exmo-user-trades", type=int, default=0, metavar="LIMIT",
                    help="Моя история сделок по паре, LIMIT записей (0=пропустить)")
    ex.add_argument("--dump-json", type=str, default=None,
                    help="Путь для JSON-дампа результата EXMO probe (например, data/exmo_probe.json)")

    return p


def _build_paper_components(args) -> tuple[TradingPair, TradeEngine, RandomWalkMarket, PaperExchange]:
    settings = get_settings()
    symbol = args.symbol or settings.default_pair or "DOGE_EUR"
    try:
        base, quote = symbol.split("_", 1)
    except ValueError:
        raise SystemExit("Некорректный --symbol, ожидается формат BASE_QUOTE, пример: DOGE_EUR")
    pair = TradingPair(base=base, quote=quote)

    notifier = LogNotifier()
    storage = FileStorage(path=settings.storage_path)

    market = RandomWalkMarket(
        start_price=Decimal(args.start_price),
        drift_bps=args.drift_bps,
        vol_bps=args.vol_bps,
        seed=args.rw_seed,
        tick_seconds=args.tick_seconds,
    )

    ex = PaperExchange.with_quote_funds(
        market=market,
        quote_asset=quote,
        amount=Decimal("10000"),
        spread_bps=10,
        slippage_bps=5,
    )

    if args.strategy == "sma":
        strat = SmaCrossover(
            cfg=SmaCfg(
                timeframe=args.tf,
                fast=args.fast,
                slow=args.slow,
                min_gap_bps=Decimal(args.min_gap_bps),
            )
        )
        candles_tf = args.tf
        lookback = max(args.fast, args.slow) + 2
    else:
        strat = MeanReversion()
        candles_tf = "1m"
        lookback = 60

    risk = RiskService(get_settings().risk)
    positions = PositionService(storage=storage)

    engine = TradeEngine(
        market=market,
        exchange=ex,
        storage=storage,
        notifier=notifier,
        strategy=strat,
        positions=positions,
        risk=risk,
        candles_timeframe=candles_tf,
        candles_lookback=lookback,
    )
    return pair, engine, market, ex


def _exmo_probe(args) -> int:
    """
    Безопасные зондирующие вызовы EXMO API (read-only).
    Возвращает 0 при успехе, 1 при ошибке.
    """
    s = get_settings()
    creds = ExmoCredentials(api_key=s.api_key, api_secret=s.api_secret)
    api = ExmoApi(creds=creds, allow_trading=False)

    # Выберем пару для зондов
    pair = args.exmo_ticker_pair or args.symbol or s.default_pair or "DOGE_EUR"

    result: Dict[str, Any] = {"pair": pair}

    try:
        if args.exmo_ping:
            ok = api.ping()
            print(f"EXMO ping: {'OK' if ok else 'FAIL'}")
            result["ping"] = ok

        if args.exmo_ticker:
            tk = api.ticker()
            print(f"EXMO ticker: {len(tk) if isinstance(tk, dict) else 'n/a'} pairs")
            result["ticker"] = tk

        if args.exmo_ticker_pair:
            tpk = api.ticker_pair(pair)
            print(f"EXMO ticker[{pair}]: {tpk}")
            result["ticker_pair"] = tpk

        if args.exmo_order_book and args.exmo_order_book > 0:
            ob = api.order_book(pair, limit=args.exmo_order_book)
            top = list(ob.get(pair, {}).items())[:2] if isinstance(ob, dict) else []
            print(f"EXMO order_book[{pair}] top keys: {top}")
            result["order_book"] = ob

        if args.exmo_trades and args.exmo_trades > 0:
            tr = api.trades(pair, limit=args.exmo_trades)
            print(f"EXMO trades[{pair}]: {len(tr)} items")
            result["trades"] = tr

        if args.exmo_balances:
            bals = api.user_balances()
            print(f"EXMO balances: { {k: str(v) for k,v in bals.items()} }")
            result["balances"] = {k: str(v) for k, v in bals.items()}

        if args.exmo_open_orders:
            oo = api.user_open_orders(pair)
            print(f"EXMO open_orders[{pair}]: {oo}")
            result["open_orders"] = oo

        if args.exmo_user_trades and args.exmo_user_trades > 0:
            ut = api.user_trades(pair, limit=args.exmo_user_trades)
            print(f"EXMO user_trades[{pair}]: {len(ut)} items")
            result["user_trades"] = ut

        # Если задан дамп — сохраняем
        if args.dump_json:
            try:
                with open(args.dump_json, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2, default=str)
                print(f"→ JSON saved to: {args.dump_json}")
            except Exception as e:
                print(f"⚠️  Не удалось сохранить JSON: {e!r}")

        # Если ни одна из опций probe не была задана — сообщим пользователю
        if (
            not args.exmo_ping and
            not args.exmo_ticker and
            not args.exmo_ticker_pair and
            not args.exmo_order_book and
            not args.exmo_trades and
            not args.exmo_balances and
            not args.exmo_open_orders and
            not args.exmo_user_trades
        ):
            print("Нет выбранных действий EXMO probe. Укажи хотя бы один флаг из группы EXMO.")
            return 1

        return 0
    except Exception as e:
        print(f"❌ EXMO probe error: {e!r}")
        return 1


def run_cli() -> None:
    args = _build_parser().parse_args()

    # --- Ветка EXMO-probe (read-only, безопасная) ---
    if (
        args.exmo_ping or args.exmo_ticker or args.exmo_ticker_pair or
        (args.exmo_order_book and args.exmo_order_book > 0) or
        (args.exmo_trades and args.exmo_trades > 0) or
        args.exmo_balances or args.exmo_open_orders or
        (args.exmo_user_trades and args.exmo_user_trades > 0)
    ):
        code = _exmo_probe(args)
        raise SystemExit(code)

    # --- Обычный paper-режим ---
    if args.mode != "paper":
        raise SystemExit("Пока доступен только --mode paper")

    pair, engine, market, ex = _build_paper_components(args)

    if args.validate:
        price = market.get_price(pair)
        _ = ex.get_price(pair)
        print("✅ Validation OK")
        print(f"  Pair: {pair.symbol()}")
        print(f"  Price: {price}")
        print(f"  Strategy: {'SMA' if args.strategy=='sma' else 'MeanReversion(HOLD)'}")
        return

    ticks = max(1, int(args.ticks))
    interval = max(0.0, float(args.interval))

    try:
        for i in range(ticks):
            market.tick(1)
            engine.run_tick(pair)

            if (i + 1) % 5 == 0 or i == ticks - 1:
                snap = ex.snapshot()
                print(f"[tick {i+1}/{ticks}] balances={snap['balances']} last_fills={len(snap['fills'])}")

            if i != ticks - 1 and interval > 0:
                time.sleep(interval)

    except KeyboardInterrupt:
        print("\n⏹️  Остановлено пользователем")
