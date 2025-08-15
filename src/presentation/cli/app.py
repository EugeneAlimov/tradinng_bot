from __future__ import annotations

import os
import traceback

import argparse
import time
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from typing import Dict, Any, Tuple, Optional, List

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

# Доменные сервисы
from src.domain.risk.risk_service import RiskService
from src.domain.portfolio.position_service import PositionService

# EXMO read-only клиент
from src.infrastructure.exchange.exmo_api import ExmoApi, ExmoCredentials

# Аналитика PnL
from src.analytics.pnl import compute_pnl_with_ledger, compute_pnl

getcontext().prec = 50


# ──────────────────────────────────────────────────────────────────────────────
# Универсальные хелперы
# ──────────────────────────────────────────────────────────────────────────────
def exmo_pairs_from_args(args) -> Tuple[str, str, str]:
    """Единая логика выбора пары из аргументов."""
    s = get_settings()
    default_pair = s.default_pair or "DOGE_EUR"
    pair_general = getattr(args, "exmo_pair", None) or getattr(args, "symbol", None) or default_pair
    pair_user = getattr(args, "exmo_user_pair", None) or pair_general
    pair_ticker = getattr(args, "exmo_ticker_pair", None) or pair_general
    return pair_general, pair_user, pair_ticker


def parse_limit_or_hint(val: str, flag_name: str) -> int:
    """Мягко парсим числовой лимит, печатая подсказку при ошибке."""
    try:
        lim = int(val)
        if lim < 0:
            raise ValueError
        return lim
    except Exception:
        print(f"⚠️  Неверное значение для {flag_name}: {val!r}.")
        print("   Примеры:")
        print("     --exmo-user-trades 50 --exmo-user-pair DOGE_EUR")
        print("     --exmo-trades 100 --exmo-pair DOGE_EUR")
        return -1


def require_pair(flag_ctx: str, pair: str | None) -> str:
    """Проверяем, что пара указана, иначе даём понятную подсказку и выходим."""
    if not pair:
        print(f"⚠️  Для {flag_ctx} требуется указать пару. Примеры:")
        print("    --exmo-pair DOGE_EUR --exmo-trades 50")
        print("    --symbol DOGE_EUR --exmo-order-book 20")
        raise SystemExit(1)
    return pair


def dump_if_needed(path: str | None, payload: Dict[str, Any]) -> None:
    """Сохраняем JSON по запросу."""
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        print(f"→ JSON saved to: {path}")
    except Exception as e:
        print(f"⚠️  Не удалось сохранить JSON: {e!r}")


def _parse_time_hint(s: str | None) -> Optional[int]:
    """
    Возвращает UNIX-epoch (сек) для строки:
      - '1717351410' (int)
      - '2025-08-09T14:00' (ISO; без TZ трактуем как UTC)
      - '24h', '7d', '90m' (относительно «сейчас»)
    """
    if not s:
        return None
    s = str(s).strip()
    # относительные
    try:
        if s.endswith(("h", "m", "d")):
            n = int(s[:-1])
            now = datetime.now(timezone.utc)
            if s.endswith("h"):
                return int((now - timedelta(hours=n)).timestamp())
            if s.endswith("m"):
                return int((now - timedelta(minutes=n)).timestamp())
            if s.endswith("d"):
                return int((now - timedelta(days=n)).timestamp())
    except Exception:
        pass
    # epoch int
    try:
        return int(s)
    except Exception:
        pass
    # ISO
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return int(dt.timestamp())
    except Exception:
        print(f"⚠️  Не удалось распознать время: {s!r}. Примеры: 1717351410, 2025-08-09T14:00, 24h, 7d")
        return None


def _warn_no_trades(source: str, dump_path: str | None = None, payload: Dict[str, Any] | None = None) -> int:
    """Единое сообщение и ранний выход, если нет сделок для PnL."""
    print(f"⚠ Нет сделок для расчёта PnL (источник: {source})")
    if dump_path and payload is not None:
        dump_if_needed(dump_path, payload)
    return 0


