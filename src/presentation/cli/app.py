# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import urllib3

# ===== Logging =====
logger = logging.getLogger("cli")


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.debug("Logging configured. Level=%s", "DEBUG" if debug else "INFO")


# ===== External modules (project) =====
# Стратегии
try:
    from src.domain.strategy.registry import get_definition as get_strategy_def
except Exception:
    # fallback на старый путь
    from src.application.research.strategies import strat_registry as _REG  # type: ignore

    def get_strategy_def(name: str):
        return _REG.get(name)

# Селектор (ресёрч операции)
from src.application.research import selector as sel  # type: ignore


# ===== EXMO candles fetch =====
_HTTP = urllib3.PoolManager(retries=False, timeout=urllib3.util.Timeout(connect=5.0, read=10.0))


def _parse_candles_spec(spec: str) -> Tuple[int, int]:
    """
    '5m:200' -> (resolution_seconds=300, count=200)
    '1m:1000' -> (60, 1000)
    """
    tf, cnt = spec.split(":")
    cnt_i = int(cnt)

    unit = tf[-1]
    num = int(tf[:-1])
    if unit == "m":
        res_sec = num * 60
    elif unit == "h":
        res_sec = num * 3600
    elif unit == "d":
        res_sec = num * 86400
    elif unit == "s":
        res_sec = num
    else:
        # по умолчанию считаем минуты
        res_sec = num * 60
    return res_sec, cnt_i


def _exmo_resolution_param(resolution_sec: int) -> int:
    """
    EXMO v1.1 принимает resolution как число минут (или 1 для 1m).
    """
    if resolution_sec < 60:
        return 1
    return resolution_sec // 60


def _normalize_exmo_ts(ts: int | float) -> int:
    """
    EXMO иногда возвращает секунды, иногда миллисекунды. Нормализуем к секундам.
    """
    t = int(ts)
    if t > 10_000_000_000:  # миллисекунды
        return t // 1000
    return t


def _fetch_exmo_ohlc(
    pair: str,
    spec: str,
    http_retries: int = 3,
    http_backoff: float = 0.5,
) -> Dict[str, List[float]]:
    """
    Возвращает словарь списков: t, o, h, l, c (timestamps в секундах UTC)
    """
    res_sec, count = _parse_candles_spec(spec)
    resolution = _exmo_resolution_param(res_sec)

    now = int(time.time())
    span_sec = res_sec * count
    frm = now - span_sec
    to = now

    url = (
        f"https://api.exmo.com/v1.1/candles_history"
        f"?symbol={pair}&resolution={resolution}&from={frm}&to={to}"
    )

    attempt = 0
    while True:
        try:
            r = _HTTP.request("GET", url)
            if r.status != 200:
                raise RuntimeError(f"EXMO HTTP {r.status}")
            data = json.loads(r.data.decode("utf-8"))
            candles = data.get("candles") or []

            t_list: List[int] = []
            o_list: List[float] = []
            h_list: List[float] = []
            l_list: List[float] = []
            c_list: List[float] = []

            for c in candles:
                # поля: t, o, h, l, c, v
                t = _normalize_exmo_ts(c.get("t", 0))
                t_list.append(t)
                o_list.append(float(c.get("o", 0.0)))
                h_list.append(float(c.get("h", 0.0)))
                l_list.append(float(c.get("l", 0.0)))
                c_list.append(float(c.get("c", 0.0)))

            # гарантируем наличие данных
            if not t_list or not c_list:
                raise RuntimeError("Empty candles from EXMO")

            return {"t": t_list, "o": o_list, "h": h_list, "l": l_list, "c": c_list}
        except Exception as e:
            attempt += 1
            if attempt > http_retries:
                logger.error("EXMO fetch failed after %d attempts: %s", attempt - 1, e)
                raise
            sleep_s = http_backoff * (2 ** (attempt - 1))
            logger.warning("EXMO fetch failed (attempt %d/%d): %s; retry in %.2fs",
                           attempt, http_retries, e, sleep_s)
            time.sleep(sleep_s)


