# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import csv
import inspect
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------- Strategy registry ----------
try:
    from src.domain.strategy import registry as strat_registry  # type: ignore
except Exception:
    try:
        from src.application.research.strategies import strat_registry  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Strategy registry not found. Ensure src/domain/strategy/registry.py exists."
        ) from e

# ---------- Optional research selector ----------
try:
    from src.application.research import selector as sel  # type: ignore
except Exception:
    sel = None

LOG = logging.getLogger("cli")


def _selector_invoke(func_name: str, **our_kwargs):
    """
    Универсально вызывает sel.<func_name>, автоматически маппя наши ключи
    на те, которые реально ожидает selector.<func_name>.
    """
    _require_sel()
    func = getattr(sel, func_name)  # type: ignore[attr-defined]
    sig = inspect.signature(func)
    expected = set(sig.parameters.keys())

    # Все возможные алиасы для часто используемых параметров:
    pref_map = {
        "exmo_pair": ["exmo_pair", "pair", "symbol", "asset", "market", "instrument"],
        "exmo_candles": ["exmo_candles", "candles", "candles_spec", "span", "bars"],
        "strategies": ["strategies", "strategy_list", "strats", "strategy"],
        # если останется только 'strategy', отдадим туда строку/первый элемент
        "strategy": ["strategy", "name"],
        "metric": ["metric", "score_metric", "target_metric"],
        "top_n": ["top_n", "top", "n_top"],
        "min_trades": ["min_trades", "mintrades", "min_trades_count"],
        "grid": ["grid", "grid_spec", "grid_dict"],
        "params": ["params", "strategy_params", "param_values"],
        "robust_level": ["robust_level", "level", "robustness_level"],
        "samples": ["samples", "n_samples", "num_samples"],
        "wf_folds": ["wf_folds", "folds", "n_folds"],
        "wf_train_frac": ["wf_train_frac", "train_frac", "train_fraction"],
        "http_retries": ["http_retries", "retries"],
        "http_backoff": ["http_backoff", "backoff", "backoff_factor"],
        "min_trades_oos": ["min_trades_oos"],  # на будущее
    }

    # Подготовим значения: копия, плюс ремонт 'strategies' -> 'strategy' если нужно
    values = dict(our_kwargs)

    # Если у функции нет 'strategies', но есть 'strategy' — сведём в одну стратегию
    if "strategies" in values and "strategies" not in expected and "strategy" in expected:
        s_val = values.get("strategies")
        if isinstance(s_val, (list, tuple)) and len(s_val) > 0:
            values["strategy"] = s_val[0]
        else:
            values["strategy"] = s_val
        values.pop("strategies", None)

    # Конечный kwargs только с разрешёнными именами
    call_kwargs = {}

    for our_key, val in values.items():
        # 1) Если ключ и так принимается функцией — берём его напрямую
        if our_key in expected:
            call_kwargs[our_key] = val
            continue

        # 2) Иначе проверяем алиасы
        aliases = pref_map.get(our_key, [])
        put = False
        for cand in aliases:
            if cand in expected:
                call_kwargs[cand] = val
                put = True
                break
        if put:
            continue

        # 3) Частные случаи:
        # - если у нас есть exmo_pair, а функция ожидает 'pair'
        if our_key == "exmo_pair" and "pair" in expected:
            call_kwargs["pair"] = val
            continue
        # - если у нас exmo_candles, а функция ждёт 'candles'/'candles_spec'
        if our_key == "exmo_candles":
            if "candles" in expected:
                call_kwargs["candles"] = val
                continue
            if "candles_spec" in expected:
                call_kwargs["candles_spec"] = val
                continue
        # - если есть wf_* алиасы
        if our_key == "wf_folds" and "folds" in expected:
            call_kwargs["folds"] = val
            continue
        if our_key == "wf_train_frac" and "train_frac" in expected:
            call_kwargs["train_frac"] = val
            continue

        # если ключ вообще не нужен функции — просто игнорируем

    # Особый случай: если функция принимает *args/**kwargs (очень либеральная), просто пробросим левые ключи
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if accepts_var_kw:
        # Пробросим всё, чего не хватает (не перекрывая уже выбранное)
        for k, v in values.items():
            if k not in call_kwargs:
                call_kwargs[k] = v

    return func(**call_kwargs)


