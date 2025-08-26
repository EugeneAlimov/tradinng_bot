# src/presentation/cli/app.py
from __future__ import annotations
import inspect

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _selector_call(func, **kwargs):
    """
    Универсальный адаптер: смотрит сигнатуру func и автоматически
    переименовывает наши канонические ключи в те, которые реально
    принимает целевая функция селектора.
    """
    # Карта синонимов: каноническое имя -> варианты, которые могут встречаться в селекторе
    synonyms = {
        "pair": ["pair", "symbol", "exmo_pair", "market", "pair_name"],
        "candles_spec": ["candles_spec", "candles", "span", "exmo_candles", "bars"],
        "strategies": ["strategies", "strategy_list", "names"],
        "strategy": ["strategy", "name"],
        "metric": ["metric", "score_metric"],
        "top_n": ["top_n", "top", "k"],
        "min_trades": ["min_trades", "mintrades", "min_trd"],
        "grid": ["grid", "grid_file", "grid_json"],
        "params": ["params", "strategy_params"],
        "robust": ["robust"],
        "robust_level": ["robust_level", "level"],
        "samples": ["samples", "n_samples"],
        "wf_folds": ["wf_folds", "folds"],
        "wf_train_frac": ["wf_train_frac", "train_frac"],
        "http_retries": ["http_retries", "retries"],
        "http_backoff": ["http_backoff", "backoff"],
    }

    sig = inspect.signature(func)
    accepted = set(sig.parameters.keys())

    remapped = {}
    # 1) если ключ уже принимается функцией — оставляем как есть
    for k, v in kwargs.items():
        if k in accepted:
            remapped[k] = v

    # 2) для прочих — ищем подходящий синоним из списка
    for canonical, variants in synonyms.items():
        if canonical in kwargs and canonical not in remapped:
            for name in variants:
                if name in accepted:
                    remapped[name] = kwargs[canonical]
                    break

    # 3) на всякий: отфильтруем неизвестные ключи, чтобы не падать
    filtered = {k: v for k, v in remapped.items() if k in accepted}

    return func(**filtered)


# ---- Strategies registry ----
try:
    from src.domain.strategy import registry as strat_registry  # type: ignore
except Exception:
    try:
        from src.application.research.strategies import strat_registry  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Strategy registry not found. Ensure src/domain/strategy/registry.py exists."
        ) from e

# ---- Research pipelines (optional) ----
try:
    from src.application.research import selector as sel  # type: ignore
except Exception:
    sel = None


def _params_from_args(args, allow_empty: bool = False) -> dict:
    """
    Собирает параметры стратегии из argparse.Namespace.

    Поддерживает алиасы CLI-опций:
      --ema-fast / --sma-fast / --fast         -> fast
      --ema-slow / --sma-slow / --slow         -> slow
      --adx-len                                -> adx_len
      --adx-on / --adx-off                     -> on / off
      --require-di                             -> require_di (bool)
      --atr-len / --atr-mult                   -> atr_len / atr_mult
      --kc-len / --kc-mult / --mode            -> kc_len / kc_mult / mode
      --min-adx                                -> min_adx
      --chandelier-len                         -> chandelier_len
      --length / --mult / --exit-rule          -> length / mult / exit_rule
      --n                                      -> n
      --signal                                 -> signal
      --params-json '{...}'                    -> сливается в итоговый словарь (поверх CLI)

    Игнорирует служебные поля (--pair/--candles/HTTP флаги и т.п.).
    """

    import json
    import logging
    log = logging.getLogger("cli")

    # arg.name -> ключ в params
    mapping = {
        "ema_fast": "fast", "sma_fast": "fast", "fast": "fast",
        "ema_slow": "slow", "sma_slow": "slow", "slow": "slow",

        "adx_len": "adx_len",
        "adx_on": "on",
        "adx_off": "off",
        "require_di": "require_di",

        "atr_len": "atr_len",
        "atr_mult": "atr_mult",

        "kc_len": "kc_len",
        "kc_mult": "kc_mult",
        "mode": "mode",

        "min_adx": "min_adx",
        "chandelier_len": "chandelier_len",

        "length": "length",
        "mult": "mult",
        "exit_rule": "exit_rule",

        "n": "n",
        "signal": "signal",

        # опционально: если в парсере есть такой аргумент
        "params_json": "__JSON__",  # специальный ключ для JSON-слияния
    }

    # Значения, которые точно не являются параметрами стратегии
    skip = {
        "pair", "exmo_pair", "candles", "exmo_candles",
        "strategies", "strategy", "metric", "top_n", "min_trades",
        "wf_folds", "wf_train_frac",
        "grid_file", "csv_results",
        "mode", "poll_sec", "heartbeat_sec",
        "initial_balance", "fee_bps", "slip_bps",
        "max_position_pct", "stop_loss_bps", "max_daily_loss_bps",
        "state_file",
        "summary_alert", "debug",
        "http_retries", "http_backoff",
        "_handler",
    }

    params: dict = {}

    def _coerce_number(x):
        # Тихая попытка привести строку к числу
        if isinstance(x, (int, float, bool)) or x is None:
            return x
        if isinstance(x, str):
            s = x.strip()
            try:
                if s.lower() in ("true", "false"):
                    return s.lower() == "true"
                if "." in s or "e" in s.lower():
                    return float(s)
                return int(s)
            except Exception:
                return x
        return x

    # Обходим все поля аргументов
    for attr, val in vars(args).items():
        if attr in skip:
            continue
        if attr not in mapping:
            # оставим молча — возможно это другой слой CLI
            continue

        key = mapping[attr]
        if key == "__JSON__":
            # Слить JSON в params
            if val:
                try:
                    if isinstance(val, str):
                        js = json.loads(val)
                    else:
                        js = val
                    if isinstance(js, dict):
                        for k, v in js.items():
                            params[k] = v
                except Exception as e:
                    log.warning("Failed to parse --params-json: %s", e)
            continue

        # Пропускаем None
        if val is None:
            continue

        # Булевы флаги типа --require-di добавляем только если True
        if isinstance(val, bool):
            if val:
                params[key] = True
            continue

        # Пробуем привести строки к числам где уместно
        params[key] = _coerce_number(val)

    if not params and not allow_empty:
        log.debug("No strategy params were collected from CLI.")

    return params