# ===== Helpers =====
def _weights_from_args(args: argparse.Namespace) -> Optional[Dict[str, float]]:
    """
    Весовые коэффициенты для score (если нужны). Если флагов нет — вернём None.
    Поддерживаем флаг вида: --score-weights "win=0.2,total=0.4,sharpe=0.4"
    """
    raw = getattr(args, "score_weights", None)
    if not raw:
        return None
    weights: Dict[str, float] = {}
    for part in str(raw).split(","):
        if not part.strip():
            continue
        k, v = part.split("=")
        weights[k.strip()] = float(v.strip())
    return weights


def _params_from_args(strategy: str, args: argparse.Namespace) -> Dict[str, Any]:
    """
    Извлекаем параметры стратегии из CLI аргументов.
    Поддержаны: ema, ema_adx, ema_adx_atr (можно расширять по мере необходимости).
    """
    out: Dict[str, Any] = {}

    def _maybe(name: str, cast=float):
        if hasattr(args, name) and getattr(args, name) is not None:
            try:
                out[name.replace("-", "_")] = cast(getattr(args, name))
            except Exception:
                pass

    # общее (EMA)
    _maybe("ema_fast", int)
    _maybe("ema_slow", int)

    if strategy in ("ema_adx", "ema_adx_atr"):
        _maybe("adx_len", int)
        _maybe("adx_on", float)
        _maybe("adx_off", float)
        if hasattr(args, "require_di"):
            out["require_di"] = bool(getattr(args, "require_di"))

    if strategy == "ema_adx_atr":
        _maybe("atr_len", int)
        _maybe("atr_mult", float)

    return out


