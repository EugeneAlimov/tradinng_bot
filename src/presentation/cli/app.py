# src/presentation/cli/app.py
# -*- coding: utf-8 -*-
"""
EXMO research & live CLI.

Команды:
  - sweep         : перебор стратегий на OHLC и вывод топа
  - optimize      : оптимизация параметров одной стратегии
  - robustness    : робастность лучших параметров
  - walk-forward  : walk-forward валидация
  - trade-live    : observe / paper режимы

Требует модуль selector:
  src.application.research.selector
    (sweep / optimize / robustness / walk_forward / load_grid_json / available_strategies)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

# Внешнее HTTP (EXMO)
import urllib3
import pandas as pd

# Наш селектор (единая точка алгоритмики)
try:
    from src.application.research import selector as sel
except Exception:  # noqa: BLE001 - хотим понятную ошибку пользователю
    sel = None  # type: ignore

# ----------------------------- Логи -----------------------------

logger = logging.getLogger("cli")


def _configure_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # как в логах пользователя — подробный urllib3 только в debug
    if debug:
        for noisy in ("urllib3",):
            logging.getLogger(noisy).setLevel(logging.DEBUG)
    else:
        logging.getLogger("urllib3").setLevel(logging.WARNING)


# ----------------------------- Константы -----------------------------

AUTO_STRATEGIES: List[str] = [
    "sma",
    "ema",
    "ema_adx",
    "ema_adx_atr",
    "supertrend",
    "keltner",
    "adx",
    "sma_atr",
    "rsi2",
    "donchian",
    "bbands",
    "roc",
]


# ----------------------------- Утилиты -----------------------------

def _minutes_from_tf(tf: str) -> int:
    """'1m' -> 1, '5m' -> 5, '15m' -> 15, '1h'/'60m' -> 60."""
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    # допустим "60" или "60m"
    return int(tf)


def _parse_candles_spec(spec: str) -> Tuple[int, int, int]:
    """
    '5m:2000' -> (resolution_minutes, bars, span_seconds)
    """
    s = spec.strip()
    if ":" not in s:
        raise ValueError(f"Bad candles spec: '{spec}' (ожидалось вроде '5m:2000')")
    tf, cnt = s.split(":", 1)
    minutes = _minutes_from_tf(tf)
    bars = int(cnt)
    span_sec = minutes * 60 * bars
    return minutes, bars, span_sec


def _http_client(retries: int, backoff: float) -> urllib3.PoolManager:
    retry = urllib3.util.retry.Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
    )
    return urllib3.PoolManager(retries=retry, timeout=urllib3.Timeout(connect=5.0, read=30.0))


def _fetch_exmo_ohlc(pair: str, candles_spec: str, http_retries: int, http_backoff: float) -> pd.DataFrame:
    """
    Тянем OHLC с EXMO /v1.1/candles_history.
    Возвращает DataFrame с колонками: ['ts','open','high','low','close','volume']
    """
    minutes, _, span_sec = _parse_candles_spec(candles_spec)
    now = int(time.time())
    frm = int(now - span_sec)
    to = now
    resolution = minutes  # EXMO resolution = минуты

    http = _http_client(http_retries, http_backoff)
    url = (
        "https://api.exmo.com/v1.1/candles_history"
        f"?symbol={pair}&resolution={resolution}&from={frm}&to={to}"
    )

    logger.debug("Starting new HTTPS connection (1): api.exmo.com:443")
    r = http.request("GET", url)
    logger.debug('https://api.exmo.com:443 "GET %s HTTP/1.1" %s %s', url.replace("https://api.exmo.com", ""), r.status, "None")

    if r.status != 200:
        raise RuntimeError(f"EXMO HTTP {r.status}")

    try:
        payload = json.loads(r.data.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("EXMO response decode error") from e

    if not payload or "candles" not in payload:
        raise RuntimeError("EXMO payload malformed (no 'candles')")

    candles = payload["candles"] or []
    if not candles:
        # Пусто — вернём empty DF, пусть верхний уровень решает
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)  # keys: t, o, h, l, c, v
    # нормализуем
    mapping = {"t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    df = df.rename(columns=mapping)
    # типы
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["ts"] = pd.to_numeric(df["ts"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["ts", "close"]).reset_index(drop=True)
    return df


def _ensure_dir(path: Optional[str]) -> None:
    if not path:
        return
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _list_from_csv_arg(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _params_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Берём базовые параметры, если они переданы (ema/adx/atr).
    """
    out: Dict[str, Any] = {}
    # EMA
    if getattr(args, "ema_fast", None) is not None:
        out["fast"] = int(args.ema_fast)
    if getattr(args, "ema_slow", None) is not None:
        out["slow"] = int(args.ema_slow)
    # ADX
    if getattr(args, "adx_len", None) is not None:
        out["adx_len"] = int(args.adx_len)
    if getattr(args, "adx_on", None) is not None:
        out["on"] = float(args.adx_on)
    if getattr(args, "adx_off", None) is not None:
        out["off"] = float(args.adx_off)
    if getattr(args, "require_di", False):
        out["require_di"] = True
    # ATR
    if getattr(args, "atr_len", None) is not None:
        out["atr_len"] = int(args.atr_len)
    if getattr(args, "atr_mult", None) is not None:
        out["atr_mult"] = float(args.atr_mult)
    return out