# ---- Safe converters ----
def as_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return None
        return int(value)
    s = str(value).strip()
    return int(s) if s else None


def as_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:
            return None
        return value
    if isinstance(value, int):
        return float(value)
    s = str(value).strip()
    return float(s) if s else None


def bps_or_none(value: Any) -> Optional[int]:
    i = as_int_or_none(value)
    return i if (i is not None and i >= 0) else None


def pct01_or_none(value: Any) -> Optional[float]:
    f = as_float_or_none(value)
    return f if (f is not None and f >= 0.0) else None


# ---- Logging ----
LOG = logging.getLogger("cli")


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOG.debug("Logging configured. Level=%s", "DEBUG" if debug else "INFO")


# ---- EXMO HTTP ----
import urllib3
from urllib3.util.retry import Retry

EXMO_HOST = "https://api.exmo.com"
EXMO_CANDLES_V = "/v1.1/candles_history"


def _resolution_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    raise ValueError(f"Unsupported timeframe: {tf}")


def _parse_pair(pair: str) -> str:
    return pair.strip().upper()


def _parse_candles_spec(spec: str) -> Tuple[str, int]:
    tf, cnt = spec.split(":")
    return tf.strip(), int(cnt)


def _build_http(retries: Optional[int], backoff: Optional[float]) -> urllib3.PoolManager:
    total = retries if retries is not None else as_int_or_none(os.getenv("HTTP_RETRIES"))
    back = backoff if backoff is not None else as_float_or_none(os.getenv("HTTP_BACKOFF"))
    total = total if total is not None else 3
    back = back if back is not None else 0.3
    retry = Retry(
        total=total,
        backoff_factor=back,
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
        allowed_methods=False,
    )
    return urllib3.PoolManager(retries=retry, timeout=urllib3.Timeout(connect=5.0, read=15.0))


def _exmo_candles_history(
        http: urllib3.PoolManager,
        pair: str,
        resolution_min: int,
        epoch_from: int,
        epoch_to: int,
) -> List[Dict[str, Any]]:
    params = {
        "symbol": pair,
        "resolution": str(resolution_min),
        "from": str(epoch_from),
        "to": str(epoch_to),
    }
    url = f"{EXMO_HOST}{EXMO_CANDLES_V}"
    r = http.request("GET", url, fields=params)
    if r.status != 200:
        LOG.error("EXMO candles_history failed: %s", r.status)
        raise RuntimeError(f"EXMO HTTP {r.status}")
    data = json.loads(r.data.decode("utf-8"))
    return data.get("candles") or []


def _ts_to_seconds(x: Any) -> int:
    """
    EXMO candles 't' может быть в секундах или миллисекундах.
    Приводим к секундам.
    """
    try:
        t = int(float(x))
    except Exception:
        t = 0
    # всё, что выглядит как миллисекунды, режем до секунд
    return t // 1000 if t > 10 ** 12 else t


def _get_candles_arrays(
        pair: str,
        spec: str,
        retries: Optional[int],
        backoff: Optional[float],
) -> Tuple[List[int], List[float], List[float], List[float], List[float]]:
    tf, count = _parse_candles_spec(spec)
    res_min = _resolution_minutes(tf)
    now = int(time.time())
    span = res_min * 60 * count
    frm = now - span
    to = now

    http = _build_http(retries, backoff)
    raw = _exmo_candles_history(http, _parse_pair(pair), res_min, frm, to)

    # Нормализуем и сортируем
    norm = []
    for k in raw or []:
        t = _ts_to_seconds(k.get("t"))
        try:
            o = float(k.get("o"))
            h = float(k.get("h"))
            l = float(k.get("l"))
            c = float(k.get("c"))
        except Exception:
            # пропустим кривую свечу
            continue
        norm.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    norm.sort(key=lambda x: x["t"])

    ts: List[int] = [r["t"] for r in norm]
    o: List[float] = [r["o"] for r in norm]
    h: List[float] = [r["h"] for r in norm]
    l: List[float] = [r["l"] for r in norm]
    c: List[float] = [r["c"] for r in norm]
    return ts, o, h, l, c