def _save_results_csv_generic(results, csv_path: Optional[str]) -> None:
    if not csv_path:
        return
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)

    # Если у selector есть удобная утилита — используем её
    saver = getattr(sel, "save_results_csv", None)
    if callable(saver):
        saver(results, csv_path)  # type: ignore
        LOG.info("Saved CSV -> %s", csv_path)
        return

    # Иначе пишем простой CSV (список dict'ов или что получится)
    rows: List[dict] = []
    if isinstance(results, list):
        for r in results:
            if isinstance(r, dict):
                rows.append(r)
            else:
                rows.append({"value": str(r)})
    else:
        rows.append({"value": str(results)})

    # Заголовки — объединение ключей
    fieldnames: List[str] = sorted({k for row in rows for k in row.keys()}) or ["value"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    LOG.info("Saved CSV -> %s", csv_path)


# ---------- Logging ----------
def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOG.debug("Logging configured. Level=%s", "DEBUG" if debug else "INFO")


# ---------- Helpers / Aliases ----------
def _coalesce_pair_candles(args: argparse.Namespace) -> None:
    """
    Поддержка алиасов:
      --exmo-pair  <-> --pair
      --exmo-candles <-> --candles
    Гарантирует наличие args.pair/args.candles и args.exmo_pair/args.exmo_candles.
    """
    if getattr(args, "pair", None) and not getattr(args, "exmo_pair", None):
        args.exmo_pair = args.pair
    if getattr(args, "exmo_pair", None) and not getattr(args, "pair", None):
        args.pair = args.exmo_pair

    if getattr(args, "candles", None) and not getattr(args, "exmo_candles", None):
        args.exmo_candles = args.candles
    if getattr(args, "exmo_candles", None) and not getattr(args, "candles", None):
        args.candles = args.exmo_candles


def _read_grid_arg(grid_file: Optional[str]) -> Optional[dict]:
    """
    Возвращает dict для грид-поиска из файла или STDIN.
      - path == '-' -> читаем JSON из stdin
      - None -> None
      - иначе используем selector.load_grid_json
    """
    if not grid_file:
        return None
    if grid_file == "-":
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else None
    if sel is None:
        raise RuntimeError("selector is not available but --grid-file was provided.")
    return sel.load_grid_json(grid_file)  # type: ignore


def _params_from_args(args: argparse.Namespace, allow_empty: bool = False) -> Dict[str, Any]:
    """
    Собирает параметры стратегии из argparse.Namespace.
    Поддерживаемые ключи:
      --fast/--slow/--ema-fast/--ema-slow/--sma-fast/--sma-slow
      --adx-len/--adx-on/--adx-off/--require-di
      --atr-len/--atr-mult
      --st-len/--st-mult
      --kc-len/--kc-mult
      --min-adx/--chandelier-len
      --length/--mult/--exit-rule
      --n/--signal
      --params-json '{...}' (сливается поверх CLI)
    """
    import json as _json

    mapping = {
        "fast": "fast", "slow": "slow",
        "ema_fast": "fast", "ema_slow": "slow",
        "sma_fast": "fast", "sma_slow": "slow",

        "adx_len": "adx_len",
        "adx_on": "on",
        "adx_off": "off",
        "require_di": "require_di",

        "atr_len": "atr_len",
        "atr_mult": "atr_mult",

        "st_len": "st_len",
        "st_mult": "st_mult",

        "kc_len": "kc_len",
        "kc_mult": "kc_mult",

        "min_adx": "min_adx",
        "chandelier_len": "chandelier_len",

        "length": "length",
        "mult": "mult",
        "exit_rule": "exit_rule",

        "n": "n",
        "signal": "signal",

        "params_json": "__JSON__",
    }

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
        "_handler", "cmd",
    }

    def _coerce(v: Any) -> Any:
        if isinstance(v, (int, float, bool)) or v is None:
            return v
        s = str(v).strip()
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        try:
            if "." in s or "e" in s.lower():
                return float(s)
            return int(s)
        except Exception:
            return v

    params: Dict[str, Any] = {}
    for attr, val in vars(args).items():
        if attr in skip:
            continue
        if attr not in mapping:
            continue
        key = mapping[attr]
        if key == "__JSON__":
            if val:
                try:
                    js = _json.loads(val) if isinstance(val, str) else val
                    if isinstance(js, dict):
                        params.update(js)
                except Exception as e:
                    LOG.warning("Failed to parse --params-json: %s", e)
            continue
        if val is None:
            continue
        if isinstance(val, bool):
            if val:
                params[key] = True
            continue
        params[key] = _coerce(val)

    if not params and not allow_empty:
        LOG.debug("No strategy params were collected from CLI.")
    return params