def _weights_from_args(_: argparse.Namespace) -> Dict[str, float]:
    """
    Весовые коэффициенты для score (если они появятся в селекторе).
    """
    return {
        "sharpe": 1.0,
        "winrate": 0.5,
        "avg_pnl": 0.5,
        "total_pnl": 1.0,
        "max_dd": 1.0,  # в селекторе обычно нормализован как (1 - dd_norm)
    }


def _selector_invoke(fn_name: str, **call_kwargs: Any) -> Any:
    if sel is None:
        raise RuntimeError("Selector module not found: src.application.research.selector")
    func = getattr(sel, fn_name, None)
    if func is None:
        raise RuntimeError(f"Selector.{fn_name} is missing")
    return func(**call_kwargs)


# ----------------------------- Печать таблиц -----------------------------

def _print_rows_table(rows: List[Dict[str, Any]], metric: str) -> None:
    """
    Ряды от селектора — выводим компактную таблицу.
    Ожидаем поля: strategy, params, trades, winrate, avg_pnl, total_pnl, max_dd, sharpe, <metric>
    """
    if not rows:
        logger.info("no results")
        return

    headers = ["strategy", "params", "trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", metric]
    fmt_rows: List[List[str]] = []
    for r in rows:
        fmt_rows.append([
            str(r.get("strategy", "")),
            json.dumps(r.get("params", {}), ensure_ascii=False, separators=(",", ": ")),
            str(r.get("trades", "")),
            f"{r.get('winrate', 0.0):.1%}" if isinstance(r.get("winrate", None), (int, float)) else "",
            f"{r.get('avg_pnl', 0.0):.6f}" if isinstance(r.get("avg_pnl", None), (int, float)) else "",
            f"{r.get('total_pnl', 0.0):.6f}" if isinstance(r.get("total_pnl", None), (int, float)) else "",
            f"{r.get('max_dd', 0.0):.6f}" if isinstance(r.get("max_dd", None), (int, float)) else "",
            f"{r.get('sharpe', 0.0):.3f}" if isinstance(r.get("sharpe", None), (int, float)) else "",
            f"{r.get(metric, 0.0):.3f}" if isinstance(r.get(metric, None), (int, float)) else "",
        ])

    widths = [max(len(h), max((len(row[i]) for row in fmt_rows), default=0)) for i, h in enumerate(headers)]
    sep = "  "
    logger.info(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    logger.info(sep.join("-" * w for w in widths))
    for row in fmt_rows:
        logger.info(sep.join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _save_csv(path: Optional[str], rows: List[Dict[str, Any]]) -> None:
    if not path:
        return
    _ensure_dir(path)
    pd.DataFrame(rows).to_csv(path, index=False)
    logger.info("Saved CSV -> %s", path)


def _load_grid(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    if path == "-":
        data = sys.stdin.read()
        return json.loads(data) if data else None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------- Запуски команд -----------------------------

def _run_sweep(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 2))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
    if ohlc.empty:
        logger.info("OHLC is empty, nothing to do.")
        return 2

    strategies = (
        _list_from_csv_arg(args.strategies)
        if args.strategies and args.strategies != "auto"
        else AUTO_STRATEGIES
    )

    results: List[Dict[str, Any]] = _selector_invoke(
        "sweep",
        ohlc=ohlc,
        strategies=strategies,
        metric=args.metric,
        top_n=int(args.top_n),
        min_trades=int(args.min_trades),
        fee_bps=int(getattr(args, "fee_bps", 0)),
        slip_bps=int(getattr(args, "slip_bps", 0)),
    )
    _print_rows_table(results, metric=args.metric)
    _save_csv(getattr(args, "csv_results", None), results)
    return 0


def _run_optimize(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 2))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
    if ohlc.empty:
        logger.info("OHLC is empty, nothing to do.")
        return 2

    results: List[Dict[str, Any]] = _selector_invoke(
        "optimize",
        ohlc=ohlc,
        strategy=args.strategy,
        metric=args.metric,
        top_n=int(args.top_n),
        min_trades=int(args.min_trades),
        fee_bps=int(getattr(args, "fee_bps", 0)),
        slip_bps=int(getattr(args, "slip_bps", 0)),
    )
    _print_rows_table(results, metric=args.metric)
    _save_csv(getattr(args, "csv_results", None), results)
    return 0


def _run_robustness(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 2))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
    if ohlc.empty:
        logger.info("OHLC is empty, nothing to do.")
        return 2

    params = _params_from_args(args)

    # robust_level может быть строкой ("std") или числом (0.1)
    robust_level: Any = getattr(args, "robust_level", "std")
    try:
        if isinstance(robust_level, str):
            robust_level = robust_level.strip()
            if robust_level.lower() not in ("std", "lo", "hi"):
                robust_level = float(robust_level)
        else:
            robust_level = float(robust_level)
    except Exception:
        robust_level = "std"

    rows: List[Dict[str, Any]] = _selector_invoke(
        "robustness",
        ohlc=ohlc,
        strategy=args.strategy,
        params=params if params else None,
        level=robust_level,
        samples=int(getattr(args, "samples", 20)),
        fee_bps=int(getattr(args, "fee_bps", 0)),
        slip_bps=int(getattr(args, "slip_bps", 0)),
    )

    if rows:
        try:
            avg_sharpe = float(pd.DataFrame(rows)["sharpe"].mean())
        except Exception:
            avg_sharpe = float("nan")
        logger.info("robustness samples=%d  avgSharpe=%.3f", len(rows), avg_sharpe)

    _save_csv(getattr(args, "csv_results", None), rows)
    return 0