# ---- Stats ----
def _sharpe_by_trades(trade_pnls: List[float]) -> float:
    if not trade_pnls:
        return 0.0
    import math
    m = sum(trade_pnls) / len(trade_pnls)
    var = sum((x - m) ** 2 for x in trade_pnls) / len(trade_pnls)
    sd = math.sqrt(var) if var > 0 else 0.0
    return (m / sd) if sd > 0 else 0.0


def _max_drawdown(equity: List[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < mdd:
            mdd = dd
    return mdd


@dataclass
class Trade:
    entry_ts: int
    entry_px: float
    side: int
    exit_ts: int
    exit_px: float
    pnl: float


# ---- Params from CLI ----
def _build_params_from_args(strategy: str, args: argparse.Namespace) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    if getattr(args, "fast", None) is not None:
        p["fast"] = int(args.fast)
    if getattr(args, "slow", None) is not None:
        p["slow"] = int(args.slow)
    if getattr(args, "adx_len", None) is not None:
        p["adx_len"] = int(args.adx_len)
    if getattr(args, "on", None) is not None:
        p["on"] = float(args.on)
    if getattr(args, "off", None) is not None:
        p["off"] = float(args.off)
    if getattr(args, "require_di", False):
        p["require_di"] = True
    if getattr(args, "atr_len", None) is not None:
        p["atr_len"] = int(args.atr_len)
    if getattr(args, "atr_mult", None) is not None:
        p["atr_mult"] = float(args.atr_mult)
    if getattr(args, "st_len", None) is not None:
        p["atr_len"] = int(args.st_len)
    if getattr(args, "st_mult", None) is not None:
        p["mult"] = float(args.st_mult)
    return p


# ---- Backtest engine ----
def _run_backtest_signals(
        timestamps: List[int],
        open_: List[float],
        high: List[float],
        low: List[float],
        close: List[float],
        signals: List[int],
        fee_bps: int = 0,
        slip_bps: int = 0,
        stop_loss_bps: Optional[int] = None,
) -> Tuple[List[Trade], List[float]]:
    trades: List[Trade] = []
    eq: List[float] = []
    pos = 0
    entry_px = 0.0
    entry_ts = 0
    equity = 0.0
    bps_cost = (fee_bps + slip_bps) * 0.0001

    def exit_trade(i_idx: int):
        nonlocal pos, entry_px, entry_ts, equity
        if pos == 0:
            return
        px = close[i_idx]
        ts = timestamps[i_idx]
        raw_ret = (px - entry_px) / entry_px if pos > 0 else (entry_px - px) / entry_px
        pnl = raw_ret - 2 * bps_cost
        trades.append(Trade(entry_ts, entry_px, pos, ts, px, pnl))
        equity += pnl
        pos = 0
        entry_px = 0.0
        entry_ts = 0

    for i in range(len(close)):
        sig = signals[i] if i < len(signals) else 0
        eq.append(equity)

        if pos != 0 and stop_loss_bps is not None and stop_loss_bps > 0:
            adverse = (entry_px - low[i]) / entry_px if pos > 0 else (high[i] - entry_px) / entry_px
            if adverse > stop_loss_bps * 1e-4:
                exit_trade(i)
                continue

        if sig != pos:
            if pos != 0:
                exit_trade(i)
            if sig != 0:
                pos = sig
                entry_px = close[i]
                entry_ts = timestamps[i]

    if pos != 0:
        exit_trade(len(close) - 1)
    return trades, eq


# ---- CSV helpers ----
def _save_trades_csv(path: str, trades: List[Trade]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_ts", "entry_iso", "entry_px", "side", "exit_ts", "exit_iso", "exit_px", "pnl"])
        for t in trades:
            w.writerow([
                t.entry_ts,
                datetime.fromtimestamp(t.entry_ts, tz=timezone.utc).isoformat(),
                f"{t.entry_px:.6f}",
                t.side,
                t.exit_ts,
                datetime.fromtimestamp(t.exit_ts, tz=timezone.utc).isoformat(),
                f"{t.exit_px:.6f}",
                f"{t.pnl:.6f}",
            ])


def _save_equity_csv(path: str, timestamps: List[int], equity: List[float]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "iso", "equity"])
        for ts, eq in zip(timestamps, equity):
            w.writerow([ts, datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), f"{eq:.6f}"])


# ---- Common CLI args ----
def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strategy", default="sma")
    # EMA aliases + base
    p.add_argument("--fast", type=int)
    p.add_argument("--slow", type=int)
    p.add_argument("--ema-fast", dest="fast", type=int)  # alias for compatibility
    p.add_argument("--ema-slow", dest="slow", type=int)  # alias for compatibility

    # ADX & filters
    p.add_argument("--adx-len", dest="adx_len", type=int)
    p.add_argument("--adx-on", dest="on", type=float)
    p.add_argument("--adx-off", dest="off", type=float)
    p.add_argument("--require-di", action="store_true")

    # ATR / SuperTrend
    p.add_argument("--atr-len", dest="atr_len", type=int)
    p.add_argument("--atr-mult", dest="atr_mult", type=float)
    p.add_argument("--st-len", type=int)
    p.add_argument("--st-mult", type=float)

    # EXMO data
    p.add_argument("--exmo-pair", dest="pair", default="DOGE_EUR")
    p.add_argument("--exmo-candles", dest="candles", default="1m:500")

    # costs
    p.add_argument("--fee-bps", type=int, default=0)
    p.add_argument("--slip-bps", type=int, default=0)

    # infra
    p.add_argument("--http-retries", type=int)
    p.add_argument("--http-backoff", type=float)
    p.add_argument("--summary-alert", action="store_true")  # accepted & ignored for now
    p.add_argument("--debug", action="store_true")


def _add_risk_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-position-pct", type=float)
    p.add_argument("--stop-loss-bps", type=int)
    p.add_argument("--max-daily-loss-bps", type=int)


# ---- Commands ----
def _run_backtest(args: argparse.Namespace) -> int:
    LOG.info("Command: backtest")
    ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)
    defn = strat_registry.get(args.strategy)
    params = _build_params_from_args(args.strategy, args)
    # НЕ передаём open=
    signals = defn.generate_signals(close=c, high=h, low=l, **params)  # type: ignore

    trades, equity = _run_backtest_signals(
        timestamps=ts, open_=o, high=h, low=l, close=c, signals=signals,
        fee_bps=args.fee_bps or 0, slip_bps=args.slip_bps or 0,
        stop_loss_bps=bps_or_none(getattr(args, "stop_loss_bps", None)),
    )

    wins = sum(1 for t in trades if t.pnl > 0)
    n = len(trades)
    win_rate = (wins / n * 100.0) if n else 0.0
    avg_pnl = (sum(t.pnl for t in trades) / n) if n else 0.0
    total_pnl = sum(t.pnl for t in trades)
    maxdd = _max_drawdown(equity)
    sharpe = _sharpe_by_trades([t.pnl for t in trades])

    LOG.info("Backtest %s %s strategy=%s params=%s", args.pair, args.candles, args.strategy, params)
    LOG.info("Trades: %s  WinRate: %.1f%%  AvgPnL: %.6f  TotalPnL: %.6f  MaxDD: %.6f  Sharpe(trades): %.2f",
             n, win_rate, avg_pnl, total_pnl, maxdd, sharpe)

    if getattr(args, "csv_trades", None):
        _save_trades_csv(args.csv_trades, trades)
        LOG.info("Saved trades CSV -> %s", args.csv_trades)
    if getattr(args, "csv_equity", None):
        _save_equity_csv(args.csv_equity, ts, equity)
        LOG.info("Saved equity CSV -> %s", args.csv_equity)
    return 0