def _print_table(headers: List[str], rows: List[List[Any]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(row: List[Any]) -> str:
        return "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

    logger.info(fmt(headers))
    for r in rows:
        logger.info(fmt(r))


def _selector_invoke(
    func_name: str,
    *,
    ohlc: Dict[str, List[float]],
    strategy: str | None = None,
    strategies: List[str] | None = None,
    metric: str | None = None,
    top_n: int | None = None,
    min_trades: int | None = None,
    fee_bps: int = 10,
    slip_bps: int = 2,
    grid: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Any:
    """
    Универсальный адаптер к src.application.research.selector.*
    Приводит аргументы к актуальным сигнатурам селектора.
    """
    func = getattr(sel, func_name)

    call_kwargs: Dict[str, Any] = {
        "ohlc": ohlc,
        "fee_bps": fee_bps,
        "slip_bps": slip_bps,
    }
    if strategy is not None:
        call_kwargs["strategy"] = strategy
    if strategies is not None:
        call_kwargs["strategies"] = strategies
    if metric is not None:
        call_kwargs["metric"] = metric
    if top_n is not None:
        call_kwargs["top_n"] = top_n
    if min_trades is not None:
        call_kwargs["min_trades"] = min_trades
    if grid is not None:
        call_kwargs["grid"] = grid
    if weights is not None and func_name in ("sweep", "optimize"):
        call_kwargs["score_weights"] = weights

    return func(**call_kwargs)


# ===== Commands =====
def _run_sweep(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 3))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)

    strategies = []
    if args.strategies == "auto":
        strategies = ["sma", "ema", "ema_adx", "ema_adx_atr", "supertrend",
                      "keltner", "adx", "sma_atr", "rsi2", "donchian", "bbands", "roc"]
    else:
        strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    weights = _weights_from_args(args)

    results = _selector_invoke(
        "sweep",
        ohlc=ohlc,
        strategies=strategies,
        metric=args.metric,
        top_n=int(args.top_n),
        min_trades=int(args.min_trades),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        weights=weights,
    )

    # вывод
    headers = ["strategy", "params", "trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score"]
    rows: List[List[Any]] = []
    for r in results:
        rows.append([
            r.get("strategy"),
            json.dumps(r.get("params"), ensure_ascii=False),
            r.get("trades"),
            f"{r.get('win_rate', 0.0):.1f}",
            f"{r.get('avg_pnl', 0.0):.6f}",
            f"{r.get('total_pnl', 0.0):.6f}",
            f"{r.get('max_dd', 0.0):.6f}",
            f"{r.get('sharpe', 0.0):.3f}",
            f"{r.get('score', 0.0):.3f}",
        ])
    _print_table(headers, rows)

    if args.csv_results:
        import csv
        with open(args.csv_results, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow(r)
        logger.info("Saved sweep CSV -> %s", args.csv_results)

    return 0


def _run_optimize(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 3))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)

    grid = None
    if args.grid_file:
        grid = _load_grid_json(args.grid_file)

    weights = _weights_from_args(args)

    results = _selector_invoke(
        "optimize",
        ohlc=ohlc,
        strategy=args.strategy,
        metric=args.metric,
        top_n=int(args.top_n),
        min_trades=int(args.min_trades),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        grid=grid,
        weights=weights,
    )

    headers = ["strategy", "params", "trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score"]
    rows: List[List[Any]] = []
    for r in results:
        rows.append([
            r.get("strategy"),
            json.dumps(r.get("params"), ensure_ascii=False),
            r.get("trades"),
            f"{r.get('win_rate', 0.0):.1f}",
            f"{r.get('avg_pnl', 0.0):.6f}",
            f"{r.get('total_pnl', 0.0):.6f}",
            f"{r.get('max_dd', 0.0):.6f}",
            f"{r.get('sharpe', 0.0):.3f}",
            f"{r.get('score', 0.0):.3f}",
        ])
    _print_table(headers, rows)

    if args.csv_results:
        import csv
        with open(args.csv_results, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow(r)
        logger.info("Saved optimize CSV -> %s", args.csv_results)

    return 0


def _run_robustness(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 3))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)

    params = _params_from_args(args.strategy, args)

    results = sel.robustness(
        ohlc=ohlc,
        strategy=args.strategy,
        params=params if params else None,
        level=args.robust_level,
        samples=int(args.samples),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
    )

    # агрегируем в табличку
    headers = ["passes", "total", "pass_ratio", "avgSharpe", "avgTotal", "worstSharpe", "worstTotal", "robustScore"]
    rows = [[
        results.get("passes", 0),
        results.get("total", 0),
        f"{results.get('pass_ratio', 0.0):.3f}",
        f"{results.get('avg_sharpe', 0.0):.3f}",
        f"{results.get('avg_total', 0.0):.6f}",
        f"{results.get('worst_sharpe', 0.0):.3f}",
        f"{results.get('worst_total', 0.0):.6f}",
        f"{results.get('robust_score', 0.0):.3f}",
    ]]
    _print_table(headers, rows)

    if args.csv_results:
        import csv
        with open(args.csv_results, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow(r)
        logger.info("Saved robustness CSV -> %s", args.csv_results)

    return 0


def _run_walk_forward(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 3))
    http_backoff = float(getattr(args, "http_backoff", 0.5))
    ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)

    grid = None
    if args.grid_file:
        grid = _load_grid_json(args.grid_file)

    res = sel.walk_forward(
        ohlc=ohlc,
        strategies=[s.strip() for s in args.strategies.split(",") if s.strip()],
        metric=args.metric,
        min_trades=int(args.min_trades),
        folds=int(args.wf_folds),
        train_frac=float(args.wf_train_frac),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        grid=grid,
    )

    # печать
    logger.info(
        "WF aggregate: folds=%s trades=%s totalPnL=%.6f avgSharpe=%.2f",
        res.get("folds_total"), res.get("trades_total"),
        res.get("total_pnl", 0.0), res.get("avg_sharpe", 0.0)
    )

    if args.csv_results:
        import csv
        # Ожидаем, что res["folds"] — список словарей по фолдам
        headers = ["fold", "train_start", "train_end", "test_start", "test_end", "trades", "total", "sharpe", "best"]
        with open(args.csv_results, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for i, fold in enumerate(res.get("folds", []), 1):
                w.writerow([
                    i,
                    fold.get("train_start"),
                    fold.get("train_end"),
                    fold.get("test_start"),
                    fold.get("test_end"),
                    fold.get("trades"),
                    f"{fold.get('total', 0.0):.6f}",
                    f"{fold.get('sharpe', 0.0):.3f}",
                    json.dumps(fold.get("best"), ensure_ascii=False),
                ])
        logger.info("Saved walk-forward CSV -> %s", args.csv_results)

    return 0


# ===== Live (observe/paper) =====
def _run_live_observe(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 3))
    http_backoff = float(getattr(args, "http_backoff", 0.5))

    logger.info(
        "[live] observe %s %s strategy=%s params=%s poll=%ss",
        args.pair, args.candles, args.strategy,
        _params_from_args(args.strategy, args), int(args.poll_sec)
    )

    if getattr(args, "summary_alert", False):
        logger.debug("[live] summary-alert flag accepted (no-op notifier).")

    strategy_def = get_strategy_def(args.strategy)
    if not strategy_def:
        raise RuntimeError(f"Unknown strategy: {args.strategy}")

    while True:
        ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
        # последние значения
        t = ohlc["t"][-1]
        o = ohlc["o"][-1]
        h = ohlc["h"][-1]
        l = ohlc["l"][-1]
        c = ohlc["c"][-1]

        params = _params_from_args(args.strategy, args)

        # NB: используем open_ — так ожидают многие реализации status()
        status_text, _state = strategy_def.status(
            close=c, open_=o, high=h, low=l, **params
        )

        t_iso = datetime.fromtimestamp(int(t), tz=timezone.utc).isoformat()
        logger.info("[live] %s %s", t_iso, status_text)

        time.sleep(float(args.poll_sec))