def _run_walk_forward(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 2))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
    if ohlc.empty:
        logger.info("OHLC is empty, nothing to do.")
        return 2

    strategies = (
        _list_from_csv_arg(args.strategies)
        if args.strategies and args.strategies != "auto"
        else AUTO_STRATEGIES
    )
    grid: Optional[Dict[str, Any]] = _load_grid(getattr(args, "grid_file", None))

    result: Dict[str, Any] = _selector_invoke(
        "walk_forward",
        ohlc=ohlc,
        strategies=strategies,
        metric=args.metric,
        min_trades=int(args.min_trades),
        folds=int(args.wf_folds),
        train_frac=float(args.wf_train_frac),
        grid=grid,
        fee_bps=int(getattr(args, "fee_bps", 0)),
        slip_bps=int(getattr(args, "slip_bps", 0)),
    )

    folds = result.get("folds", [])
    agg_trades = sum(int(f.get("trades", 0)) for f in folds) if isinstance(folds, list) else 0
    avg_sharpe = float(result.get("avg_sharpe", 0.0))
    total_pnl = float(result.get("total_pnl", 0.0))
    logger.info("WF aggregate: folds=%d trades=%d totalPnL=%.6f avgSharpe=%.2f",
                int(args.wf_folds), agg_trades, total_pnl, avg_sharpe)

    _save_csv(getattr(args, "csv_results", None), folds if isinstance(folds, list) else [])
    return 0


# ----------------------------- Live режимы -----------------------------

def _run_live_observe(args: argparse.Namespace) -> int:
    """
    Минимальный observe: периодически печатаем таймштамп и последнюю цену.
    """
    http_retries = int(getattr(args, "http_retries", 2))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    poll_sec = float(getattr(args, "poll_sec", 10))

    logger.info(
        "[live] observe %s %s strategy=%s params=%s poll=%ss",
        args.pair,
        args.candles,
        args.strategy,
        json.dumps(_params_from_args(args), ensure_ascii=False),
        int(poll_sec),
    )
    if getattr(args, "summary_alert", False):
        logger.debug("[live] summary-alert flag accepted (no-op notifier).")

    try:
        while True:
            df = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
            if not df.empty:
                last = df.iloc[-1]
                t_iso = datetime.fromtimestamp(int(last["ts"]), tz=timezone.utc).isoformat()
                logger.info("[live] %s close=%.6f", t_iso, float(last["close"]))
            time.sleep(poll_sec)
    except KeyboardInterrupt:
        logger.info("[live] stop by user")
        return 0