def _run_live_observe(args: argparse.Namespace) -> int:
    LOG.info("Command: trade-live")
    params = _build_params_from_args(args.strategy, args)
    LOG.info("[live] observe %s %s strategy=%s params=%s poll=%ss",
             args.pair, args.candles, args.strategy, params, args.poll_sec)
    if getattr(args, "summary_alert", False):
        LOG.debug("[live] summary-alert flag accepted (no-op notifier).")
    last_seen_ts = 0
    try:
        while True:
            ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)
            if ts and ts[-1] != last_seen_ts:
                last_seen_ts = ts[-1]
                defn = strat_registry.get(args.strategy)
                # НЕ передаём open=
                status_text, state = defn.status(close=c, high=h, low=l, **params)  # type: ignore
                t_iso = datetime.fromtimestamp(ts[-1], tz=timezone.utc).isoformat()
                LOG.info("[live] %s %s", t_iso, status_text)
            time.sleep(max(1, int(args.poll_sec)))
    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
    return 0


@dataclass
class PaperState:
    balance: float
    position: int
    pos_px: float
    last_day: str


def _load_state(path: Optional[str], initial_balance: float) -> PaperState:
    if not path or not os.path.exists(path):
        return PaperState(balance=initial_balance, position=0, pos_px=0.0, last_day="")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PaperState(**data)
    except Exception:
        return PaperState(balance=initial_balance, position=0, pos_px=0.0, last_day="")


def _save_state(path: Optional[str], state: PaperState) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, ensure_ascii=False, indent=2)