def _run_live_paper(args: argparse.Namespace) -> int:
    http_retries = int(getattr(args, "http_retries", 3))
    http_backoff = float(getattr(args, "http_backoff", 0.5))

    logger.info(
        "[live:paper] %s %s strategy=%s params=%s poll=%ss",
        args.pair, args.candles, args.strategy,
        _params_from_args(args.strategy, args), int(args.poll_sec)
    )
    if getattr(args, "summary_alert", False):
        logger.debug("[live:paper] summary-alert flag accepted (no-op notifier).")

    strategy_def = get_strategy_def(args.strategy)
    if not strategy_def:
        raise RuntimeError(f"Unknown strategy: {args.strategy}")

    # простая paper-петля (без состояния — сохранение CSV на каждом тике)
    trades_path = getattr(args, "csv_trades", None)
    equity_path = getattr(args, "csv_equity", None)

    equity = 1_000.0  # абстрактная метрика equity, для демо
    position = 0  # -1 / 0 / +1

    while True:
        ohlc = _fetch_exmo_ohlc(args.pair, args.candles, http_retries, http_backoff)
        t = ohlc["t"][-1]
        o = ohlc["o"][-1]
        h = ohlc["h"][-1]
        l = ohlc["l"][-1]
        c = ohlc["c"][-1]
        params = _params_from_args(args.strategy, args)

        status_text, state_info = strategy_def.status(
            close=c, open_=o, high=h, low=l, **params
        )
        sig = int(state_info.get("signal", 0)) if isinstance(state_info, dict) else 0

        # очень простой симулятор (для визуального движения equity)
        if sig != 0:
            position = sig
        equity += position * (c - o)  # псевдо-PnL

        t_iso = datetime.fromtimestamp(int(t), tz=timezone.utc).isoformat()
        logger.info("[live:paper] %s close=%.6f sig=%+d %s", t_iso, c, sig, status_text)

        if equity_path:
            with open(equity_path, "a", encoding="utf-8") as f:
                f.write(f"{t_iso},{equity:.6f}\n")

        if trades_path and sig != 0:
            with open(trades_path, "a", encoding="utf-8") as f:
                f.write(f"{t_iso},{sig},{c:.6f}\n")

        time.sleep(float(args.poll_sec))


