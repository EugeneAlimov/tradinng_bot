from __future__ import annotations

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
from src.analytics.pnl import compute_pnl_with_ledger

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
    s = get_settings()
    creds = ExmoCredentials(api_key=s.api_key, api_secret=s.api_secret)
    api = ExmoApi(creds=creds, allow_trading=False)

    pair_general, pair_user, pair_ticker = exmo_pairs_from_args(args)
    pair_general = require_pair("EXMO probe", pair_general)
    pair_ticker = pair_ticker or pair_general

    result: Dict[str, Any] = {"pair": pair_ticker}

    try:
        # базовые
        if args.exmo_ping:
            ok = api.ping()
            print(f"EXMO ping: {'OK' if ok else 'FAIL'}")
            result["ping"] = ok

        if args.exmo_ticker:
            tk = api.ticker()
            print(f"EXMO ticker: {len(tk) if isinstance(tk, dict) else 'n/a'} pairs")
            result["ticker"] = tk

        if getattr(args, "exmo_ticker_pair", None):
            tpk = api.ticker_pair(pair_ticker)
            print(f"EXMO ticker[{pair_ticker}]: {tpk}")
            result["ticker_pair"] = tpk

        if args.exmo_order_book and args.exmo_order_book > 0:
            ob = api.order_book(pair_general, limit=args.exmo_order_book)
            top = list(ob.get(pair_general, {}).items())[:2] if isinstance(ob, dict) else []
            print(f"EXMO order_book[{pair_general}] top keys: {top}")
            result["order_book"] = ob

        if args.exmo_trades and args.exmo_trades > 0:
            tr = api.trades(pair_general, limit=args.exmo_trades)
            print(f"EXMO trades[{pair_general}]: {len(tr)} items")
            result["trades"] = tr

        if args.exmo_balances:
            bals = api.user_balances()
            print(f"EXMO balances: {{ {', '.join(f'{k!s}: {str(v)!s}' for k,v in bals.items())} }}")
            result["balances"] = {k: str(v) for k, v in bals.items()}

        if args.exmo_open_orders:
            oo = api.user_open_orders(pair_user)
            print(f"EXMO open_orders[{pair_user}]: {oo}")
            result["open_orders"] = oo

        # user trades (ручной дамп)
        if args.exmo_user_trades and args.exmo_user_trades != "0":
            limit = parse_limit_or_hint(args.exmo_user_trades, "--exmo-user-trades")
            if limit < 0:
                return 1
            ut = api.user_trades(pair_user, limit=limit)
            print(f"EXMO user_trades[{pair_user}]: {len(ut)} items")
            result["user_trades"] = ut

        # свечи/kline/ohlcv
        def _split_tf_limit(s: str, flag_name: str) -> tuple[str, int] | None:
            tf, _, lim = (s or "").partition(":")
            lim = parse_limit_or_hint(lim or "0", flag_name)
            if not tf or lim <= 0:
                print(f"⚠️  Пример: {flag_name} 1m:200 --exmo-pair DOGE_EUR")
                return None
            return tf, lim

        since_ts = _parse_time_hint(args.exmo_since)
        until_ts = _parse_time_hint(args.exmo_until)

        def _filter_by_time(rows: List[Dict[str, Any]], ts_key: str = "ts") -> List[Dict[str, Any]]:
            if since_ts is None and until_ts is None:
                return rows
            out: List[Dict[str, Any]] = []
            for r in rows:
                ts = int(r.get(ts_key, 0))
                if since_ts is not None and ts < since_ts:
                    continue
                if until_ts is not None and ts > until_ts:
                    continue
                out.append(r)
            return out

        def _maybe_save_csv(rows: List[Dict[str, Any]], path: str | None) -> None:
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("ts,open,high,low,close,volume\n")
                    for r in rows:
                        f.write(f"{int(r['ts'])},{r['open']},{r['high']},{r['low']},{r['close']},{r.get('volume','')}\n")
                print(f"→ CSV saved to: {path}")
            except Exception as e:
                print(f"⚠️  Не удалось сохранить CSV: {e!r}")

        # candles
        if getattr(args, "exmo_candles", None):
            sp = _split_tf_limit(args.exmo_candles, "--exmo-candles")
            if sp is None:
                return 1
            tf, lim = sp
            pair = require_pair("--exmo-candles", pair_general)
            data = api.candles(pair=pair, timeframe=tf, limit=lim)
            data = _filter_by_time(data, ts_key="ts")
            print(f"EXMO candles[{pair} {tf}]: {len(data)} items")
            result["candles"] = data
            _maybe_save_csv(data, args.exmo_save_csv)
            if getattr(args, "exmo_plot", None):
                xs = [int(r["ts"]) for r in data]
                ys = [float(r["close"]) for r in data]
                _plot_series_to_png(xs, ys, f"Candles close — {pair} {tf}", args.exmo_plot, ylabel="close")

        # kline
        if getattr(args, "exmo_kline", None):
            sp = _split_tf_limit(args.exmo_kline, "--exmo-kline")
            if sp is None:
                return 1
            tf, lim = sp
            pair = require_pair("--exmo-kline", pair_general)
            data = api.kline(pair=pair, timeframe=tf, limit=lim)
            data = _filter_by_time(data, ts_key="ts")
            print(f"EXMO kline[{pair} {tf}]: {len(data)} items")
            result["kline"] = data
            _maybe_save_csv(data, args.exmo_save_csv)
            if getattr(args, "exmo_plot", None):
                xs = [int(r["ts"]) for r in data]
                ys = [float(r["close"]) for r in data]
                _plot_series_to_png(xs, ys, f"Kline close — {pair} {tf}", args.exmo_plot, ylabel="close")

        # ohlcv
        if getattr(args, "exmo_ohlcv", None):
            sp = _split_tf_limit(args.exmo_ohlcv, "--exmo-ohlcv")
            if sp is None:
                return 1
            tf, lim = sp
            pair = require_pair("--exmo-ohlcv", pair_general)
            raw = api.ohlcv(pair=pair, timeframe=tf, limit=lim)
            norm = [{"ts": int(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in raw]
            norm = _filter_by_time(norm, ts_key="ts")
            print(f"EXMO ohlcv[{pair} {tf}]: {len(norm)} items")
            result["ohlcv"] = norm
            _maybe_save_csv(norm, args.exmo_save_csv)
            if getattr(args, "exmo_plot", None):
                xs = [int(r["ts"]) for r in norm]
                ys = [float(r["close"]) for r in norm]
                _plot_series_to_png(xs, ys, f"OHLCV close — {pair} {tf}", args.exmo_plot, ylabel="close")

        # PnL-сканер (полноценный)
        if getattr(args, "exmo_pnl", False):
            pair = require_pair("--exmo-pnl", pair_user or pair_general)

            # откуда брать сделки
            trades: List[Dict[str, Any]] = []
            source_desc = "exmo-api"
            if getattr(args, "exmo_pnl_from", None):
                try:
                    with open(args.exmo_pnl_from, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    trades = list(data.get("user_trades") or [])
                    source_desc = f"file:{args.exmo_pnl_from}"
                except Exception as e:
                    print(f"❌ Не удалось прочитать {args.exmo_pnl_from!r}: {e!r}")
                    return 1
            else:
                limit = int(getattr(args, "exmo_user_limit", 500) or 500)
                trades = api.user_trades(pair, limit=limit)

            # фильтр по времени
            since_ts = _parse_time_hint(args.exmo_since)
            until_ts = _parse_time_hint(args.exmo_until)
            if since_ts is not None or until_ts is not None:
                trades = [t for t in trades if (since_ts is None or int(t.get("date", 0)) >= since_ts) and
                                           (until_ts is None or int(t.get("date", 0)) <= until_ts)]

            if not trades:
                return _warn_no_trades(source_desc, getattr(args, "dump_json", None), {"pair": pair, "user_trades": []})

            # актуальная цена
            tpk = api.ticker_pair(pair) or {}
            last_price = Decimal(tpk.get("last_trade") or tpk.get("buy_price") or tpk.get("sell_price") or "0")

            summary, ledger, equity = compute_pnl_with_ledger(pair, trades, last_price)

            # консольная сводка
            print(f"EXMO PnL[{pair}] trades={summary.trades_total} (B:{summary.buys}/S:{summary.sells})")
            print(f"  position: {summary.inventory_base} {pair.split('_',1)[0]}")
            if summary.avg_cost is not None:
                print(f"  avg_cost: {summary.avg_cost}")
            print(f"  last_price: {summary.last_price}")
            print(f"  notional: {summary.notional_quote}")
            print(f"  realized: {summary.realized_pnl_quote}")
            print(f"  unrealized: {summary.unrealized_pnl_quote}")
            print(f"  total PnL: {summary.total_pnl_quote}")
            print(f"  fees (quote-eq): {summary.fees_quote_converted} | base fees sum: {summary.base_fees_total}")

            # дампы в общий result
            result["pnl"] = {
                "pair": summary.pair,
                "trades_total": summary.trades_total,
                "buys": summary.buys,
                "sells": summary.sells,
                "inventory_base": str(summary.inventory_base),
                "avg_cost": (str(summary.avg_cost) if summary.avg_cost is not None else None),
                "last_price": str(summary.last_price),
                "notional_quote": str(summary.notional_quote),
                "realized_pnl_quote": str(summary.realized_pnl_quote),
                "unrealized_pnl_quote": str(summary.unrealized_pnl_quote),
                "total_pnl_quote": str(summary.total_pnl_quote),
                "fees_quote_converted": str(summary.fees_quote_converted),
                "base_fees_total": str(summary.base_fees_total),
            }
            result["pnl_ledger"] = ledger
            result["pnl_equity"] = equity

            # CSV Ledger
            if getattr(args, "exmo_pnl_save_csv", None):
                try:
                    with open(args.exmo_pnl_save_csv, "w", encoding="utf-8") as f:
                        f.write("ts,type,qty,price,amount_quote,realized_step,inventory_base,avg_cost_before,avg_cost_after,realized_cum\n")
                        for r in ledger:
                            f.write(",".join([
                                str(int(r["ts"])),
                                r["type"],
                                r["qty"],
                                r["price"],
                                r["amount_quote"],
                                r["realized_step"],
                                r["inventory_base"],
                                "" if r["avg_cost_before"] is None else r["avg_cost_before"],
                                "" if r["avg_cost_after"] is None else r["avg_cost_after"],
                                r["realized_cum"],
                            ]) + "\n")
                    print(f"→ CSV saved to: {args.exmo_pnl_save_csv}")
                except Exception as e:
                    print(f"⚠️  Не удалось сохранить CSV ledger: {e!r}")

            # PNG эквити
            if getattr(args, "exmo_pnl_plot", None):
                xs = [int(r["ts"]) for r in equity]
                ys = [float(r["equity_quote"]) for r in equity]
                _plot_series_to_png(xs, ys, f"Equity curve — {pair}", args.exmo_pnl_plot, ylabel="equity (quote)")

        # общий дамп результата
        dump_if_needed(args.dump_json, result)

        # если ничего не выбрано
        if (
            not args.exmo_ping and
            not args.exmo_ticker and
            not getattr(args, "exmo_ticker_pair", None) and
            not args.exmo_order_book and
            not args.exmo_trades and
            not args.exmo_balances and
            not args.exmo_open_orders and
            (not args.exmo_user_trades or args.exmo_user_trades == "0") and
            not getattr(args, "exmo_candles", None) and
            not getattr(args, "exmo_kline", None) and
            not getattr(args, "exmo_ohlcv", None) and
            not getattr(args, "exmo_pnl", None)
        ):
            print("Нет выбранных действий EXMO probe. Укажи хотя бы один флаг из группы EXMO.")
            return 1

        return 0
    except Exception as e:
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