def _run_live_paper(args: argparse.Namespace) -> int:
    LOG.info("Command: trade-live")
    params = _build_params_from_args(args.strategy, args)
    LOG.info("[live:paper] %s %s strategy=%s params=%s poll=%ss",
             args.pair, args.candles, args.strategy, params, args.poll_sec)
    if getattr(args, "summary_alert", False):
        LOG.debug("[live:paper] summary-alert flag accepted (no-op notifier).")

    initial_balance = as_float_or_none(getattr(args, "initial_balance", None)) or 1000.0
    fee_bps = args.fee_bps or 0
    slip_bps = args.slip_bps or 0
    max_pos_pct = pct01_or_none(getattr(args, "max_position_pct", None)) or 1.0
    stop_loss_bps = bps_or_none(getattr(args, "stop_loss_bps", None))
    max_daily_loss_bps = bps_or_none(getattr(args, "max_daily_loss_bps", None))
    _ = max_daily_loss_bps  # reserved

    state = _load_state(getattr(args, "state_file", None), initial_balance)
    last_seen_ts = 0
    trades_out: List[Trade] = []
    eq_out_ts: List[int] = []
    eq_out: List[float] = []

    try:
        while True:
            ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)
            if not ts or ts[-1] == last_seen_ts:
                time.sleep(max(1, int(args.poll_sec)))
                continue
            last_seen_ts = ts[-1]

            defn = strat_registry.get(args.strategy)
            # НЕ передаём open=
            status_text, state_info = defn.status(close=c, high=h, low=l, **params)  # type: ignore
            sig = int(state_info.get("signal", 0)) if isinstance(state_info, dict) else 0

            px = c[-1]
            tstamp = ts[-1]
            bps_cost = (fee_bps + slip_bps) * 1e-4

            if state.position != 0 and stop_loss_bps:
                adverse = (state.pos_px - l[-1]) / state.pos_px if state.position > 0 else (h[
                                                                                                -1] - state.pos_px) / state.pos_px
                if adverse > stop_loss_bps * 1e-4:
                    raw_ret = (px - state.pos_px) / state.pos_px if state.position > 0 else (
                                                                                                    state.pos_px - px) / state.pos_px
                    pnl = raw_ret - 2 * bps_cost
                    state.balance *= (1.0 + pnl * max_pos_pct)
                    trades_out.append(Trade(entry_ts=tstamp, entry_px=state.pos_px, side=state.position,
                                            exit_ts=tstamp, exit_px=px, pnl=pnl))
                    state.position = 0
                    state.pos_px = 0.0

            if sig != state.position:
                if state.position != 0:
                    raw_ret = (px - state.pos_px) / state.pos_px if state.position > 0 else (
                                                                                                    state.pos_px - px) / state.pos_px
                    pnl = raw_ret - 2 * bps_cost
                    state.balance *= (1.0 + pnl * max_pos_pct)
                    trades_out.append(Trade(entry_ts=tstamp, entry_px=state.pos_px, side=state.position,
                                            exit_ts=tstamp, exit_px=px, pnl=pnl))
                    state.position = 0
                    state.pos_px = 0.0
                if sig != 0:
                    state.position = sig
                    state.pos_px = px

            eq_out_ts.append(tstamp)
            eq_out.append(state.balance)

            t_iso = datetime.fromtimestamp(tstamp, tz=timezone.utc).isoformat()
            LOG.info("[live:paper] %s close=%.6f sig=%+d %s", t_iso, px, sig, status_text)

            _save_state(getattr(args, "state_file", None), state)
            if getattr(args, "csv_trades", None) and trades_out:
                _save_trades_csv(args.csv_trades, trades_out)
            if getattr(args, "csv_equity", None) and eq_out_ts:
                _save_equity_csv(args.csv_equity, eq_out_ts, eq_out)

            time.sleep(max(1, int(args.poll_sec)))
    except KeyboardInterrupt:
        LOG.info("[live:paper] stop by user")
        if getattr(args, "csv_trades", None) and trades_out:
            LOG.info("Saved trades CSV -> %s", args.csv_trades)
        if getattr(args, "csv_equity", None) and eq_out_ts:
            LOG.info("Saved equity CSV -> %s", args.csv_equity)
    return 0


# ---- Research commands ----
def _require_sel() -> None:
    if sel is None:
        raise RuntimeError("Research selector module not available (src/application/research/selector.py).")