# ---------- Safe converters ----------
def as_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    return int(s) if s else None


def as_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float):
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


# ---------- EXMO HTTP ----------
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
        allowed_methods=None,  # retry on any method
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
    """EXMO 't' может быть в секундах или миллисекундах. Возвращаем секунды."""
    try:
        t = int(float(x))
    except Exception:
        t = 0
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

    norm = []
    for k in raw or []:
        t = _ts_to_seconds(k.get("t"))
        try:
            o = float(k.get("o"))
            h = float(k.get("h"))
            l = float(k.get("l"))
            c = float(k.get("c"))
        except Exception:
            continue
        norm.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    norm.sort(key=lambda x: x["t"])

    ts: List[int] = [r["t"] for r in norm]
    o: List[float] = [r["o"] for r in norm]
    h: List[float] = [r["h"] for r in norm]
    l: List[float] = [r["l"] for r in norm]
    c: List[float] = [r["c"] for r in norm]
    return ts, o, h, l, c


# ---------- Metrics ----------
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


# ---------- Backtest engine ----------
@dataclass
class Trade:
    entry_ts: int
    entry_px: float
    side: int
    exit_ts: int
    exit_px: float
    pnl: float


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


# ---------- CSV helpers ----------
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


# ---------- Common CLI args ----------
def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strategy", default="sma")

    # EMA/SMA
    p.add_argument("--fast", type=int)
    p.add_argument("--slow", type=int)
    p.add_argument("--ema-fast", dest="fast", type=int)
    p.add_argument("--ema-slow", dest="slow", type=int)
    p.add_argument("--sma-fast", dest="fast", type=int)
    p.add_argument("--sma-slow", dest="slow", type=int)

    # ADX & filters
    p.add_argument("--adx-len", dest="adx_len", type=int)
    p.add_argument("--adx-on", dest="adx_on", type=float)
    p.add_argument("--adx-off", dest="adx_off", type=float)
    p.add_argument("--require-di", action="store_true")

    # ATR / SuperTrend / Keltner / прочее
    p.add_argument("--atr-len", dest="atr_len", type=int)
    p.add_argument("--atr-mult", dest="atr_mult", type=float)
    p.add_argument("--st-len", dest="st_len", type=int)
    p.add_argument("--st-mult", dest="st_mult", type=float)
    p.add_argument("--kc-len", dest="kc_len", type=int)
    p.add_argument("--kc-mult", dest="kc_mult", type=float)
    p.add_argument("--min-adx", dest="min_adx", type=float)
    p.add_argument("--chandelier-len", dest="chandelier_len", type=int)
    p.add_argument("--length", dest="length", type=int)
    p.add_argument("--mult", dest="mult", type=float)
    p.add_argument("--exit-rule", dest="exit_rule")
    p.add_argument("--n", dest="n", type=int)
    p.add_argument("--signal", dest="signal", type=int)
    p.add_argument("--params-json", dest="params_json", help="Extra params as JSON string")

    # EXMO data (с алиасами)
    p.add_argument("--exmo-pair", dest="pair", default="DOGE_EUR", help="EXMO symbol, e.g. DOGE_EUR")
    p.add_argument("--pair", dest="pair", help="Alias of --exmo-pair")
    p.add_argument("--exmo-candles", dest="candles", default="1m:500", help="e.g. 5m:2500")
    p.add_argument("--candles", dest="candles", help="Alias of --exmo-candles")

    # costs
    p.add_argument("--fee-bps", type=int, default=0)
    p.add_argument("--slip-bps", type=int, default=0)

    # infra
    p.add_argument("--http-retries", type=int)
    p.add_argument("--http-backoff", type=float)
    p.add_argument("--summary-alert", action="store_true")
    p.add_argument("--debug", action="store_true")