def _run_live_paper(args: argparse.Namespace) -> int:
    """
    Простейший paper: ведём equity=кеш (без сделок), чтобы проверить пайплайн сохранения CSV.
    """
    http_retries = int(getattr(args, "http_retries", 2))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    poll_sec = float(getattr(args, "poll_sec", 10))
    fee_bps = int(getattr(args, "fee_bps", 0))
    slip_bps = int(getattr(args, "slip_bps", 0))

    equity_csv = getattr(args, "csv_equity", None)
    trades_csv = getattr(args, "csv_trades", None)
    _ensure_dir(equity_csv)
    _ensure_dir(trades_csv)

    logger.info(
        "[live:paper] %s %s strategy=%s params=%s poll=%ss",
        args.pair,
        args.candles,
        args.strategy,
        json.dumps(_params_from_args(args), ensure_ascii=False),
        int(poll_sec),
    )
    if getattr(args, "summary_alert", False):
        logger.debug("[live:paper] summary-alert flag accepted (no-op notifier).")

    balance = float(getattr(args, "initial_balance", 0.0) or 0.0)
    if balance <= 0:
        balance = 1000.0  # дефолтный виртуальный капитал
    equity_rows: List[Dict[str, Any]] = []
    trades_rows: List[Dict[str, Any]] = []

    try:
        while True:
            df = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
            if not df.empty:
                last = df.iloc[-1]
                ts = int(last["ts"])
                price = float(last["close"])
                # Без сделок — чисто мониторинг equity
                equity_rows.append({"ts": ts, "equity": balance, "price": price, "fee_bps": fee_bps, "slip_bps": slip_bps})
                logger.info("[live:paper] %s close=%.6f sig=+0", datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), price)

                # периодически сохраняем
                if len(equity_rows) % 6 == 0 and equity_csv:
                    pd.DataFrame(equity_rows).to_csv(equity_csv, index=False)
            time.sleep(poll_sec)
    except KeyboardInterrupt:
        logger.info("[live:paper] stop by user")
        if trades_csv:
            pd.DataFrame(trades_rows).to_csv(trades_csv, index=False)
            logger.info("Saved trades CSV -> %s", trades_csv)
        if equity_csv:
            pd.DataFrame(equity_rows).to_csv(equity_csv, index=False)
            logger.info("Saved equity CSV -> %s", equity_csv)
        return 0


