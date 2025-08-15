# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import matplotlib.dates as mdates

from src.config.settings import get_settings
from src.core.domain.models import TradingPair
from src.infrastructure.market.random_walk import RandomWalkMarket
from src.infrastructure.exchange.paper_exchange import PaperExchange
from src.infrastructure.storage.files import FileStorage
from src.infrastructure.notify.log import LogNotifier
from src.application.engine.trade_engine import TradeEngine

# Стратегии
from src.domain.strategy.sma_crossover import SmaCrossover, SmaCfg
from src.domain.strategy.mean_reversion import MeanReversion

# Доменные сервисы
from src.domain.risk.risk_service import RiskService
from src.domain.portfolio.position_service import PositionService

# EXMO API (без ExmoCredentials — делаем универсальный конструктор)
from src.infrastructure.exchange.exmo_api import ExmoApi


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────
def _parse_time_hint(s: Optional[str]) -> Optional[int]:
    """Возвращает epoch-секунды для: '1717351410', '2025-08-09T14:00', '24h'/'7d'/'90m'."""
    if not s:
        return None
    s = s.strip()
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
    # epoch
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
        return None


def _split_tf_limit(arg: str) -> Tuple[str, int]:
    """Разбирает 'TF:LIMIT' → ('1m', 200)."""
    tf, _, lim = (arg or "").partition(":")
    if not tf or not lim:
        raise SystemExit("Неверный формат. Пример: --exmo-candles 1m:200")
    try:
        lim_i = int(lim)
    except Exception:
        raise SystemExit("LIMIT должен быть целым числом")
    if lim_i <= 0:
        raise SystemExit("LIMIT должен быть > 0")
    return tf.strip(), lim_i


def _tf_to_minutes(tf: str | int) -> int:
    """'1m'/'1h'/'1d'/int → минуты (минимум 1)."""
    if isinstance(tf, int):
        return max(1, tf)
    s = str(tf).strip().lower()
    if s.endswith("m"):
        return max(1, int(s[:-1] or "1"))
    if s.endswith("h"):
        return max(1, int(s[:-1] or "1") * 60)
    if s.endswith("d"):
        return max(1, int(s[:-1] or "1") * 60 * 24)
    try:
        return max(1, int(s))
    except Exception:
        return 1


def _maybe_save_csv(rows: List[Dict[str, Any]], path: Optional[str]) -> None:
    if not path or not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts,open,high,low,close,volume\n")
        for r in rows:
            ts = int(r.get("ts") or r.get("t") or 0)
            if ts > 10_000_000_000:
                ts //= 1000
            f.write(f"{ts},{r['open']},{r['high']},{r['low']},{r['close']},{r.get('volume','')}\n")
    print(f"→ CSV saved to: {path}")


def _maybe_plot(rows, title, out_path):
    if not out_path or not rows:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")  # неинтерактивный бэкенд
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
        logging.getLogger("matplotlib").setLevel(logging.WARNING)

        xs, ys = [], []

        for r in rows:
            # Поддержка форматов: dict с t/c (API), dict с ts/close (нормализованный),
            # а также tuple/list (ts, close)
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                ts_sec, close = float(r[0]), float(r[1])
            elif isinstance(r, dict):
                # timestamp
                if "t" in r:              # миллисекунды от EXMO API
                    ts_sec = float(r["t"]) / 1000.0
                elif "ts" in r:           # секунды после нормализации
                    ts_sec = float(r["ts"])
                else:
                    continue
                # close
                if "c" in r:
                    close = float(r["c"])
                elif "close" in r:
                    close = float(r["close"])
                else:
                    continue
            else:
                continue

            xs.append(datetime.fromtimestamp(ts_sec))
            ys.append(close)

        if not xs:
            raise KeyError("t/ts")

        fig = plt.figure(figsize=(12, 3.2))
        ax = plt.gca()
        ax.plot(xs, ys)
        ax.set_title(title)
        ax.set_xlabel("time")
        ax.set_ylabel("close")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate()
        plt.tight_layout()
        plt.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"→ Chart saved to: {out_path}")
    except Exception as e:
        print(f"⚠️  Не удалось построить график: {e!r}")