def _run_sweep(args) -> int:
    """
    Run strategy sweep over a strategy set.
    Supports:
      --pair / --candles  (и старые --exmo-pair / --exmo-candles)
      --strategies (csv | 'auto')
      --metric, --top-n, --min-trades
      --grid-file (путь или '-' для stdin)
      --csv-results
    """
    import sys, json, csv, logging
    log = logging.getLogger("cli")

    # ---- resolve pair & candles (поддержка старых имён) ----
    pair = getattr(args, "pair", None) or getattr(args, "exmo_pair", None)
    candles = getattr(args, "candles", None) or getattr(args, "exmo_candles", None)

    # ---- resolve strategies ----
    strategies_arg = getattr(args, "strategies", None)
    if not strategies_arg or str(strategies_arg).strip().lower() == "auto":
        strategies = [
            "sma", "ema", "ema_adx", "ema_adx_atr", "supertrend",
            "keltner", "adx", "sma_atr", "rsi2", "donchian", "bbands", "roc"
        ]
    else:
        strategies = [s.strip() for s in str(strategies_arg).split(",") if s.strip()]

    # ---- load grid if provided ----
    grid = None
    grid_file = getattr(args, "grid_file", None)
    if grid_file:
        if grid_file == "-":
            try:
                text = sys.stdin.read()
                grid = json.loads(text) if text.strip() else None
            except Exception as e:
                log.warning("Failed to read grid JSON from stdin: %s", e)
                grid = None
        else:
            try:
                # Используем имеющуюся утилиту из селектора, если она есть
                if hasattr(sel, "load_grid_json"):
                    grid = sel.load_grid_json(grid_file)  # type: ignore[attr-defined]
                else:
                    with open(grid_file, "r", encoding="utf-8") as f:
                        grid = json.load(f)
            except Exception as e:
                log.warning("Failed to load grid file %r: %s", grid_file, e)
                grid = None

    log.info(
        "Sweep %s %s strategies=%s metric=%s",
        pair, candles, strategies, getattr(args, "metric", None),
    )

    try:
        results = _selector_call(
            sel.sweep,
            pair=pair,
            candles_spec=candles,
            strategies=strategies,
            metric=getattr(args, "metric", None),
            top_n=getattr(args, "top_n", None),
            min_trades=getattr(args, "min_trades", None),
            grid=grid,
            http_retries=getattr(args, "http_retries", None),
            http_backoff=getattr(args, "http_backoff", None),
        )
    except Exception as e:
        log.exception("sweep failed: %s", e)
        return 1

    # ---- pretty print ----
    if not results:
        log.info("No results.")
    else:
        log.info("strategy  params  -- metrics --")
        for r in results:
            strategy = r.get("strategy") or r.get("name") or "?"
            params = r.get("params") or r.get("cfg") or {}
            # Сформируем краткую метрику
            metrics_keys = ["trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score", "calmar"]
            metrics = " ".join(
                f"{k}={r[k]!r}" for k in metrics_keys if k in r
            )
            log.info("%-10s %s  %s", strategy, params, metrics)

    # ---- save CSV if requested ----
    csv_path = getattr(args, "csv_results", None)
    if csv_path and results:
        try:
            # Унифицируем поля
            fieldnames = set()
            for r in results:
                fieldnames.update(r.keys())
            fieldnames = list(fieldnames)
            # Преобразуем params в JSON-строку для удобства
            rows = []
            for r in results:
                rr = dict(r)
                if "params" in rr and isinstance(rr["params"], (dict, list)):
                    rr["params"] = json.dumps(rr["params"], ensure_ascii=False)
                rows.append(rr)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)
            log.info("Saved sweep CSV -> %s", csv_path)
        except Exception as e:
            log.warning("Failed to save CSV %r: %s", csv_path, e)

    return 0


def _run_optimize(args) -> int:
    """
    Optimize a single strategy.
    Supports:
      --pair / --candles
      --strategy
      --metric, --top-n, --min-trades
      --grid-file (путь или '-' для stdin)
      --csv-results
    """
    import sys, json, csv, logging
    log = logging.getLogger("cli")

    pair = getattr(args, "pair", None) or getattr(args, "exmo_pair", None)
    candles = getattr(args, "candles", None) or getattr(args, "exmo_candles", None)

    grid = None
    grid_file = getattr(args, "grid_file", None)
    if grid_file:
        if grid_file == "-":
            try:
                text = sys.stdin.read()
                grid = json.loads(text) if text.strip() else None
            except Exception as e:
                log.warning("Failed to read grid JSON from stdin: %s", e)
                grid = None
        else:
            try:
                if hasattr(sel, "load_grid_json"):
                    grid = sel.load_grid_json(grid_file)  # type: ignore[attr-defined]
                else:
                    with open(grid_file, "r", encoding="utf-8") as f:
                        grid = json.load(f)
            except Exception as e:
                log.warning("Failed to load grid file %r: %s", grid_file, e)
                grid = None

    log.info(
        "Optimize %s %s strategy=%s metric=%s",
        pair, candles, getattr(args, "strategy", None), getattr(args, "metric", None),
    )

    try:
        results = _selector_call(
            sel.optimize,
            pair=pair,
            candles_spec=candles,
            strategy=getattr(args, "strategy", None),
            metric=getattr(args, "metric", None),
            top_n=getattr(args, "top_n", None),
            min_trades=getattr(args, "min_trades", None),
            grid=grid,
            http_retries=getattr(args, "http_retries", None),
            http_backoff=getattr(args, "http_backoff", None),
        )
    except Exception as e:
        log.exception("optimize failed: %s", e)
        return 1

    if not results:
        log.info("No results.")
    else:
        log.info("strategy  params  -- metrics --")
        for r in results:
            strategy = r.get("strategy") or r.get("name") or "?"
            params = r.get("params") or r.get("cfg") or {}
            metrics_keys = ["trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score", "calmar"]
            metrics = " ".join(
                f"{k}={r[k]!r}" for k in metrics_keys if k in r
            )
            log.info("%-10s %s  %s", strategy, params, metrics)

    csv_path = getattr(args, "csv_results", None)
    if csv_path and results:
        try:
            fieldnames = set()
            for r in results:
                fieldnames.update(r.keys())
            fieldnames = list(fieldnames)
            rows = []
            for r in results:
                rr = dict(r)
                if "params" in rr and isinstance(rr["params"], (dict, list)):
                    rr["params"] = json.dumps(rr["params"], ensure_ascii=False)
                rows.append(rr)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)
            log.info("Saved optimize CSV -> %s", csv_path)
        except Exception as e:
            log.warning("Failed to save CSV %r: %s", csv_path, e)

    return 0


