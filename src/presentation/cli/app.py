# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import random

import numpy as np
import pandas as pd
import urllib3
from urllib3.util import Retry, Timeout

LOG = logging.getLogger("cli")
EXMO_BASE_URL = "https://api.exmo.com"


# =========================
# ЛОГИРОВАНИЕ
# =========================
def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s %(levelname)s [cli] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# =========================
# CLI
# =========================
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot", description="EXMO research & live CLI")

    # Общие
    p.add_argument("--pair", type=str, default="DOGE_EUR", help="EXMO symbol, e.g. DOGE_EUR")
    p.add_argument("--candles", type=str, default="5m:2000", help="timeframe:bars, e.g. 5m:2000")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--out-dir", type=str, default="out/data", help="Where to save CSV/JSON results")

    # Сеть (дефолты включены)
    p.add_argument("--http-retries", type=int, default=3, help="HTTP retries")
    p.add_argument("--http-backoff", type=float, default=1.0, help="HTTP backoff factor (seconds)")
    p.add_argument("--http-timeout", type=float, default=10.0, help="HTTP total timeout (seconds)")

    sub = p.add_subparsers(dest="command", required=True)

    # sweep
    sp = sub.add_parser("sweep", help="Grid sweep over strategies/params")
    sp.add_argument("--strategies", type=str, default="auto", help="auto or list (comma-separated)")
    sp.add_argument("--metric", type=str, default="sharpe", help="primary metric to sort by")
    sp.add_argument("--top-n", type=int, default=3, help="top N results")
    sp.add_argument("--min-trades", type=int, default=1, help="min trades filter")
    sp.set_defaults(_handler=_run_sweep)

    # trade-live
    lp = sub.add_parser("trade-live", help="Live observe/paper/trade")
    lp.add_argument("--mode", type=str, choices=["observe", "paper", "live"], default="observe")
    lp.add_argument("--strategy", type=str, default="ema_adx")
    lp.add_argument("--ema-fast", type=int, default=12)
    lp.add_argument("--ema-slow", type=int, default=21)
    lp.add_argument("--adx-len", type=int, default=14)
    lp.add_argument("--adx-on", type=float, default=25.0)
    lp.add_argument("--adx-off", type=float, default=16.0)
    lp.add_argument("--require-di", action="store_true", help="Require DI alignment for entries")
    lp.add_argument("--atr-len", type=int, default=14)
    lp.add_argument("--atr-mult", type=float, default=0.0, help=">0 enables ATR stop")
    lp.add_argument("--poll-sec", type=int, default=10)
    lp.add_argument("--summary-alert", action="store_true", help="No-op notifier flag (placeholder)")
    lp.set_defaults(_handler=_dispatch_live)

    # optimize / robustness / walk-forward — stubs (не падают)
    op = sub.add_parser("optimize", help="Parameter optimization (stub)")
    op.set_defaults(_handler=_run_optimize_stub)

    rb = sub.add_parser("robustness", help="Robustness checks (stub)")
    rb.set_defaults(_handler=_run_robustness_stub)

    wf = sub.add_parser("walk-forward", help="Walk-forward analysis (stub)")
    wf.add_argument("--wf-folds", type=int, default=4)
    wf.add_argument("--wf-train-frac", type=float, default=0.7)
    wf.set_defaults(_handler=_run_walk_forward_stub)

    return p


# =========================
# ВСТРОЕННЫЙ HTTP (singleton)
# =========================
_PM: Optional[urllib3.PoolManager] = None
_RETRY: Optional[Retry] = None
_TIMEOUT: Optional[Timeout] = None