def _add_risk_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-position-pct", type=float)
    p.add_argument("--stop-loss-bps", type=int)
    p.add_argument("--max-daily-loss-bps", type=int)


# ---------- Commands: backtest / live ----------
def _run_backtest(args: argparse.Namespace) -> int:
    LOG.info("Command: backtest")
    _coalesce_pair_candles(args)
    ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)

    defn = strat_registry.get(args.strategy)
    params = _params_from_args(args, allow_empty=True)

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
    _coalesce_pair_candles(args)
    params = _params_from_args(args, allow_empty=True)
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
    _coalesce_pair_candles(args)
    params = _params_from_args(args, allow_empty=True)
    LOG.info("[live:paper] %s %s strategy=%s params=%s poll=%ss",
             args.pair, args.candles, args.strategy, params, args.poll_sec)
    if getattr(args, "summary_alert", False):
        LOG.debug("[live:paper] summary-alert flag accepted (no-op notifier).")

    initial_balance = as_float_or_none(getattr(args, "initial_balance", None)) or 1000.0
    fee_bps = args.fee_bps or 0
    slip_bps = args.slip_bps or 0
    max_pos_pct = pct01_or_none(getattr(args, "max_position_pct", None)) or 1.0
    stop_loss_bps = bps_or_none(getattr(args, "stop_loss_bps", None))
    _ = bps_or_none(getattr(args, "max_daily_loss_bps", None))  # зарезервировано

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
            status_text, state_info = defn.status(close=c, high=h, low=l, **params)  # type: ignore
            sig = int(state_info.get("signal", 0)) if isinstance(state_info, dict) else 0

            px = c[-1]
            tstamp = ts[-1]
            bps_cost = (fee_bps + slip_bps) * 1e-4

            # стоп-лосс
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

            # сигнал сменился
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


# ---------- Research commands ----------
def _require_sel() -> None:
    if sel is None:
        raise RuntimeError("Research selector module not available (src/application/research/selector.py).")


# --- replace your _run_sweep with this version --------------------------------
def _run_sweep(args: argparse.Namespace) -> int:
    _require_sel()
    _coalesce_pair_candles(args)

    grid = _read_grid_arg(getattr(args, "grid_file", None))
    http_retries = as_int_or_none(getattr(args, "http_retries", None)) or 0
    http_backoff = as_float_or_none(getattr(args, "http_backoff", None)) or 0.0

    # strategies может быть "auto" (строка) — пробрасываем как есть
    results = _selector_invoke(
        "sweep",
        exmo_pair=args.exmo_pair,
        exmo_candles=args.exmo_candles,
        strategies=args.strategies,
        metric=args.metric,
        top_n=int(getattr(args, "top_n", 0) or 0),
        min_trades=int(getattr(args, "min_trades", 0) or 0),
        grid=grid,
        http_retries=http_retries,
        http_backoff=http_backoff,
    )

    _save_results_csv_generic(results, getattr(args, "csv_results", None))
    return 0