def _run_robustness(args) -> int:
    """
    Robustness testing for a single strategy with fixed params.
    Supports:
      --pair / --candles
      --strategy + параметры стратегии из CLI (через _params_from_args)
      --robust (флаг), --robust-level, --samples
      --csv-results
    """
    import json, csv, logging
    log = logging.getLogger("cli")

    pair = getattr(args, "pair", None) or getattr(args, "exmo_pair", None)
    candles = getattr(args, "candles", None) or getattr(args, "exmo_candles", None)
    params = _params_from_args(args)  # существующий в app.py хелпер

    level = getattr(args, "robust_level", None)
    samples = getattr(args, "samples", None)

    log.info(
        "Robustness %s %s strategy=%s params=%s level=%s samples=%s",
        pair, candles, getattr(args, "strategy", None), params, level, samples,
    )

    try:
        res = _selector_call(
            sel.robustness,
            pair=pair,
            candles_spec=candles,
            strategy=getattr(args, "strategy", None),
            params=params,
            robust=True,
            robust_level=level,
            samples=samples,
            http_retries=getattr(args, "http_retries", None),
            http_backoff=getattr(args, "http_backoff", None),
        )
    except Exception as e:
        log.exception("robustness failed: %s", e)
        return 1

    # res может быть dict (агрегат) или list[dict] (сырые прогоны) — поддержим оба варианта
    csv_path = getattr(args, "csv_results", None)

    if isinstance(res, dict):
        # красивый лог агрегата
        if res:
            pretty = "  ".join(f"{k}={v!r}" for k, v in res.items())
            log.info(pretty)
        else:
            log.info("No robustness data.")
        # CSV (одна строка)
        if csv_path:
            try:
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(res.keys()))
                    w.writeheader()
                    w.writerow(res)
                log.info("Saved robustness CSV -> %s", csv_path)
            except Exception as e:
                log.warning("Failed to save CSV %r: %s", csv_path, e)

    elif isinstance(res, list):
        # список экспериментов
        if res:
            # Печать первых 5 строк как пример
            log.info("Robustness rows: %d", len(res))
            for r in res[:5]:
                short = {k: r[k] for k in ("calmar", "sharpe", "totalPnL", "params") if k in r}
                log.info("  %s", short)
        else:
            log.info("No robustness rows.")
        # CSV (много строк)
        if csv_path and res:
            try:
                fieldnames = set()
                for r in res:
                    fieldnames.update(r.keys())
                fieldnames = list(fieldnames)
                rows = []
                for r in res:
                    rr = dict(r)
                    if "params" in rr and isinstance(rr["params"], (dict, list)):
                        rr["params"] = json.dumps(rr["params"], ensure_ascii=False)
                    rows.append(rr)
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    w.writerows(rows)
                log.info("Saved robustness CSV -> %s", csv_path)
            except Exception as e:
                log.warning("Failed to save CSV %r: %s", csv_path, e)

    else:
        # неизвестный формат — просто залогируем repr
        log.info("Robustness result: %r", res)

    return 0