def _candles_via_history(api: Any, pair: str, tf: str, limit: int) -> List[Dict[str, Any]]:
    """Фоллбэк: строим нормализованные свечи через candles_history."""
    res_min = _tf_to_minutes(tf)
    now = int(time.time())
    frm = now - res_min * 60 * limit
    data = api.candles_history(symbol=pair, resolution=res_min, ts_from=frm, ts_to=now)
    raw = data.get("candles", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for r in raw:
        try:
            ts = int(int(r.get("t", 0)) // 1000)
            out.append({
                "ts": ts,
                "open": str(r["o"]),
                "high": str(r["h"]),
                "low": str(r["l"]),
                "close": str(r["c"]),
                "volume": str(r.get("v", "")),
            })
        except Exception:
            continue
    return out


def _make_exmo_api() -> ExmoApi:
    """Универсально создаём клиент, независимо от версии конструктора."""
    api_key = os.getenv("EXMO_API_KEY", "")
    api_secret = os.getenv("EXMO_API_SECRET", "")
    # Вариант 1: ExmoApi(api_key=..., api_secret=..., allow_trading=...)
    try:
        return ExmoApi(api_key=api_key, api_secret=api_secret, allow_trading=False)  # type: ignore
    except TypeError:
        pass
    # Вариант 2: ExmoApi(ExmoCredentials(...), allow_trading=...)
    try:
        from src.infrastructure.exchange.exmo_api import ExmoCredentials  # type: ignore
        return ExmoApi(ExmoCredentials(api_key=api_key, api_secret=api_secret), allow_trading=False)  # type: ignore
    except Exception:
        # Фоллбэк — попробуем последний вариант без allow_trading
        try:
            return ExmoApi(api_key=api_key, api_secret=api_secret)  # type: ignore
        except Exception:
            return ExmoApi()  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="exmo-bot", description="EXMO bot and tools")

    # ===== Старые/базовые аргументы (совместимость) =====
    p.add_argument("--mode", choices=["paper", "live", "hybrid", "legacy"], default="paper")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--exmo-debug", action="store_true")
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    p.add_argument("--pair", default=None)
    p.add_argument("--resolution", type=int, default=1)
    p.add_argument("--from-ts", type=int, default=0)
    p.add_argument("--to-ts", type=int, default=0)

    # ===== Paper-рынок =====
    p.add_argument("--symbol", default=None)
    p.add_argument("--ticks", type=int, default=1)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--start-price", type=str, default="0.1")
    p.add_argument("--drift-bps", type=float, default=0.0)
    p.add_argument("--vol-bps", type=float, default=20.0)
    p.add_argument("--rw-seed", type=int, default=None)
    p.add_argument("--tick-seconds", type=int, default=1)
    p.add_argument("--strategy", choices=["sma", "mr"], default="sma")
    p.add_argument("--tf", default="1m")
    p.add_argument("--fast", type=int, default=10)
    p.add_argument("--slow", type=int, default=30)
    p.add_argument("--min-gap-bps", type=str, default="2")

    # ===== EXMO probe (новые флаги) =====
    ex = p.add_argument_group("EXMO probe (read-only)")
    ex.add_argument("--exmo-pair", type=str, default=None)
    ex.add_argument("--exmo-candles", type=str, default=None, metavar="TF:LIMIT")
    ex.add_argument("--exmo-kline", type=str, default=None, metavar="TF:LIMIT")
    ex.add_argument("--exmo-ohlcv", type=str, default=None, metavar="TF:LIMIT")
    ex.add_argument("--exmo-save-csv", type=str, default=None)
    ex.add_argument("--exmo-plot", type=str, default=None)

    ex.add_argument("--exmo-balances", action="store_true")
    ex.add_argument("--exmo-open-orders", action="store_true")
    ex.add_argument("--exmo-trades", type=int, default=0, metavar="LIMIT")
    ex.add_argument("--exmo-order-book", type=int, default=0, metavar="LIMIT")
    ex.add_argument("--exmo-ticker", action="store_true")
    ex.add_argument("--exmo-ticker-pair", type=str, default=None)

    ex.add_argument("--exmo-user-trades", type=int, default=0, metavar="LIMIT")
    ex.add_argument("--exmo-user-pair", type=str, default=None)
    ex.add_argument("--exmo-since", type=str, default=None)
    ex.add_argument("--exmo-until", type=str, default=None)
    ex.add_argument("--dump-json", type=str, default=None)

    ex.add_argument("--exmo-pnl", action="store_true")
    ex.add_argument("--exmo-user-limit", type=int, default=500)
    ex.add_argument("--exmo-pnl-from", type=str, default=None)
    ex.add_argument("--exmo-pnl-save-csv", type=str, default=None)
    ex.add_argument("--exmo-pnl-plot", type=str, default=None)

    return p


# ──────────────────────────────────────────────────────────────────────────────
# Paper-режим
# ──────────────────────────────────────────────────────────────────────────────
def _build_paper_components(args):
    settings = get_settings()
    symbol = args.symbol or settings.default_pair or "DOGE_EUR"
    try:
        base, quote = symbol.split("_", 1)
    except ValueError:
        raise SystemExit("Некорректный --symbol, ожидается BASE_QUOTE, например DOGE_EUR")

    pair = TradingPair(base=base, quote=quote)
    notifier = LogNotifier()
    storage = FileStorage(path=settings.storage_path)

    market = RandomWalkMarket(
        start_price=args.start_price,
        drift_bps=args.drift_bps,
        vol_bps=args.vol_bps,
        seed=args.rw_seed,
        tick_seconds=args.tick_seconds,
    )

    ex = PaperExchange.with_quote_funds(
        market=market,
        quote_asset=quote,
        amount=10000,
        spread_bps=10,
        slippage_bps=5,
    )

    if args.strategy == "sma":
        strat = SmaCrossover(cfg=SmaCfg(timeframe=args.tf, fast=args.fast, slow=args.slow, min_gap_bps=args.min_gap_bps))
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
# EXMO probe
# ──────────────────────────────────────────────────────────────────────────────
def _run_exmo_probe(args) -> int:
    api = _make_exmo_api()

    # выбор пары
    pair_general = (args.exmo_pair or args.pair or args.symbol or "DOGE_EUR").strip()
    pair_user = (args.exmo_user_pair or pair_general).strip()

    result: Dict[str, Any] = {"pair": pair_general}

    # временные фильтры
    since_ts = _parse_time_hint(args.exmo_since)
    until_ts = _parse_time_hint(args.exmo_until)

    def _filter_time(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if since_ts is None and until_ts is None:
            return rows
        out = []
        for r in rows:
            ts = int(r.get("ts") or r.get("t") or r.get("date") or 0)
            if ts > 10_000_000_000:
                ts //= 1000
            if since_ts is not None and ts < since_ts:
                continue
            if until_ts is not None and ts > until_ts:
                continue
            out.append(r)
        return out

    # базовые публичные
    if args.exmo_ticker:
        result["ticker"] = api.ticker()
    if args.exmo_ticker_pair:
        result["ticker_pair"] = api.ticker_pair(args.exmo_ticker_pair)

    if args.exmo_order_book:
        result["order_book"] = api.order_book(pair_general, limit=int(args.exmo_order_book))

    if args.exmo_trades:
        result["trades"] = api.trades(pair_general, limit=int(args.exmo_trades))

    # свечи/kline/ohlcv (нормализованные dict → CSV/PNG)
    def _candles_like(flag_value: Optional[str], name: str):
        if not flag_value:
            return
        tf, lim = _split_tf_limit(flag_value)

        if name == "ohlcv" and hasattr(api, "ohlcv"):
            rows = api.ohlcv(pair=pair_general, timeframe=tf, limit=lim)  # список списков
            result[name] = rows
            return

        if hasattr(api, "candles"):
            rows = api.candles(pair=pair_general, timeframe=tf, limit=lim)  # список dict
        else:
            rows = _candles_via_history(api, pair_general, tf, lim)

        rows = _filter_time(rows)
        result[name] = rows
        _maybe_save_csv(rows, args.exmo_save_csv if name != "ohlcv" else None)
        _maybe_plot(rows, f"{pair_general} {tf}", args.exmo_plot if name != "ohlcv" else None)

    _candles_like(args.exmo_candles, "candles")
    _candles_like(args.exmo_kline, "kline")
    _candles_like(args.exmo_ohlcv, "ohlcv")

    # приватка
    if args.exmo_balances:
        result["balances"] = api.user_balances()

    if args.exmo_open_orders:
        result["open_orders"] = api.user_open_orders(pair_user)

    if args.exmo_user_trades:
        result["user_trades"] = api.user_trades(pair_user, limit=int(args.exmo_user_trades))

    # PnL — подготовим входные данные (расчёт можешь делать своим модулем)
    if args.exmo_pnl:
        trades = result.get("user_trades") or api.user_trades(pair_user, limit=int(args.exmo_user_limit))
        result["pnl_source_trades"] = len(trades or [])

    # дамп результата
    if args.dump_json:
        os.makedirs(os.path.dirname(args.dump_json), exist_ok=True)
        with open(args.dump_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"→ JSON saved to: {args.dump_json}")

    # краткий вывод
    if "candles" in result:
        print(f"EXMO candles[{pair_general}] rows={len(result['candles'])}")
    if "balances" in result:
        print("EXMO balances loaded")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────────────────────────────────────
def run_cli() -> None:
    # логи: по умолчанию INFO, сторонние либы — WARNING
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ["matplotlib", "PIL", "urllib3", "fontTools", "requests"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    args = _build_parser().parse_args()

    # Включаем подробный дебаг только для нашего EXMO-клиента при флаге/переменной
    if os.getenv("EXMO_DEBUG") or "--exmo-debug" in os.sys.argv:
        logging.getLogger("src.infrastructure.exchange.exmo_api").setLevel(logging.DEBUG)

    # Ветка EXMO probe (новые флаги)
    if any([
        args.exmo_candles, args.exmo_kline, args.exmo_ohlcv, args.exmo_balances,
        args.exmo_open_orders, args.exmo_trades, args.exmo_order_book,
        args.exmo_ticker, args.exmo_ticker_pair, args.exmo_user_trades, args.exmo_pnl
    ]):
        raise SystemExit(_run_exmo_probe(args))

    # Совместимость со «старым» режимом запроса свечей по from/to
    if args.pair and args.from_ts and args.to_ts:
        api = _make_exmo_api()
        res = args.resolution or 1
        data = api.candles_history(
            symbol=args.pair,
            resolution=int(res),
            ts_from=int(args.from_ts),
            ts_to=int(args.to_ts),
        )
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    # Иначе — paper-режим (симуляция)
    if args.mode != "paper":
        raise SystemExit("Пока доступен только --mode paper")

    if args.validate:
        s = get_settings()
        print("✅ Validation OK")
        print(f"  Default pair: {s.default_pair}")
        return

    pair, engine, market, ex = _build_paper_components(args)

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