# --- replace your _run_optimize with this version ------------------------------
def _run_optimize(args: argparse.Namespace) -> int:
    _require_sel()
    _coalesce_pair_candles(args)

    grid = _read_grid_arg(getattr(args, "grid_file", None))
    http_retries = as_int_or_none(getattr(args, "http_retries", None)) or 0
    http_backoff = as_float_or_none(getattr(args, "http_backoff", None)) or 0.0

    results = _selector_invoke(
        "optimize",
        exmo_pair=args.exmo_pair,
        exmo_candles=args.exmo_candles,
        strategy=args.strategy,
        metric=args.metric,
        top_n=int(getattr(args, "top_n", 0) or 0),
        min_trades=int(getattr(args, "min_trades", 0) or 0),
        grid=grid,
        http_retries=http_retries,
        http_backoff=http_backoff,
    )

    _save_results_csv_generic(results, getattr(args, "csv_results", None))
    return 0


# --- replace your _run_robustness with this version ----------------------------
def _run_robustness(args: argparse.Namespace) -> int:
    _require_sel()
    _coalesce_pair_candles(args)

    params = _params_from_args(args, allow_empty=True)
    http_retries = as_int_or_none(getattr(args, "http_retries", None)) or 0
    http_backoff = as_float_or_none(getattr(args, "http_backoff", None)) or 0.0

    results = _selector_invoke(
        "robustness",
        exmo_pair=args.exmo_pair,
        exmo_candles=args.exmo_candles,
        strategy=args.strategy,
        params=params,
        robust_level=getattr(args, "robust_level", "std"),
        samples=int(getattr(args, "samples", 0) or 0),
        http_retries=http_retries,
        http_backoff=http_backoff,
    )

    _save_results_csv_generic(results, getattr(args, "csv_results", None))
    return 0


# --- replace your _run_walk_forward with this version --------------------------
def _run_walk_forward(args: argparse.Namespace) -> int:
    _require_sel()
    _coalesce_pair_candles(args)

    grid = _read_grid_arg(getattr(args, "grid_file", None))
    http_retries = as_int_or_none(getattr(args, "http_retries", None)) or 0
    http_backoff = as_float_or_none(getattr(args, "http_backoff", None)) or 0.0

    results = _selector_invoke(
        "walk_forward",
        exmo_pair=args.exmo_pair,
        exmo_candles=args.exmo_candles,
        strategies=args.strategies,
        metric=args.metric,
        min_trades=int(getattr(args, "min_trades", 0) or 0),
        wf_folds=int(getattr(args, "wf_folds", 0) or 0),
        wf_train_frac=float(getattr(args, "wf_train_frac", 0.7) or 0.7),
        grid=grid,
        http_retries=http_retries,
        http_backoff=http_backoff,
    )

    _save_results_csv_generic(results, getattr(args, "csv_results", None))
    return 0


# ---------- Parser / Dispatcher ----------
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="exmo-bot", add_help=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    # backtest
    p = sub.add_parser("backtest", help="Run simple backtest over candles")
    _add_common_args(p)
    _add_risk_args(p)
    p.add_argument("--csv-trades")
    p.add_argument("--csv-equity")
    p.set_defaults(_handler=_run_backtest)

    # live
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

    # sweep
    p = sub.add_parser("sweep", help="Grid search over multiple strategies")
    _add_common_args(p)
    p.add_argument("--strategies", default="auto")
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--top-n", type=int, default=8)
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_sweep)

    # optimize
    p = sub.add_parser("optimize", help="Optimize a single strategy over a grid")
    _add_common_args(p)
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_optimize)

    # robustness
    p = sub.add_parser("robustness", help="Noise/perturbation robustness check")
    _add_common_args(p)
    p.add_argument("--robust-level", dest="robust_level", choices=["lite", "std", "hard"], default="std")
    p.add_argument("--samples", type=int, default=10)
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_robustness)

    # walk-forward
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