def _plot_series_to_png(xs: List[int], ys: List[float], title: str, out_path: str, ylabel: str = "value") -> None:
    """Простой построитель PNG-графика (без зависимостей на seaborn)."""
    try:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 4))
        plt.plot(xs, ys)
        plt.title(title)
        plt.xlabel("ts")
        plt.ylabel(ylabel)
        plt.tight_layout()
        plt.savefig(out_path)
        plt.close()
        print(f"→ Chart saved to: {out_path}")
    except Exception as e:
        print(f"⚠️  Не удалось сохранить график {out_path!r}: {e!r}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
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

    # ===== EXMO probe (read-only) =====
    ex = p.add_argument_group("EXMO probe (read-only)")
    ex.add_argument("--exmo-ping", action="store_true", help="Проверить доступность EXMO API")
    ex.add_argument("--exmo-ticker", action="store_true", help="Получить общий тикер по всем парам")
    ex.add_argument("--exmo-ticker-pair", type=str, default=None, help="Тикер конкретной пары, напр. DOGE_EUR")

    # единый выбор пары + отдельная для приватных
    ex.add_argument("--exmo-pair", type=str, default=None,
                    help="Пара для всех EXMO операций (например, DOGE_EUR). Приоритет выше, чем у --symbol.")
    ex.add_argument("--exmo-user-pair", type=str, default=None,
                    help="Пара для user_trades/open_orders (если не указано — берём из --exmo-pair, затем --symbol).")

    ex.add_argument("--exmo-order-book", type=int, default=0, metavar="LIMIT",
                    help="Стакан по паре (LIMIT записей, 0=пропустить)")
    ex.add_argument("--exmo-trades", type=int, default=0, metavar="LIMIT",
                    help="Последние публичные сделки по паре (LIMIT записей, 0=пропустить)")
    ex.add_argument("--exmo-balances", action="store_true", help="Мои балансы (read-only)")
    ex.add_argument("--exmo-open-orders", action="store_true", help="Мои открытые ордера (read-only)")
    ex.add_argument("--exmo-user-trades", type=str, default="0", metavar="LIMIT",
                    help="Моя история сделок: LIMIT (число). Пара — через --exmo-user-пair или --exmo-pair.")
    ex.add_argument("--dump-json", type=str, default=None,
                    help="Путь для JSON-дампа результата EXMO probe (например, data/exmo_probe.json)")

    # свечи/kline/ohlcv + фильтры + PNG/CSV
    ex.add_argument("--exmo-candles", type=str, default=None, metavar="TF:LIMIT",
                    help="Свечи: TF:LIMIT, напр. 1m:200. Пара — через --exmo-pair.")
    ex.add_argument("--exmo-kline", type=str, default=None, metavar="TF:LIMIT",
                    help="Kline: TF:LIMIT. Пара — через --exmo-pair.")
    ex.add_argument("--exmo-ohlcv", type=str, default=None, metavar="TF:LIMIT",
                    help="OHLCV: TF:LIMIT. Пара — через --exmo-pair.")
    ex.add_argument("--exmo-since", type=str, default=None,
                    help="Срез «с»: epoch/ISO/rel (напр. 24h, 2025-08-09T14:00)")
    ex.add_argument("--exmo-until", type=str, default=None,
                    help="Срез «по»: epoch/ISO/rel")
    ex.add_argument("--exmo-save-csv", type=str, default=None,
                    help="Сохранить свечи в CSV (ts,open,high,low,close,volume)")
    ex.add_argument("--exmo-plot", type=str, default=None,
                    help="Сохранить график цены (close) в PNG (например, data/plot.png)")

    # PnL-сканер
    ex.add_argument("--exmo-pnl", action="store_true",
                    help="Подсчёт PnL по сделкам (учитывает --exmo-since/--exmo-until)")
    ex.add_argument("--exmo-user-limit", type=int, default=500,
                    help="Сколько сделок запрашивать онлайн для PnL (по умолчанию 500)")
    ex.add_argument("--exmo-pnl-from", type=str, default=None,
                    help="Путь к JSON со сделками для офлайнового расчёта PnL (дамп из --exmo-user-trades)")
    ex.add_argument("--exmo-pnl-save-csv", type=str, default=None,
                    help="Сохранить подробный разбор сделок (ledger) в CSV")
    ex.add_argument("--exmo-pnl-plot", type=str, default=None,
                    help="Сохранить PNG с эквити-кривой (equity_quote по времени)")

    return p


# ──────────────────────────────────────────────────────────────────────────────
# Paper-компоненты
# ──────────────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────────
# EXMO-probe (read-only)
# ──────────────────────────────────────────────────────────────────────────────
def _exmo_probe(args) -> int:
    """
    Универсальный пробник EXMO:
      - пинг / тикер / стакан / публичные трейды
      - приватка: балансы, открытые ордера, мои трейды
      - свечи: --exmo-candles/--exmo-kline/--exmo-ohlcv TF:LIMIT (+ --exmo-since/--exmo-until, CSV/plot)
      - PnL: --exmo-pnl (по моим трейдам или из файла через --exmo-pnl-from)
    """
    import json, os, traceback
    from decimal import Decimal
    from typing import Dict, Any, List

    from src.config.settings import get_settings
    from src.infrastructure.exchange.exmo_api import ExmoApi, ExmoCredentials

    EXMO_DEBUG = os.getenv("EXMO_DEBUG", "").strip() not in ("", "0", "false", "False")

    # ── helpers ──────────────────────────────────────────────────────────────────
    def parse_limit_or_hint(val: str, flag: str) -> int:
        try:
            return int(str(val).strip())
        except Exception:
            print(f"⚠️  {flag}: ожидается целое число, получено {val!r}")
            return -1

    def require_pair(flag: str, pair: str | None) -> str:
        p = (pair or args.symbol or "").strip()
        if not p:
            print(f"⚠️  Укажи торговую пару через {flag} или --symbol, например: --exmo-pair DOGE_EUR")
            raise SystemExit(1)
        return p

    def _parse_time_hint(s: str | None) -> int | None:
        from datetime import datetime, timedelta, timezone
        if not s:
            return None
        s = str(s).strip()
        try:
            if s.endswith(("h", "m", "d")):
                n = int(s[:-1])
                now = datetime.now(timezone.utc)
                if s.endswith("h"):
                    return int((now - timedelta(hours=n)).timestamp())
                if s.endswith("m"):
                    return int((now - timedelta(minutes=n)).timestamp())
                if s.endswith("d"):
                    return int((now - timedelta(days=n)).timestamp())
        except Exception:
            pass
        try:
            return int(s)
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                # трактуем как UTC (проще и предсказуемее)
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return int(dt.timestamp())
        except Exception:
            print(f"⚠️  Не удалось распознать время: {s!r}. Примеры: 1717351410, 2025-08-09T14:00, 24h, 7d")
            return None

    def dump_if_needed(path: str | None, payload: Dict[str, Any]) -> None:
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"→ JSON saved to: {path}")
        except Exception as e:
            print(f"⚠️  Не удалось сохранить JSON: {e!r}")

    def _filter_by_time(rows: List[Dict[str, Any]], since_ts: int | None, until_ts: int | None) -> List[Dict[str, Any]]:
        if since_ts is None and until_ts is None:
            return rows
        out = []
        for r in rows:
            ts = int(r.get("ts") or r.get("t") or r.get("date") or 0)
            # для candles_history сервер отдаёт миллисекунды в поле t — нормализуем
            if ts > 10_000_000_000:  # вероятно ms
                ts //= 1000
            if since_ts is not None and ts < since_ts:
                continue
            if until_ts is not None and ts > until_ts:
                continue
            out.append(r)
        return out

    def _maybe_save_csv(rows: List[Dict[str, Any]], path: str | None) -> None:
        if not path or not rows:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("ts,open,high,low,close,volume\n")
                for r in rows:
                    ts = int(r.get("ts") or r.get("t") or 0)
                    if ts > 10_000_000_000:
                        ts //= 1000
                    f.write(f"{ts},{r['open']},{r['high']},{r['low']},{r['close']},{r.get('volume','')}\n")
            print(f"→ CSV saved to: {path}")
        except Exception as e:
            print(f"⚠️  Не удалось сохранить CSV: {e!r}")

    def _maybe_plot(rows: List[Dict[str, Any]], pair: str, tf: str, out_path: str | None) -> None:
        if not out_path or not rows:
            return
        try:
            import matplotlib.pyplot as plt
            xs = []
            ys = []
            for r in rows:
                ts = int(r.get("ts") or r.get("t") or 0)
                if ts > 10_000_000_000:
                    ts //= 1000
                xs.append(ts)
                ys.append(float(r["close"]))
            plt.figure(figsize=(10, 3.2))
            plt.plot(xs, ys)
            plt.title(f"EXMO {'ohlcv' if 'volume' in rows[0] else 'candles'} {pair} {tf}")
            plt.xlabel("ts")
            plt.ylabel("close")
            plt.tight_layout()
            plt.savefig(out_path, dpi=120)
            plt.close()
            print(f"→ Chart saved to: {out_path}")
        except Exception as e:
            print(f"⚠️  Не удалось построить график: {e!r}")

    # ── подготовка клиента ───────────────────────────────────────────────────────
    s = get_settings()
    api = ExmoApi(ExmoCredentials(api_key=s.api_key, api_secret=s.api_secret), allow_trading=False)
    pair_general = (getattr(args, "exmo_pair", None) or getattr(args, "symbol", None) or "").strip()
    pair_user = (getattr(args, "exmo_user_pair", None) or pair_general or "").strip()

    result: Dict[str, Any] = {"pair": pair_general}

    try:
        # ── Простые публичные проверки ──────────────────────────────────────────
        if getattr(args, "exmo_ping", False):
            ok = api.ping()
            print(f"EXMO ping: {'OK' if ok else 'FAIL'}")
            result["ping"] = ok

        if getattr(args, "exmo_ticker", False):
            t = api.ticker()
            print(f"EXMO ticker: {len(t)} pairs")
            result["ticker"] = t

        if getattr(args, "exmo_ticker_pair", None):
            pair = require_pair("--exmo-ticker-pair", args.exmo_ticker_pair)
            tp = api.ticker_pair(pair)
            print(f"EXMO ticker[{pair}]: {tp}")
            result["ticker_pair"] = tp

        # стакан и публичные трейды
        if getattr(args, "exmo_order_book", None):
            limit = parse_limit_or_hint(args.exmo_order_book, "--exmo-order-book")
            if limit < 0:
                return 1
            pair = require_pair("--exmo-order-book", pair_general)
            ob = api.order_book(pair, limit=limit)
            # чуть компактнее в консоли
            top_keys = sorted([(k, str(v)) for k, v in ob.items() if isinstance(v, (str, int, float))])[:2]
            print(f"EXMO order_book[{pair}] top keys: {top_keys}")
            result["order_book"] = ob

        if getattr(args, "exmo_trades", None):
            limit = parse_limit_or_hint(args.exmo_trades, "--exmo-trades")
            if limit < 0:
                return 1
            pair = require_pair("--exmo-trades", pair_general)
            tr = api.trades(pair, limit=limit)
            print(f"EXMO trades[{pair}]: {len(tr)} items")
            result["trades"] = tr

        # приватка
        if getattr(args, "exmo_balances", False):
            bal = api.user_balances()
            print(f"EXMO balances: {bal}")
            result["balances"] = bal

        if getattr(args, "exmo_open_orders", False):
            pair = require_pair("--exmo-open-orders", pair_user or pair_general)
            oo = api.user_open_orders(pair)
            print(f"EXMO open_orders[{pair}]: {oo}")
            result["open_orders"] = oo

        if getattr(args, "exmo_user_trades", None) and args.exmo_user_trades != "0":
            limit = parse_limit_or_hint(args.exmo_user_trades, "--exmo-user-trades")
            if limit < 0:
                return 1
            pair = require_pair("--exmo-user-trades", pair_user or pair_general)
            ut = api.user_trades(pair, limit=limit)
            print(f"EXMO user_trades[{pair}]: {len(ut)} items")
            result["user_trades"] = ut

        # ── Свечи / Kline / OHLCV (через candles_history) ──────────────────────
        since_ts = _parse_time_hint(getattr(args, "exmo_since", None))
        until_ts = _parse_time_hint(getattr(args, "exmo_until", None))

        def _split_tf_limit(s: str, flag_name: str) -> tuple[str, int] | None:
            tf, sep, lim = (s or "").partition(":")
            lim_i = parse_limit_or_hint(lim or "0", flag_name)
            if not tf or lim_i <= 0:
                print(f"⚠️  Пример: {flag_name} 1m:200 --exmo-pair DOGE_EUR")
                return None
            return tf, lim_i

        if getattr(args, "exmo_candles", None):
            sp = _split_tf_limit(args.exmo_candles, "--exmo-candles")
            if sp is None:
                return 1
            tf, lim = sp
            pair = require_pair("--exmo-candles", pair_general)
            rows = api.candles(pair=pair, timeframe=tf, limit=lim)  # уже нормализованы в dict со столбцами
            rows = _filter_by_time(rows, since_ts, until_ts)
            print(f"EXMO candles[{pair} {tf}]: {len(rows)} items")
            result["candles"] = rows
            _maybe_save_csv(rows, getattr(args, "exmo_save_csv", None))
            _maybe_plot(rows, pair, tf, getattr(args, "exmo_plot", None))

        if getattr(args, "exmo_kline", None):
            sp = _split_tf_limit(args.exmo_kline, "--exmo-kline")
            if sp is None:
                return 1
            tf, lim = sp
            pair = require_pair("--exmo-kline", pair_general)
            rows = api.kline(pair=pair, timeframe=tf, limit=lim)
            rows = _filter_by_time(rows, since_ts, until_ts)
            print(f"EXMO kline[{pair} {tf}]: {len(rows)} items")
            result["kline"] = rows
            _maybe_save_csv(rows, getattr(args, "exmo_save_csv", None))
            _maybe_plot(rows, pair, tf, getattr(args, "exmo_plot", None))

        if getattr(args, "exmo_ohlcv", None):
            sp = _split_tf_limit(args.exmo_ohlcv, "--exmo-ohlcv")
            if sp is None:
                return 1
            tf, lim = sp
            pair = require_pair("--exmo-ohlcv", pair_general)
            rows = api.ohlcv(pair=pair, timeframe=tf, limit=lim)
            # api.ohlcv уже возвращает нормализованные словари
            rows = _filter_by_time(rows, since_ts, until_ts)
            print(f"EXMO ohlcv[{pair} {tf}]: {len(rows)} items")
            result["ohlcv"] = rows
            _maybe_save_csv(rows, getattr(args, "exmo_save_csv", None))
            _maybe_plot(rows, pair, tf, getattr(args, "exmo_plot", None))

        # ── PnL (упрощённый честный расчёт FIFO) ────────────────────────────────
        if getattr(args, "exmo_pnl", False):
            pair = require_pair("--exmo-pnl", pair_user or pair_general)

            # источник трейдов: файл или API
            trades: List[Dict[str, Any]] = []
            src = ""
            if getattr(args, "exmo_pnl_from", None):
                src = f"file:{args.exmo_pnl_from}"
                try:
                    with open(args.exmo_pnl_from, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    trades = data if isinstance(data, list) else data.get("user_trades") or data.get("trades") or []
                except Exception as e:
                    print(f"⚠ Не удалось прочитать {args.exmo_pnl_from!r}: {e!r}")
                    trades = []
            else:
                src = "exmo-api"
                limit = parse_limit_or_hint(getattr(args, "exmo_user_limit", "500"), "--exmo-user-limit")
                if limit < 0:
                    limit = 500
                trades = api.user_trades(pair, limit=limit)

            # фильтры по времени
            trades = _filter_by_time(trades, since_ts, until_ts)

            if not trades:
                print(f"⚠ Нет сделок для расчёта PnL (источник: {src})")
                dump_if_needed(getattr(args, "dump_json", None), {"pair": pair, "pnl": {"trades_total": 0}})
                return 0

            # сортируем по времени
            trades.sort(key=lambda r: int(r.get("date", 0)))

            # FIFO учёт
            position = Decimal("0")
            inv_quote = Decimal("0")  # стоимость позиции в валюте котировки
            realized = Decimal("0")
            fees_quote = Decimal("0")
            base_fees_total = Decimal("0")

            def _fee_to_quote(t: Dict[str, Any]) -> Decimal:
                # комиссия может быть в базе или в котировке
                fa = Decimal(str(t.get("commission_amount", "0")))
                cc = str(t.get("commission_currency") or "").upper()
                px = Decimal(str(t.get("price", "0") or "0"))
                q = Decimal(str(t.get("quantity", "0") or "0"))
                base, quote = pair.split("_", 1)
                if cc == quote:
                    return fa
                if cc == base:
                    # конвертим в quote по цене сделки
                    return (fa * px)
                return Decimal("0")

            for t in trades:
                side = (t.get("type") or "").lower()
                px = Decimal(str(t.get("price", "0") or "0"))
                qty = Decimal(str(t.get("quantity", "0") or "0"))
                amt = Decimal(str(t.get("amount", "0") or "0"))  # в валюте котировки
                if side == "buy":
                    position += qty
                    inv_quote += amt
                elif side == "sell":
                    # средняя цена * до-продажная позиция
                    avg_cost = (inv_quote / position) if position > 0 else Decimal("0")
                    cost_sold = avg_cost * qty
                    proceeds = amt  # уже в quote
                    realized += (proceeds - cost_sold)
                    position -= qty
                    inv_quote -= cost_sold
                    if position < 0:  # на всякий случай не уходим в минус
                        position = Decimal("0")
                        inv_quote = Decimal("0")
                # копим комиссии
                fees_quote += _fee_to_quote(t)
                base_fees_total += Decimal(str(t.get("commission_amount", "0")))

            # текущая цена
            last_px = None
            try:
                tp = api.ticker_pair(pair)
                last_px = Decimal(str(tp.get("last_trade") or tp.get("last_price") or "0"))
            except Exception:
                last_px = Decimal("0")

            notional = (position * last_px)
            unrealized = (notional - inv_quote)
            total_pnl = realized + unrealized

            # печать
            print(f"EXMO PnL[{pair}] trades={len(trades)} "
                  f"(B:{sum(1 for t in trades if (t.get('type') or '').lower()=='buy')}/"
                  f"S:{sum(1 for t in trades if (t.get('type') or '').lower()=='sell')})")
            print(f"  position: {position} {pair.split('_',1)[0]}")
            avg_cost = (inv_quote / position) if position > 0 else None
            if avg_cost is not None:
                print(f"   avg_cost: {avg_cost}")
            print(f"  last_price: {last_px}")
            print(f"  notional: {notional}")
            print(f"  realized: {realized}")
            print(f"  unrealized: {unrealized}")
            print(f"  total PnL: {total_pnl}")
            print(f"  fees (quote-eq): {fees_quote} | base fees sum: {base_fees_total}")

            pnl_json = {
                "pair": pair,
                "trades_total": len(trades),
                "buys": sum(1 for t in trades if (t.get("type") or "").lower() == "buy"),
                "sells": sum(1 for t in trades if (t.get("type") or "").lower() == "sell"),
                "inventory_base": str(position),
                "avg_cost": (str(avg_cost) if avg_cost is not None else None),
                "last_price": str(last_px),
                "notional_quote": str(notional),
                "realized_pnl_quote": str(realized),
                "unrealized_pnl_quote": str(unrealized),
                "total_pnl_quote": str(total_pnl),
                "fees_quote_converted": str(fees_quote),
                "base_fees_total": str(base_fees_total),
                "user_trades": trades,
            }
            result["pnl"] = pnl_json

            # CSV/plot для equity, если уже реализовано ранее — можно оставить свой код.
            # Здесь минималистично ничего не сохраняем: JSON попадёт в dump.

        # если пользователь не выбрал ничего из EXMO-группы
        if not any([
            getattr(args, "exmo_ping", False),
            getattr(args, "exmo_ticker", False),
            getattr(args, "exmo_ticker_pair", None),
            getattr(args, "exmo_order_book", None),
            getattr(args, "exmo_trades", None),
            getattr(args, "exmo_balances", False),
            getattr(args, "exmo_open_orders", False),
            (getattr(args, "exmo_user_trades", None) and args.exmo_user_trades != "0"),
            getattr(args, "exmo_candles", None),
            getattr(args, "exmo_kline", None),
            getattr(args, "exmo_ohlcv", None),
            getattr(args, "exmo_pnl", False),
        ]):
            print("Нет выбранных действий EXMO probe. Укажи хотя бы один флаг из группы EXMO.")
            return 1

        dump_if_needed(getattr(args, "dump_json", None), result)
        return 0

    except SystemExit as se:
        return int(se.code) if isinstance(se.code, int) else 1
    except Exception as e:
        if EXMO_DEBUG:
            traceback.print_exc()
        print(f"❌ EXMO probe error: {e!r}")
        return 1


# ──────────────────────────────────────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────────────────────────────────────
def run_cli() -> None:
    args = _build_parser().parse_args()

    # ветка EXMO-probe
    if (
        args.exmo_ping or args.exmo_ticker or args.exmo_ticker_pair or
        (args.exmo_order_book and args.exmo_order_book > 0) or
        (args.exmo_trades and args.exmo_trades > 0) or
        args.exmo_balances or args.exmo_open_orders or
        (args.exmo_user_trades and args.exmo_user_trades != "0") or
        args.exmo_candles or args.exmo_kline or args.exmo_ohlcv or
        args.exmo_pnl
    ):
        code = _exmo_probe(args)
        raise SystemExit(code)

    # обычный paper-режим
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