def _init_http(args: argparse.Namespace) -> None:
    global _PM, _RETRY, _TIMEOUT
    if _PM is not None:
        return
    retries = int(getattr(args, "http_retries", 3))
    backoff = float(getattr(args, "http_backoff", 1.0))
    timeout_sec = float(getattr(args, "http_timeout", 10.0))

    _RETRY = Retry(
        total=retries,
        connect=retries,
        read=retries,
        redirect=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods={"GET", "HEAD", "OPTIONS"},
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    _PM = urllib3.PoolManager(num_pools=4, maxsize=8, retries=False)
    _TIMEOUT = Timeout(total=timeout_sec)


def _sleep_with_jitter(base_sec: float) -> None:
    if base_sec <= 0:
        return
    time.sleep(base_sec + random.random() * base_sec * 0.25)


def _http_get_json(args: argparse.Namespace, url: str) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Единый GET JSON поверх встроенного urllib3 с ретраями и джиттером."""
    _init_http(args)
    assert _PM and _RETRY and _TIMEOUT
    attempt = 0
    while True:
        attempt += 1
        try:
            LOG.debug("Starting new HTTPS connection (1): api.exmo.com:443")
            r = _PM.request("GET", url, retries=_RETRY, timeout=_TIMEOUT, preload_content=True)
            status = int(r.status or 0)
            text = r.data.decode("utf-8", errors="replace") if r.data else ""
            if not text:
                if attempt > (_RETRY.total or 0):
                    return status, None
                _sleep_with_jitter(_RETRY.backoff_factor or 0.5)
                continue
            try:
                return status, json.loads(text)
            except Exception:
                LOG.warning("JSON parse failed (status=%s): %s...", status, text[:120])
                return status, None
        except Exception as e:
            LOG.warning("Retrying (attempt %s/%s) after error: %s",
                        attempt, (_RETRY.total or 0) + 1, e)
            if attempt > (_RETRY.total or 0):
                LOG.error("Fatal: HTTPSConnectionPool(host='api.exmo.com', port=443): fetch failed (status=0) %s", url)
                return 0, None
            _sleep_with_jitter(_RETRY.backoff_factor or 0.5)


# =========================
# УТИЛИТЫ
# =========================
def _ensure_out_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        LOG.warning("Cannot create out dir %s: %s", path, e)


def _parse_candles_arg(arg: str) -> Tuple[int, int]:
    """
    "5m:2000" -> (5, 2000)
    """
    tf, bars = arg.split(":")
    if not tf.endswith("m"):
        raise ValueError("Only minute resolution supported like 5m:2000")
    res = int(tf[:-1])
    n = int(bars)
    return res, n


def _epoch_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _epoch_series_to_seconds(s: pd.Series) -> pd.Series:
    """
    Приводим значения времени к секундам эпохи:
    - если максимум > 1e12 → считаем, что это миллисекунды и делим на 1000;
    - допускаем строки → to_numeric;
    - отбрасываем NaN и приводим к int64.
    """
    s_num = pd.to_numeric(s, errors="coerce")
    maxv = float(s_num.max()) if len(s_num) else 0.0
    if maxv > 1e12:  # миллисекунды
        s_num = (s_num / 1000.0)
    # округление вниз безопаснее для таймстемпов
    s_num = np.floor(s_num).astype("Int64")
    return s_num.astype("int64", errors="ignore")


# =========================
# EXMO OHLC
# =========================
def _fetch_exmo_ohlc(args: argparse.Namespace, pair: str, candles: str) -> pd.DataFrame:
    """
    Мягкие фейлы: при сетевой ошибке — пустой DataFrame (и предупреждение в лог).
    """
    res_min, bars = _parse_candles_arg(candles)
    now = _epoch_now()
    span_sec = res_min * 60 * bars
    t_from = now - span_sec
    t_to = now - 1  # отступим от текущего момента

    url = (
        f"{EXMO_BASE_URL}/v1.1/candles_history"
        f"?symbol={pair}&resolution={res_min}&from={t_from}&to={t_to}"
    )

    status, payload = _http_get_json(args, url)
    if status != 200 or payload is None:
        LOG.error(
            "Fatal: HTTPSConnectionPool(host='api.exmo.com', port=443): fetch failed (status=%s) %s",
            status, url
        )
        return pd.DataFrame()

    candles_list = payload.get("candles") or payload.get("data") or []
    if not isinstance(candles_list, list) or not candles_list:
        LOG.warning("EXMO returned empty candles for %s %s", pair, candles)
        return pd.DataFrame()

    df = pd.DataFrame(candles_list).rename(columns={
        "t": "time",
        "o": "open",
        "c": "close",
        "h": "high",
        "l": "low",
        "v": "volume",
    })

    # Нормализуем время → секунды эпохи, затем в UTC
    if "time" not in df.columns:
        LOG.warning("No 'time' column in payload, keys=%s", list(df.columns))
        return pd.DataFrame()

    df["time"] = _epoch_series_to_seconds(df["time"])
    # конвертируем в datetime с защитой от выходов за диапазон
    dt = pd.to_datetime(df["time"], unit="s", utc=True, errors="coerce")
    bad = dt.isna().sum()
    if bad:
        LOG.warning("Dropped %d rows with invalid timestamps", int(bad))
    df["dt"] = dt
    df = df.dropna(subset=["dt"]).sort_values("time").reset_index(drop=True)

    # Числовые столбцы
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df[["dt", "open", "high", "low", "close", "volume", "time"]]


# =========================
# ИНДИКАТОРЫ
# =========================
def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    a = high - low
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(span=length, adjust=False).mean()


def _dx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)
    tr = _true_range(high, low, close)
    atr = tr.ewm(span=length, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=length, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=length, adjust=False).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.ewm(span=length, adjust=False).mean()
    return adx.fillna(0.0), plus_di.fillna(0.0), minus_di.fillna(0.0)


# =========================
# ПРОСТОЙ БЭКТЕСТЕР EMA+ADX(+ATR)
# =========================
@dataclass
class EmaAdxParams:
    fast: int
    slow: int
    adx_len: int
    on: float
    off: float
    require_di: bool = True
    atr_len: int = 14
    atr_mult: float = 0.0  # <=0 => без стопа


def _backtest_ema_adx(df: pd.DataFrame, p: EmaAdxParams) -> Dict[str, Any]:
    if df.empty or len(df) < max(p.fast, p.slow, p.adx_len) + 5:
        return _empty_metrics()

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    ema_fast = _ema(close, p.fast)
    ema_slow = _ema(close, p.slow)
    adx, plus_di, minus_di = _dx(high, low, close, p.adx_len)
    atr = _atr(high, low, close, p.atr_len) if p.atr_mult > 0 else pd.Series(0.0, index=close.index)

    pos = 0  # 1 long, 0 flat
    entry = 0.0
    eq = 0.0
    pnl: List[float] = []
    trade_pnl: List[float] = []
    dd_peak = 0.0
    dd_min = 0.0

    for i in range(1, len(close)):
        f = ema_fast.iat[i]
        s = ema_slow.iat[i]
        _adx = adx.iat[i]
        _plus = plus_di.iat[i]
        _minus = minus_di.iat[i]
        c = close.iat[i]
        a = atr.iat[i]

        want_long = f > s and _adx >= p.on
        if p.require_di:
            want_long = want_long and (_plus > _minus)

        exit_signal = (pos == 1 and (_adx <= p.off or f < s))
        stop_price = entry - p.atr_mult * a if (pos == 1 and p.atr_mult > 0) else -np.inf
        hit_stop = pos == 1 and c <= stop_price

        if pos == 0 and want_long:
            pos = 1
            entry = c
        elif pos == 1 and (exit_signal or hit_stop):
            trade = c - entry
            eq += trade
            pnl.append(trade)
            trade_pnl.append(trade)
            pos = 0
            entry = 0.0

        dd_peak = max(dd_peak, eq)
        dd_min = min(dd_min, eq - dd_peak)

    if pos == 1:
        trade = close.iat[-1] - entry
        eq += trade
        pnl.append(trade)
        trade_pnl.append(trade)

    n_trades = len(trade_pnl)
    total_pnl = float(eq)
    avg_pnl = float(np.mean(trade_pnl)) if n_trades > 0 else 0.0
    win_rate = float((np.array(trade_pnl) > 0).mean()) if n_trades > 0 else 0.0

    ret = pd.Series(pnl, dtype=float)
    std = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0
    sharpe = (avg_pnl / std) if std > 0 else 0.0
    max_dd = float(dd_min)
    calmar = (total_pnl / abs(max_dd)) if max_dd < 0 else (
        math.copysign(math.inf, total_pnl) if total_pnl != 0 else 0.0)

    return {
        "n_trades": int(n_trades),
        "win_rate": round(win_rate * 100.0, 3),
        "avg_pnl": round(avg_pnl, 6),
        "total_pnl": round(total_pnl, 6),
        "max_dd": round(max_dd, 6),
        "sharpe": round(sharpe, 6),
        "calmar": round(calmar, 6),
    }


def _empty_metrics() -> Dict[str, Any]:
    return {
        "n_trades": 0,
        "win_rate": 0.0,
        "avg_pnl": 0.0,
        "total_pnl": 0.0,
        "max_dd": 0.0,
        "sharpe": 0.0,
        "calmar": 0.0,
    }


# =========================
# SWEEP
# =========================
def _sweep_param_grid(strategies: str) -> List[Tuple[str, Dict[str, Any]]]:
    grid: List[Tuple[str, Dict[str, Any]]] = []
    if strategies == "auto":
        base = dict(adx_len=14, on=22.0, off=18.0, require_di=True)
        grid.append(("ema_adx", dict(fast=10, slow=26, **base)))
        grid.append(("ema_adx_atr", dict(fast=10, slow=26, atr_len=14, atr_mult=2.0, **base)))
        grid.append(("ema_adx_atr", dict(fast=10, slow=26, atr_len=14, atr_mult=2.5, **base)))
    return grid


def _strategy_run(name: str, params: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    if name in ("ema_adx", "ema_adx_atr"):
        p = EmaAdxParams(
            fast=int(params.get("fast", 12)),
            slow=int(params.get("slow", 21)),
            adx_len=int(params.get("adx_len", 14)),
            on=float(params.get("on", 25.0)),
            off=float(params.get("off", 16.0)),
            require_di=bool(params.get("require_di", True)),
            atr_len=int(params.get("atr_len", 14)),
            atr_mult=float(params.get("atr_mult", 0.0)),
        )
        return _backtest_ema_adx(df, p)
    return _empty_metrics()


def _run_sweep(args: argparse.Namespace) -> int:
    LOG.info("Command: sweep")

    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.warning("No data for sweep. Exiting.")
        return 0

    grid = _sweep_param_grid(args.strategies)
    rows: List[Dict[str, Any]] = []
    for name, params in grid:
        metrics = _strategy_run(name, params, df)
        rows.append({
            "strategy": name,
            "params": json.dumps(params, separators=(",", ":"), ensure_ascii=False),
            **metrics,
        })

    if not rows:
        LOG.warning("No strategies to evaluate.")
        return 0

    res = pd.DataFrame(rows)
    res = res[res["n_trades"] >= int(args.min_trades)].copy()
    metric = args.metric if args.metric in res.columns else "sharpe"
    res = res.sort_values(metric, ascending=False, kind="mergesort").reset_index(drop=True)
    view = res.head(int(args.top_n)).copy()

    _print_table(view, metric)

    _ensure_out_dir(args.out_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"sweep_{args.pair}_{args.candles.replace(':', '-')}_{ts}"
    try:
        res.to_csv(os.path.join(args.out_dir, base + ".csv"), index=False)
        with open(os.path.join(args.out_dir, base + ".json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        LOG.warning("Cannot save results into %s: %s", args.out_dir, e)

    return 0


def _print_table(df: pd.DataFrame, metric: str) -> None:
    cols = [
        ("strategy", 10),
        ("params", 44),
        ("n_trades", 6),
        ("win_rate", 6),
        ("avg_pnl", 7),
        ("total_pnl", 9),
        ("max_dd", 7),
        ("sharpe", 7),
        (metric, len(metric)),
    ]
    header = "  ".join([f"{n:>{max(w, len(n))}}" for n, w in cols])
    sep = "  ".join(["-" * max(w, len(n)) for n, w in cols])
    LOG.info("  %s", header)
    LOG.info("  %s", sep)
    for _, r in df.iterrows():
        line = "  ".join([
            f"{str(r.get('strategy', '')):>10}",
            f"{str(r.get('params', '')):>44}",
            f"{int(r.get('n_trades', 0)):>6}",
            f"{float(r.get('win_rate', 0.0)):>6.3f}",
            f"{float(r.get('avg_pnl', 0.0)):>7.3f}",
            f"{float(r.get('total_pnl', 0.0)):>9.3f}",
            f"{float(r.get('max_dd', 0.0)):>7.3f}",
            f"{float(r.get('sharpe', 0.0)):>7.3f}",
            f"{float(r.get(metric, 0.0)):>{len(metric)}.3f}",
        ])
        LOG.info("  %s", line)


# =========================
# LIVE
# =========================
def _dispatch_live(args: argparse.Namespace) -> int:
    if args.mode == "paper":
        return _run_live_paper(args)
    return _run_live_observe(args)


def _run_live_observe(args: argparse.Namespace) -> int:
    LOG.info(
        "[live] observe %s %s strategy=%s params=%s poll=%ss",
        args.pair,
        args.candles,
        args.strategy,
        json.dumps({
            "fast": args.ema_fast, "slow": args.ema_slow,
            "adx_len": args.adx_len, "on": args.adx_on, "off": args.adx_off,
            "require_di": bool(args.require_di)
        }),
        int(args.poll_sec),
    )
    if args.summary_alert:
        LOG.debug("[live] summary-alert flag accepted (no-op notifier).")

    try:
        while True:
            df = _fetch_exmo_ohlc(args, args.pair, args.candles)
            if not df.empty:
                last = df.iloc[-1]
                LOG.info("[live] %s close=%.6f", last["dt"].isoformat(), float(last["close"]))
            else:
                LOG.warning("[live] empty data")
            time.sleep(max(1, int(args.poll_sec)))
    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
        return 0


def _run_live_paper(args: argparse.Namespace) -> int:
    LOG.info("[live] paper mode is not implemented yet (stub).")
    return 0


# =========================
# STUBS
# =========================
def _run_optimize_stub(args: argparse.Namespace) -> int:
    LOG.info("Command: optimize (stub) — not implemented yet.")
    return 0


def _run_robustness_stub(args: argparse.Namespace) -> int:
    LOG.info("Command: robustness (stub) — not implemented yet.")
    return 0


def _run_walk_forward_stub(args: argparse.Namespace) -> int:
    LOG.info(
        "Command: walk-forward (stub) — folds=%s train_frac=%.2f",
        getattr(args, "wf_folds", 4),
        getattr(args, "wf_train_frac", 0.7),
    )
    return 0


# =========================
# ENTRY
# =========================
def _dispatch_command(args: argparse.Namespace) -> int:
    return args._handler(args)  # type: ignore[attr-defined]


def _run_cli(argv: List[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(bool(getattr(args, "debug", False)))
    LOG.debug("Logging configured. Level=%s", "DEBUG" if args.debug else "INFO")
    return _dispatch_command(args)


def main() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