# ===== Grid loader =====
def _load_grid_json(path: str) -> Dict[str, List[Dict[str, Any]]]:
    if path == "-":
        data = sys.stdin.read()
        return json.loads(data)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ===== CLI =====
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("exmo-bot")

    # общие флаги рынка (с обратной совместимостью имён)
    p.add_argument("--pair", "--exmo-pair", dest="pair", required=False, help="Symbol, e.g. DOGE_EUR")
    p.add_argument("--candles", "--exmo-candles", dest="candles", required=False, help='Like "5m:2500"')

    p.add_argument("--fee-bps", dest="fee_bps", type=int, default=10)
    p.add_argument("--slip-bps", dest="slip_bps", type=int, default=2)
    p.add_argument("--http-retries", dest="http_retries", type=int, default=3)
    p.add_argument("--http-backoff", dest="http_backoff", type=float, default=0.5)
    p.add_argument("--debug", dest="debug", action="store_true")

    sub = p.add_subparsers(dest="_cmd")

    # sweep
    sp = sub.add_parser("sweep")
    sp.set_defaults(_handler=_run_sweep)
    sp.add_argument("--strategies", required=True)  # "auto" | "a,b,c"
    sp.add_argument("--metric", required=True)
    sp.add_argument("--top-n", dest="top_n", type=int, default=5)
    sp.add_argument("--min-trades", dest="min_trades", type=int, default=1)
    sp.add_argument("--csv-results", dest="csv_results")
    sp.add_argument("--score-weights", dest="score_weights")

    # optimize
    sp = sub.add_parser("optimize")
    sp.set_defaults(_handler=_run_optimize)
    sp.add_argument("--strategy", required=True)
    sp.add_argument("--metric", required=True)
    sp.add_argument("--top-n", dest="top_n", type=int, default=5)
    sp.add_argument("--min-trades", dest="min_trades", type=int, default=1)
    sp.add_argument("--grid-file", dest="grid_file")
    sp.add_argument("--csv-results", dest="csv_results")
    sp.add_argument("--score-weights", dest="score_weights")

    # robustness
    sp = sub.add_parser("robustness")
    sp.set_defaults(_handler=_run_robustness)
    sp.add_argument("--strategy", required=True)
    sp.add_argument("--robust-level", dest="robust_level", type=float, default=0.1)
    sp.add_argument("--samples", type=int, default=25)
    sp.add_argument("--csv-results", dest="csv_results")

    # walk-forward
    sp = sub.add_parser("walk-forward")
    sp.set_defaults(_handler=_run_walk_forward)
    sp.add_argument("--strategies", required=True)  # "a,b,c"
    sp.add_argument("--metric", required=True)
    sp.add_argument("--min-trades", dest="min_trades", type=int, default=1)
    sp.add_argument("--wf-folds", dest="wf_folds", type=int, default=3)
    sp.add_argument("--wf-train-frac", dest="wf_train_frac", type=float, default=0.7)
    sp.add_argument("--grid-file", dest="grid_file")
    sp.add_argument("--csv-results", dest="csv_results")

    # trade-live
    sp = sub.add_parser("trade-live")
    sp.add_argument("--mode", choices=["observe", "paper"], required=True)
    sp.add_argument("--strategy", required=True)
    sp.add_argument("--poll-sec", dest="poll_sec", type=float, default=10.0)
    sp.add_argument("--summary-alert", dest="summary_alert", action="store_true")
    sp.add_argument("--csv-trades", dest="csv_trades")
    sp.add_argument("--csv-equity", dest="csv_equity")
    sp.set_defaults(_handler=lambda a: _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a))

    # Параметры стратегий (опционально)
    for name, tpe in [
        ("ema-fast", int), ("ema-slow", int),
        ("adx-len", int), ("adx-on", float), ("adx-off", float), ("require-di", None),
        ("atr-len", int), ("atr-mult", float),
    ]:
        flag = f"--{name}"
        dest = name.replace("-", "_")
        if tpe is None:
            p.add_argument(flag, dest=dest, action="store_true")
        else:
            p.add_argument(flag, dest=dest, type=tpe)

    return p


def _run_cli(argv: List[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    debug = bool(getattr(args, "debug", False))
    _setup_logging(debug)

    # sanity: для команд анализа требуем pair/candles
    if args._cmd in {"sweep", "optimize", "robustness", "walk-forward", "trade-live"}:
        if not args.pair or not args.candles:
            parser.error("--pair and --candles are required for this command")

    handler = getattr(args, "_handler", None)
    if not handler:
        parser.print_help()
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