def _run_walk_forward(args) -> int:
    """
    Walk-Forward validation.
    Supports:
      --pair / --candles
      --strategies (csv | 'auto')
      --metric, --min-trades
      --wf-folds, --wf-train-frac
      --grid-file (путь или '-' для stdin)
      --csv-results
    """
    import sys, json, csv, logging
    log = logging.getLogger("cli")

    pair = getattr(args, "pair", None) or getattr(args, "exmo_pair", None)
    candles = getattr(args, "candles", None) or getattr(args, "exmo_candles", None)

    strategies_arg = getattr(args, "strategies", None)
    if not strategies_arg or str(strategies_arg).strip().lower() == "auto":
        strategies = [
            "sma", "ema", "ema_adx", "ema_adx_atr", "supertrend",
            "keltner", "adx", "sma_atr", "rsi2", "donchian", "bbands", "roc"
        ]
    else:
        strategies = [s.strip() for s in str(strategies_arg).split(",") if s.strip()]

    grid = None
    grid_file = getattr(args, "grid_file", None)
    if grid_file:
        if grid_file == "-":
            try:
                text = sys.stdin.read()
                grid = json.loads(text) if text.strip() else None
            except Exception as e:
                log.warning("Failed to read grid JSON from stdin: %s", e)
                grid = None
        else:
            try:
                if hasattr(sel, "load_grid_json"):
                    grid = sel.load_grid_json(grid_file)  # type: ignore[attr-defined]
                else:
                    with open(grid_file, "r", encoding="utf-8") as f:
                        grid = json.load(f)
            except Exception as e:
                log.warning("Failed to load grid file %r: %s", grid_file, e)
                grid = None

    folds = getattr(args, "wf_folds", None)
    train_frac = getattr(args, "wf_train_frac", None)

    log.info(
        "Walk-Forward %s %s strategies=%s folds=%s train_frac=%.2f metric=%s",
        pair, candles, strategies, folds, float(train_frac) if train_frac is not None else 0.0,
        getattr(args, "metric", None),
    )

    try:
        wf = _selector_call(
            sel.walk_forward,
            pair=pair,
            candles_spec=candles,
            strategies=strategies,
            metric=getattr(args, "metric", None),
            min_trades=getattr(args, "min_trades", None),
            grid=grid,
            wf_folds=folds,
            wf_train_frac=train_frac,
            http_retries=getattr(args, "http_retries", None),
            http_backoff=getattr(args, "http_backoff", None),
        )
    except Exception as e:
        log.exception("walk-forward failed: %s", e)
        return 1

    # Ожидаем словарь с агрегатом и, возможно, списком фолдов
    if isinstance(wf, dict):
        # краткий отчёт
        agg_keys = [
            "folds", "trades", "totalPnL", "avgSharpe",
            "oos_total_return_pct_mean", "oos_sharpe_mean", "oos_calmar_mean"
        ]
        short = {k: wf[k] for k in agg_keys if k in wf}
        log.info("WF aggregate: %s", {k: v for k, v in short.items() if k != "folds"})
        if "folds" in wf and isinstance(wf["folds"], list):
            for i, f in enumerate(wf["folds"], 1):
                # покажем кратко
                desc = {
                    k: f[k] for k in (
                        "train_start", "train_end", "test_start", "test_end",
                        "best_strategy", "best_params", "oos_sharpe", "oos_calmar", "oos_total_return_pct", "trades"
                    ) if k in f
                }
                log.info("[WF %d] %s", i, desc)

        # CSV
        csv_path = getattr(args, "csv_results", None)
        if csv_path:
            try:
                # Если есть folds — сохраним отдельной таблицей (fold per row)
                if "folds" in wf and isinstance(wf["folds"], list) and wf["folds"]:
                    folds_rows = []
                    for f in wf["folds"]:
                        rr = dict(f)
                        if "best_params" in rr and isinstance(rr["best_params"], (dict, list)):
                            rr["best_params"] = json.dumps(rr["best_params"], ensure_ascii=False)
                        folds_rows.append(rr)
                    fn = list({k for r in folds_rows for k in r.keys()})
                    with open(csv_path, "w", newline="", encoding="utf-8") as fo:
                        w = csv.DictWriter(fo, fieldnames=fn)
                        w.writeheader()
                        w.writerows(folds_rows)
                else:
                    # Иначе — одна строка агрегата
                    with open(csv_path, "w", newline="", encoding="utf-8") as fo:
                        w = csv.DictWriter(fo, fieldnames=list(wf.keys()))
                        w.writeheader()
                        w.writerow(wf)
                log.info("Saved walk-forward CSV -> %s", csv_path)
            except Exception as e:
                log.warning("Failed to save CSV %r: %s", csv_path, e)
    else:
        log.info("Walk-forward result: %r", wf)

    return 0


# ---- Parser/Dispatcher ----
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="exmo-bot", add_help=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backtest", help="Run simple backtest over candles")
    _add_common_args(p)
    _add_risk_args(p)
    p.add_argument("--csv-trades")
    p.add_argument("--csv-equity")
    p.set_defaults(_handler=_run_backtest)

    p = sub.add_parser("trade-live", help="Run live engine (observe or paper)")
    _add_common_args(p)
    p.add_argument("--mode", choices=["observe", "paper"], default="observe")
    p.add_argument("--poll-sec", type=int, default=10)
    p.add_argument("--heartbeat-sec", type=int, default=60)
    p.add_argument("--initial-balance", type=float)
    _add_risk_args(p)
    p.add_argument("--state-file")
    p.add_argument("--csv-trades")
    p.add_argument("--csv-equity")
    p.set_defaults(_handler=lambda a: _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a))

    p = sub.add_parser("sweep", help="Grid search over multiple strategies")
    _add_common_args(p)
    p.add_argument("--strategies", default="auto")
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--top-n", type=int, default=8)
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_sweep)

    p = sub.add_parser("optimize", help="Optimize a single strategy over a grid")
    _add_common_args(p)
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_optimize)

    p = sub.add_parser("robustness", help="Noise/perturbation robustness check")
    _add_common_args(p)
    p.add_argument("--robust-level", dest="robust_level", choices=["lite", "std", "hard"], default="std")
    p.add_argument("--samples", type=int, default=10)
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_robustness)

    p = sub.add_parser("walk-forward", help="Walk-forward validation")
    _add_common_args(p)
    p.add_argument("--strategies", default="auto")
    p.add_argument("--wf-folds", type=int, default=3)
    p.add_argument("--wf-train-frac", type=float, default=0.7)
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--min-trades", type=int, default=5)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_walk_forward)

    return ap


def _dispatch_command(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        raise SystemExit("No handler bound to command.")
    return handler(args)


def _run_cli(argv: Sequence[str]) -> int:
    debug = any(a in ("--debug",) for a in argv)
    _setup_logging(debug)
    parser = _build_parser()
    args = parser.parse_args(list(argv))
    return _dispatch_command(args)


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