# ----------------------------- Парсер -----------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exmo-bot",
        description="EXMO research & live CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Глобальные опции (для помощи/--help). Фактически мы их парсим предварительно,
    # см. _run_cli — там разрешаем располагать флаги и до, и после подкоманды.
    parser.add_argument("--pair", default="DOGE_EUR", help="EXMO symbol, e.g. DOGE_EUR")
    parser.add_argument("--candles", default="5m:2000", help="timeframe:bars, e.g. 5m:2000")
    parser.add_argument("--fee-bps", dest="fee_bps", type=int, default=0, help="commission in bps (1/100 of percent)")
    parser.add_argument("--slip-bps", dest="slip_bps", type=int, default=0, help="slippage in bps")
    parser.add_argument("--http-retries", dest="http_retries", type=int, default=2)
    parser.add_argument("--http-backoff", dest="http_backoff", type=float, default=0.5)
    parser.add_argument("--debug", action="store_true", help="enable debug logging")

    # Частые параметры стратегий (опциональны)
    parser.add_argument("--ema-fast", dest="ema_fast", type=int)
    parser.add_argument("--ema-slow", dest="ema_slow", type=int)
    parser.add_argument("--adx-len", dest="adx_len", type=int)
    parser.add_argument("--adx-on", dest="adx_on", type=float)
    parser.add_argument("--adx-off", dest="adx_off", type=float)
    parser.add_argument("--require-di", dest="require_di", action="store_true")
    parser.add_argument("--atr-len", dest="atr_len", type=int)
    parser.add_argument("--atr-mult", dest="atr_mult", type=float)

    sub = parser.add_subparsers(dest="command", required=True)

    # sweep
    p = sub.add_parser("sweep", help="strategy sweep")
    p.add_argument("--strategies", default="auto", help="comma separated or 'auto'")
    p.add_argument("--metric", default="score")
    p.add_argument("--top-n", dest="top_n", type=int, default=10)
    p.add_argument("--min-trades", dest="min_trades", type=int, default=1)
    p.add_argument("--csv-results", dest="csv_results")
    p.set_defaults(_handler=_run_sweep)

    # optimize
    p = sub.add_parser("optimize", help="strategy optimize")
    p.add_argument("--strategy", required=True)
    p.add_argument("--metric", default="score")
    p.add_argument("--top-n", dest="top_n", type=int, default=10)
    p.add_argument("--min-trades", dest="min_trades", type=int, default=1)
    p.add_argument("--csv-results", dest="csv_results")
    p.set_defaults(_handler=_run_optimize)

    # robustness
    p = sub.add_parser("robustness", help="robustness test")
    p.add_argument("--strategy", required=True)
    p.add_argument("--robust-level", dest="robust_level", default="std", help="std/lo/hi or float (e.g. 0.1)")
    p.add_argument("--samples", type=int, default=20)
    p.add_argument("--csv-results", dest="csv_results")
    p.set_defaults(_handler=_run_robustness)

    # walk-forward
    p = sub.add_parser("walk-forward", help="walk-forward validation")
    p.add_argument("--strategies", default="auto", help="comma separated or 'auto'")
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--min-trades", dest="min_trades", type=int, default=1)
    p.add_argument("--wf-folds", dest="wf_folds", type=int, default=3)
    p.add_argument("--wf-train-frac", dest="wf_train_frac", type=float, default=0.7)
    p.add_argument("--grid-file", dest="grid_file", help="'-' to read JSON from stdin")
    p.add_argument("--csv-results", dest="csv_results")
    p.set_defaults(_handler=_run_walk_forward)

    # trade-live
    p = sub.add_parser("trade-live", help="live trading")
    p.add_argument("--mode", choices=["observe", "paper"], default="observe")
    p.add_argument("--strategy", default="ema_adx")
    p.add_argument("--poll-sec", dest="poll_sec", type=float, default=10.0)
    p.add_argument("--heartbeat-sec", dest="heartbeat_sec", type=float, default=60.0)
    p.add_argument("--summary-alert", dest="summary_alert", action="store_true")
    # paper extras
    p.add_argument("--initial-balance", dest="initial_balance", type=float, default=1000.0)
    p.add_argument("--csv-trades", dest="csv_trades")
    p.add_argument("--csv-equity", dest="csv_equity")

    def _dispatch_live(a: argparse.Namespace) -> int:
        return _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a)

    p.set_defaults(_handler=_dispatch_live)

    return parser


# ----------------------------- Entrypoint -----------------------------

def _dispatch_command(args: argparse.Namespace) -> int:
    return args._handler(args)  # type: ignore[attr-defined]


def _run_cli(argv: List[str]) -> int:
    # Предварительный парсер забирает ГЛОБАЛЬНЫЕ флаги из любого места,
    # чтобы после подкоманды их тоже можно было указывать.
    peek = argparse.ArgumentParser(add_help=False)
    # глобальные общие
    peek.add_argument("--pair")
    peek.add_argument("--candles")
    peek.add_argument("--fee-bps", dest="fee_bps", type=int)
    peek.add_argument("--slip-bps", dest="slip_bps", type=int)
    peek.add_argument("--http-retries", dest="http_retries", type=int)
    peek.add_argument("--http-backoff", dest="http_backoff", type=float)
    peek.add_argument("--debug", action="store_true")
    # частые параметры стратегий
    peek.add_argument("--ema-fast", dest="ema_fast", type=int)
    peek.add_argument("--ema-slow", dest="ema_slow", type=int)
    peek.add_argument("--adx-len", dest="adx_len", type=int)
    peek.add_argument("--adx-on", dest="adx_on", type=float)
    peek.add_argument("--adx-off", dest="adx_off", type=float)
    peek.add_argument("--require-di", dest="require_di", action="store_true")
    peek.add_argument("--atr-len", dest="atr_len", type=int)
    peek.add_argument("--atr-mult", dest="atr_mult", type=float)
    # NB: НЕ включаем сюда --strategy, т.к. он обязателен у optimize/robustness

    peeked, rest = peek.parse_known_args(argv)
    _configure_logging(bool(getattr(peeked, "debug", False)))
    logger.debug("Logging configured. Level=%s", "DEBUG" if getattr(peeked, "debug", False) else "INFO")

    parser = _build_parser()
    args = parser.parse_args(rest)

    # Смерджим глобальные флаги, которых нет у сабкоманды
    for k, v in vars(peeked).items():
        if getattr(args, k, None) in (None, False):
            setattr(args, k, v)

    logger.info("Command: %s", args.command)
    return _dispatch_command(args)


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(_run_cli(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001
        logger.exception("Fatal: %s", e)
        sys.exit(1)
