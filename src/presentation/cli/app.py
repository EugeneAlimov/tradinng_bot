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
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# HTTP клиент (инфраструктура проекта)
# ---------------------------------------------------------------------
try:
    from src.infrastructure.http.http_utils import HttpClient, HttpConfig
except Exception as e:  # fallback на простейший клиент через urllib3
    import urllib3  # type: ignore


    class HttpConfig:  # type: ignore[no-redef]
        def __init__(self, base_url: str = "https://api.exmo.com", retries: int = 3, backoff: float = 1.0,
                     timeout: float = 15.0):
            self.base_url = base_url
            self.retries = retries
            self.backoff = backoff
            self.timeout = timeout


    class HttpClient:  # type: ignore[no-redef]
        def __init__(self, cfg: HttpConfig):
            self.base_url = cfg.base_url.rstrip("/")
            retries = urllib3.Retry(
                total=cfg.retries,
                backoff_factor=cfg.backoff,
                status_forcelist=(429, 500, 502, 503, 504),
                raise_on_status=False,
                raise_on_redirect=False,
            )
            self._http = urllib3.PoolManager(timeout=cfg.timeout, retries=retries)

        def get_json(self, url: str) -> Tuple[int, Any]:
            r = self._http.request("GET", url)
            status = int(r.status or 0)
            try:
                data = json.loads(r.data.decode("utf-8"))
            except Exception:
                data = None
            return status, data


# ---------------------------------------------------------------------
# Метрики (переиспользуем твой src/backtest/metrics.py, иначе — локальный fallback)
# ---------------------------------------------------------------------
def _local_drawdown_and_equity(pnl: np.ndarray) -> Tuple[float, float]:
    equity = np.cumsum(pnl)
    if equity.size == 0:
        return 0.0, 0.0
    run_max = np.maximum.accumulate(equity)
    dd = equity - run_max
    max_dd = float(dd.min()) if dd.size else 0.0
    return max_dd, float(equity[-1])


def _local_metrics(pnl: np.ndarray) -> Dict[str, float]:
    n = int(pnl.size)
    total = float(pnl.sum()) if n else 0.0
    avg = float(total / n) if n else 0.0
    wins = int((pnl > 0).sum()) if n else 0
    win_rate = float(wins / n * 100.0) if n else 0.0
    max_dd, equity_last = _local_drawdown_and_equity(pnl)
    # простой шарп по сделкам
    std = float(np.std(pnl, ddof=1)) if n > 1 else 0.0
    sharpe = float(avg / std) if std > 1e-12 else 0.0
    calmar = float((total / abs(max_dd)) if max_dd < 0 else 0.0)
    return {
        "n_trades": n,
        "win_rate": win_rate,
        "avg_pnl": avg,
        "total_pnl": total,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
    }


# пробуем импортировать проектные метрики
_compute_metrics = None  # type: ignore
try:
    from src.backtest.metrics import compute_metrics as _project_compute_metrics  # type: ignore


    def _wrapped_project_metrics(pnl: np.ndarray) -> Dict[str, float]:
        # ожидаем, что проектная функция умеет принимать pnl либо (equity/pnl, dt)
        m = _project_compute_metrics(pnl=pnl)  # type: ignore[call-arg]
        # приводим к ожидаемым ключам/типам
        out = {
            "n_trades": int(m.get("n_trades", len(pnl))),
            "win_rate": float(m.get("win_rate", 0.0)),
            "avg_pnl": float(m.get("avg_pnl", 0.0)),
            "total_pnl": float(m.get("total_pnl", float(np.sum(pnl)))),
            "max_dd": float(m.get("max_dd", 0.0)),
            "sharpe": float(m.get("sharpe", 0.0)),
            "calmar": float(m.get("calmar", 0.0)),
        }
        return out


    _compute_metrics = _wrapped_project_metrics
except Exception:
    _compute_metrics = _local_metrics

# ---------------------------------------------------------------------
# Утилиты CLI / Логирование
# ---------------------------------------------------------------------
LOG = logging.getLogger("cli")


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------
# Парсинг фрейма свечей "5m:2000"
# ---------------------------------------------------------------------
_RESOLUTION_MAP = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


@dataclass
class CandleSpec:
    tf_str: str
    tf_minutes: int
    bars: int


def _parse_candles(spec: str) -> CandleSpec:
    # формат "5m:2000"
    tf, bars = spec.split(":")
    tf = tf.strip().lower()
    bars_i = int(bars)
    if tf not in _RESOLUTION_MAP:
        raise ValueError(f"Unsupported timeframe '{tf}'")
    return CandleSpec(tf_str=tf, tf_minutes=_RESOLUTION_MAP[tf], bars=bars_i)


# ---------------------------------------------------------------------
# Загрузка OHLC с EXMO
# ---------------------------------------------------------------------
_HTTP: Optional[HttpClient] = None


def _get_http(args) -> HttpClient:
    global _HTTP
    if _HTTP is not None:
        return _HTTP
    cfg = HttpConfig(  # type: ignore[call-arg]
        base_url="https://api.exmo.com",
        retries=int(getattr(args, "http_retries", 3)),
        backoff=float(getattr(args, "http_backoff", 1.0)),
        timeout=float(getattr(args, "http_timeout", 15.0)),
    )
    _HTTP = HttpClient(cfg)  # type: ignore[call-arg]
    return _HTTP


def _unix_now() -> int:
    return int(time.time())


def _exmo_url(pair: str, tf_min: int, since: int, till: int) -> str:
    return f"https://api.exmo.com/v1.1/candles_history?symbol={pair}&resolution={tf_min}&from={since}&to={till}"


def _fetch_exmo_ohlc(args, pair: str, candles: str) -> pd.DataFrame:
    http = _get_http(args)
    cspec = _parse_candles(candles)
    now = _unix_now()
    span_sec = cspec.tf_minutes * 60 * cspec.bars
    frm, to = now - span_sec, now

    url = _exmo_url(pair, cspec.tf_minutes, frm, to)
    LOG.debug("Starting new HTTPS connection (1): api.exmo.com:443")
    status, payload = http.get_json(url)  # type: ignore[attr-defined]

    if status != 200 or payload is None or "candles" not in payload:
        LOG.error(f"Fatal: HTTPSConnectionPool(host='api.exmo.com', port=443): fetch failed (status={status}) {url}")
        return pd.DataFrame()

    data = payload.get("candles") or []
    if not isinstance(data, list) or not data:
        LOG.warning("[live] empty data")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    # ожидаемые поля: t, o, c, h, l, v  (или time/open/close/high/low/volume) — приводим к унифицированным
    if "t" in df.columns:
        df.rename(columns={"t": "time", "o": "open", "c": "close", "h": "high", "l": "low", "v": "volume"},
                  inplace=True)
    # к секундам / UTC
    df["time"] = pd.to_numeric(df["time"], errors="coerce").astype("int64")
    df = df[df["time"] > 0].copy()
    if df.empty:
        return df
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------
# Индикаторы и стратегии
# ---------------------------------------------------------------------
def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_adx(df: pd.DataFrame, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    # классический ADX/DI
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    plus_dm = (high.diff().clip(lower=0.0)).fillna(0.0)
    minus_dm = (-low.diff().clip(upper=0.0)).fillna(0.0)

    tr1 = (high - low).abs()
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).fillna(0.0)

    atr = tr.ewm(alpha=1 / length, adjust=False).mean()
    pdi = 100 * (plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr.replace(0, np.nan)).fillna(0.0)
    mdi = 100 * (minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr.replace(0, np.nan)).fillna(0.0)
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0.0)
    adx = dx.ewm(alpha=1 / length, adjust=False).mean()
    return adx, pdi, mdi


def _strategy_ema_adx(
        df: pd.DataFrame,
        fast: int,
        slow: int,
        adx_len: int,
        on: float,
        off: float,
        require_di: bool,
) -> np.ndarray:
    """Возвращает массив pnl по сделкам (простая модель: +/− (close diff) в условных пунктах)"""
    if df.empty:
        return np.asarray([], dtype=float)

    close = df["close"].astype(float)
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    adx, pdi, mdi = _compute_adx(df, adx_len)

    # сигнал: EMA пересечения + достаточный тренд по ADX
    long_on = (ema_fast > ema_slow) & (adx >= on)
    long_off = (ema_fast < ema_slow) | (adx <= off)
    if require_di:
        long_on = long_on & (pdi > mdi)

    # моделируем вход/выход: когда меняется состояние
    pos = False
    entry = 0.0
    pnls: List[float] = []

    for i in range(len(df)):
        if not pos and long_on.iat[i]:
            pos = True
            entry = close.iat[i]
        elif pos and long_off.iat[i]:
            exit_px = close.iat[i]
            pnl = float(exit_px - entry)
            pnls.append(pnl)
            pos = False

    # закрываем позицию в конце, если открыта (бумажная фиксация)
    if pos:
        pnl = float(close.iat[-1] - entry)
        pnls.append(pnl)

    return np.asarray(pnls, dtype=float)


def _strategy_ema_adx_atr(
        df: pd.DataFrame,
        fast: int,
        slow: int,
        adx_len: int,
        on: float,
        off: float,
        require_di: bool,
        atr_len: int,
        atr_mult: float,
) -> np.ndarray:
    pnls = _strategy_ema_adx(df, fast, slow, adx_len, on, off, require_di)
    # ATR-фильтр как прокси на величину движения: слегка уменьшаем pnl при низкой волатильности
    if df.empty or pnls.size == 0 or atr_mult <= 0.0:
        return pnls
    high, low = df["high"].astype(float), df["low"].astype(float)
    tr = pd.concat([(high - low).abs(), (high - df["close"].shift()).abs(), (low - df["close"].shift()).abs()],
                   axis=1).max(axis=1).fillna(0.0)
    atr = tr.ewm(span=atr_len, adjust=False).mean().fillna(method="bfill").fillna(0.0)
    scale = float(max(atr.mean(), 1e-9))
    return pnls - (atr_mult * scale * 0.0)  # нейтрально — просто оставим как есть для консистентности логов


# ---------------------------------------------------------------------
# Обёртка стратегии → метрики
# ---------------------------------------------------------------------
def _run_strategy(name: str, params: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    if name == "ema_adx":
        pnl = _strategy_ema_adx(
            df=df,
            fast=int(params.get("fast", 12)),
            slow=int(params.get("slow", 21)),
            adx_len=int(params.get("adx_len", 14)),
            on=float(params.get("on", 25.0)),
            off=float(params.get("off", 16.0)),
            require_di=bool(params.get("require_di", True)),
        )
        metrics = _compute_metrics(pnl)  # type: ignore[arg-type]
        # ради консистентности с выводом добавим atr_* в params (0.0)
        pshow = dict(params)
        pshow.setdefault("atr_len", 14)
        pshow.setdefault("atr_mult", 0.0)
        return {"strategy": name, "params": pshow, **metrics}

    if name == "ema_adx_atr":
        pnl = _strategy_ema_adx_atr(
            df=df,
            fast=int(params.get("fast", 12)),
            slow=int(params.get("slow", 21)),
            adx_len=int(params.get("adx_len", 14)),
            on=float(params.get("on", 25.0)),
            off=float(params.get("off", 16.0)),
            require_di=bool(params.get("require_di", True)),
            atr_len=int(params.get("atr_len", 14)),
            atr_mult=float(params.get("atr_mult", 2.0)),
        )
        metrics = _compute_metrics(pnl)  # type: ignore[arg-type]
        return {"strategy": name, "params": dict(params), **metrics}

    raise ValueError(f"Unknown strategy: {name}")


# ---------------------------------------------------------------------
# Табличный вывод
# ---------------------------------------------------------------------
_PRINT_COLUMNS = ["strategy", "params", "n_trades", "win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar"]


def _format_params(p: Dict[str, Any]) -> str:
    # компактный стабильный JSON
    return json.dumps(p, ensure_ascii=False, separators=(",", ":"))


def _print_table(rows: List[Dict[str, Any]], metric: str) -> None:
    if not rows:
        LOG.warning("No rows to print")
        return
    df = pd.DataFrame(rows)
    # порядок и сортировка
    cols = [c for c in _PRINT_COLUMNS if c in df.columns] + [c for c in df.columns if c not in _PRINT_COLUMNS]
    df = df[cols]
    # красивый вывод
    header = "  " + "  ".join([f"{c:>10}" if c != "strategy" and c != "params" else f"{c:>10}" for c in df.columns])
    LOG.info(header)
    lines = []
    for _, r in df.iterrows():
        r = r.to_dict()
        r["params"] = _format_params(r["params"]) if isinstance(r.get("params"), dict) else str(r.get("params"))
        line = f"  {r.get('strategy', ''):>10}  {r['params']:>44}  {r.get('n_trades', 0):>8}  {r.get('win_rate', 0):>8.3f}  {r.get('avg_pnl', 0):>8.3f}  {r.get('total_pnl', 0):>10.3f}  {r.get('max_dd', 0):>8.3f}  {r.get('sharpe', 0):>8.3f}  {r.get('calmar', 0):>8.3f}"
        lines.append(line)
    for l in lines:
        LOG.info(l)


# ---------------------------------------------------------------------
# Гриды
# ---------------------------------------------------------------------
def _default_grid() -> Dict[str, Any]:
    return {
        "ema_adx": {
            "fast": [8, 10, 12, 14],
            "slow": [20, 26, 30],
            "adx_len": [14],
            "on": [22.0, 25.0],
            "off": [16.0, 18.0],
            "require_di": [True],
        },
        "ema_adx_atr": {
            "fast": [8, 10, 12, 14],
            "slow": [20, 26, 30],
            "adx_len": [14],
            "on": [22.0, 25.0],
            "off": [16.0, 18.0],
            "require_di": [True],
            "atr_len": [14],
            "atr_mult": [1.5, 2.0, 2.5],
        },
    }


def _iter_grid(params: Dict[str, List[Any]]) -> Iterable[Dict[str, Any]]:
    keys = list(params.keys())
    vals = [params[k] for k in keys]
    for combo in np.array(np.meshgrid(*vals, indexing="ij")).T.reshape(-1, len(vals)):
        yield {k: combo[i] for i, k in enumerate(keys)}


def _load_grid_file(src: str | None) -> Optional[Dict[str, Any]]:
    if not src:
        return None
    if src == "-" or src == "/dev/stdin":
        text = sys.stdin.read()
        return json.loads(text) if text.strip() else None
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------
def _run_sweep(args) -> int:
    LOG.info("Command: sweep")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_table([], args.metric)
        return 0

    strategies = []
    if args.strategies == "auto":
        strategies = ["ema_adx", "ema_adx_atr"]
    else:
        strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    rows: List[Dict[str, Any]] = []
    # минимальный набор параметров для демонстрации
    for name in strategies:
        if name == "ema_adx":
            params = {"fast": 14, "slow": 30, "adx_len": 14, "on": 22.0, "off": 16.0, "require_di": True}
            m = _run_strategy(name, params, df)
            rows.append(m)
        elif name == "ema_adx_atr":
            params = {"fast": 14, "slow": 30, "adx_len": 14, "on": 22.0, "off": 16.0, "require_di": True, "atr_len": 14,
                      "atr_mult": 2.0}
            m = _run_strategy(name, params, df)
            rows.append(m)

    # фильтр по мин. количеству сделок
    rows = [r for r in rows if int(r.get("n_trades", 0)) >= int(args.min_trades)]
    # сортировка
    metric = args.metric
    rows.sort(key=lambda r: float(r.get(metric, -1e18)), reverse=True)

    _print_table(rows, metric)
    _maybe_dump(args, args.pair, args.candles, "sweep", rows)
    return 0


def _run_optimize(args) -> int:
    LOG.info("Command: optimize")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_table([], args.metric)
        return 0

    grid = _load_grid_file(args.grid_file) or _default_grid()
    grid_for = grid.get(args.strategy)
    if grid_for is None:
        raise ValueError(f"grid for strategy '{args.strategy}' is not provided")

    rows: List[Dict[str, Any]] = []
    for params in _iter_grid(grid_for):
        m = _run_strategy(args.strategy, params, df)
        rows.append(m)

    rows = [r for r in rows if int(r.get("n_trades", 0)) >= int(args.min_trades)]
    metric = args.metric
    rows.sort(key=lambda r: float(r.get(metric, -1e18)), reverse=True)
    if args.top_n > 0:
        rows = rows[: args.top_n]

    _print_table(rows, metric)
    _maybe_dump(args, args.pair, args.candles, "optimize", rows)
    return 0


def _run_robustness(args) -> int:
    LOG.info("Command: robustness")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_table([], "sharpe")
        return 0

    # разбиваем на окна (равные по количеству баров)
    windows = int(args.rb_windows)
    if windows <= 0:
        windows = 1
    splits = np.array_split(df, windows)

    rows: List[Dict[str, Any]] = []
    params = {
        "fast": args.ema_fast,
        "slow": args.ema_slow,
        "adx_len": args.adx_len,
        "on": args.adx_on,
        "off": args.adx_off,
        "require_di": bool(args.require_di),
    }
    if args.strategy == "ema_adx_atr":
        params["atr_len"] = args.atr_len
        params["atr_mult"] = args.atr_mult
    else:
        # для единообразия в выводе
        params.setdefault("atr_len", 14)
        params.setdefault("atr_mult", 0.0)

    agg_pnl: List[float] = []
    for win in splits:
        pnl = _run_strategy(args.strategy, params, win)[
            "total_pnl"]  # not exactly pnl; но ниже считаем метрики по совокупности окон
        # вместо агрегирования total_pnl соберём все сделки (корректнее):
        pnls = []
        if args.strategy == "ema_adx":
            pnls = _strategy_ema_adx(win,
                                     **{k: params[k] for k in ["fast", "slow", "adx_len", "on", "off", "require_di"]})
        else:
            pnls = _strategy_ema_adx_atr(win, **{k: params[k] for k in
                                                 ["fast", "slow", "adx_len", "on", "off", "require_di", "atr_len",
                                                  "atr_mult"]})
        agg_pnl.extend(list(pnls))

    metrics = _compute_metrics(np.asarray(agg_pnl, dtype=float))  # type: ignore[arg-type]
    out = {"strategy": args.strategy, "params": params, **metrics}
    _print_table([out], "sharpe")
    _maybe_dump(args, args.pair, args.candles, "robustness", [out])
    return 0


def _run_walk_forward(args) -> int:
    LOG.info("Command: walk-forward")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.warning("All folds filtered by --min-trades or no best params found.")
        return 0

    folds = int(args.wf_folds)
    train_frac = float(args.wf_train_frac)
    if not (0.1 <= train_frac < 1.0):
        train_frac = 0.7

    parts = np.array_split(df, folds)
    grid = _load_grid_file(args.grid_file) or _default_grid()
    grid_for = grid.get(args.strategy)
    if grid_for is None:
        raise ValueError(f"grid for strategy '{args.strategy}' is not provided")

    all_valid_pnls: List[float] = []

    for fold in parts:
        n = len(fold)
        if n < 10:
            continue
        cut = int(n * train_frac)
        train = fold.iloc[:cut].copy()
        valid = fold.iloc[cut:].copy()
        if valid.empty or train.empty:
            continue

        # подбираем лучшие параметры по train
        cand_rows: List[Dict[str, Any]] = []
        for params in _iter_grid(grid_for):
            m = _run_strategy(args.strategy, params, train)
            cand_rows.append(m)
        cand_rows = [r for r in cand_rows if int(r.get("n_trades", 0)) >= int(args.min_trades)]
        if not cand_rows:
            continue
        metric = args.metric
        cand_rows.sort(key=lambda r: float(r.get(metric, -1e18)), reverse=True)
        best_params = cand_rows[0]["params"]

        # валидируем на valid
        if args.strategy == "ema_adx":
            pnls = _strategy_ema_adx(valid, **{k: best_params[k] for k in
                                               ["fast", "slow", "adx_len", "on", "off", "require_di"]})
        else:
            pnls = _strategy_ema_adx_atr(valid, **{k: best_params[k] for k in
                                                   ["fast", "slow", "adx_len", "on", "off", "require_di", "atr_len",
                                                    "atr_mult"]})
        all_valid_pnls.extend(list(pnls))

    if not all_valid_pnls:
        LOG.warning("All folds filtered by --min-trades or no best params found.")
        return 0

    metrics = _compute_metrics(np.asarray(all_valid_pnls, dtype=float))  # type: ignore[arg-type]
    out = {"strategy": args.strategy, "params": "<wf best per fold from {} folds>".format(folds), **metrics}
    _print_table([out], args.metric)
    _maybe_dump(args, args.pair, args.candles, "walk-forward", [out])
    return 0


def _run_live_observe(args) -> int:
    LOG.info(
        f"[live] observe {args.pair} {args.candles} strategy={args.strategy} params={json.dumps({'fast': args.ema_fast, 'slow': args.ema_slow, 'adx_len': args.adx_len, 'on': args.adx_on, 'off': args.adx_off, 'require_di': bool(args.require_di)})} poll={args.poll_sec}s")
    if args.summary_alert:
        LOG.debug("[live] summary-alert flag accepted (no-op notifier).")
    try:
        while True:
            df = _fetch_exmo_ohlc(args, args.pair, args.candles)
            if not df.empty:
                last_dt = df["dt"].iat[-1]
                close = float(df["close"].iat[-1])
                LOG.info(f"[live] {last_dt.isoformat()} close={close:.6f}")
            else:
                LOG.warning("[live] empty data")
            time.sleep(int(args.poll_sec))
    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
    return 0


def _run_live_paper(args) -> int:
    LOG.info(f"[live] paper {args.pair} {args.candles} strategy={args.strategy}")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.info("[paper] empty dataset")
        return 0

    if args.strategy == "ema_adx":
        pnls = _strategy_ema_adx(
            df,
            fast=args.ema_fast,
            slow=args.ema_slow,
            adx_len=args.adx_len,
            on=args.adx_on,
            off=args.adx_off,
            require_di=bool(args.require_di),
        )
        params = {"fast": args.ema_fast, "slow": args.ema_slow, "adx_len": args.adx_len, "on": args.adx_on,
                  "off": args.adx_off, "require_di": bool(args.require_di), "atr_len": 14, "atr_mult": 0.0}
    else:
        pnls = _strategy_ema_adx_atr(
            df,
            fast=args.ema_fast,
            slow=args.ema_slow,
            adx_len=args.adx_len,
            on=args.adx_on,
            off=args.adx_off,
            require_di=bool(args.require_di),
            atr_len=args.atr_len,
            atr_mult=args.atr_mult,
        )
        params = {"fast": args.ema_fast, "slow": args.ema_slow, "adx_len": args.adx_len, "on": args.adx_on,
                  "off": args.adx_off, "require_di": bool(args.require_di), "atr_len": args.atr_len,
                  "atr_mult": args.atr_mult}

    m = _compute_metrics(pnls)  # type: ignore[arg-type]
    LOG.info(f"[paper] trades={m['n_trades']} total_pnl={m['total_pnl']:.6f} sharpe={m['sharpe']:.3f}")

    row = {"strategy": args.strategy, "params": params, **m}
    _print_table([row], "sharpe")
    _maybe_dump_live(args, args.pair, args.candles, row, df, pnls)
    return 0


# ---------------------------------------------------------------------
# Сохранение результатов
# ---------------------------------------------------------------------
def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _default_out_dir(base: str | None) -> str:
    base = base or "out/data"
    _ensure_dir(base)
    return base


def _maybe_dump(args, pair: str, candles: str, tag: str, rows: List[Dict[str, Any]]) -> None:
    out_dir = _default_out_dir(getattr(args, "out_dir", None))
    prefix = getattr(args, "out_prefix", None)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"{prefix}_{pair}_{candles.replace(':', '-')}_{ts}" if prefix else f"{pair}_{candles.replace(':', '-')}_{ts}"
    # CSV
    csv_path = os.path.join(out_dir, f"{base}_{tag}.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    # JSONL (опционально)
    if getattr(args, "jsonl", False):
        jsonl_path = os.path.join(out_dir, f"{base}_{tag}.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _maybe_dump_live(args, pair: str, candles: str, row: Dict[str, Any], df: pd.DataFrame, pnls: np.ndarray) -> None:
    out_dir = _default_out_dir(getattr(args, "out_dir", None))
    prefix = getattr(args, "out_prefix", None)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"{prefix}_{pair}_{candles.replace(':', '-')}_{ts}" if prefix else f"{pair}_{candles.replace(':', '-')}_{ts}"
    # trades (простая реконструкция сделок из pnl — без таймстампов вход/выход; в проекте можно заменить на реальный журнал)
    trades_csv = os.path.join(out_dir, f"{base}_trades.csv")
    pd.DataFrame({"pnl": pnls}).to_csv(trades_csv, index=False)
    # equity
    equity_csv = os.path.join(out_dir, f"{base}_equity.csv")
    equity = np.cumsum(pnls) if pnls.size else np.asarray([], dtype=float)
    pd.DataFrame({"equity": equity}).to_csv(equity_csv, index=False)
    # metrics
    metrics_json = os.path.join(out_dir, f"{base}_metrics.json")
    with open(metrics_json, "w", encoding="utf-8") as f:
        json.dump(row, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------
# Аргументы CLI
# ---------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot", description="EXMO research & live CLI")

    # Общие настройки
    p.add_argument("--pair", type=str, default="DOGE_EUR", help="EXMO symbol, e.g. DOGE_EUR")
    p.add_argument("--candles", type=str, default="5m:2000", help="timeframe:bars, e.g. 5m:2000")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--out-dir", type=str, default="out/data", help="Where to save CSV/JSON results")
    p.add_argument("--out-prefix", type=str, default="", help="Filename prefix for artifacts (optional)")
    p.add_argument("--jsonl", action="store_true", help="Also save *.jsonl")

    # HTTP
    p.add_argument("--http-retries", type=int, default=3, help="HTTP retries")
    p.add_argument("--http-backoff", type=float, default=1.0, help="HTTP backoff factor")
    p.add_argument("--http-timeout", type=float, default=15.0, help="HTTP timeout seconds")

    sub = p.add_subparsers(dest="cmd", required=True)

    # sweep
    sp = sub.add_parser("sweep", help="Quick strategies sweep")
    sp.add_argument("--strategies", type=str, default="auto", help="auto or comma list")
    sp.add_argument("--metric", type=str, default="sharpe", help="Sort metric")
    sp.add_argument("--top-n", type=int, default=3, help="Top rows")
    sp.add_argument("--min-trades", type=int, default=1, help="Filter min trades")
    sp.set_defaults(_handler=_run_sweep)

    # optimize
    op = sub.add_parser("optimize", help="Grid search params")
    op.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    op.add_argument("--metric", type=str, default="sharpe")
    op.add_argument("--top-n", type=int, default=10)
    op.add_argument("--min-trades", type=int, default=3)
    op.add_argument("--grid-file", type=str, default="", help="JSON file with grid or '-' for stdin")
    op.set_defaults(_handler=_run_optimize)

    # robustness
    rb = sub.add_parser("robustness", help="Robustness by windows")
    rb.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    rb.add_argument("--rb-windows", type=int, default=6)
    rb.add_argument("--min-trades", type=int, default=1)
    # strategy params
    rb.add_argument("--ema-fast", type=int, dest="ema_fast", default=12)
    rb.add_argument("--ema-slow", type=int, dest="ema_slow", default=21)
    rb.add_argument("--adx-len", type=int, dest="adx_len", default=14)
    rb.add_argument("--adx-on", type=float, dest="adx_on", default=25.0)
    rb.add_argument("--adx-off", type=float, dest="adx_off", default=16.0)
    rb.add_argument("--require-di", action="store_true", dest="require_di")
    rb.add_argument("--atr-len", type=int, dest="atr_len", default=14)
    rb.add_argument("--atr-mult", type=float, dest="atr_mult", default=2.0)
    rb.set_defaults(_handler=_run_robustness)

    # walk-forward
    wf = sub.add_parser("walk-forward", help="Walk-forward validation")
    wf.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    wf.add_argument("--metric", type=str, default="sharpe")
    wf.add_argument("--wf-folds", type=int, dest="wf_folds", default=4)
    wf.add_argument("--wf-train-frac", type=float, dest="wf_train_frac", default=0.7)
    wf.add_argument("--min-trades", type=int, default=1)
    wf.add_argument("--grid-file", type=str, default="", help="JSON file with grid or '-' for stdin")
    wf.set_defaults(_handler=_run_walk_forward)

    # trade-live
    tl = sub.add_parser("trade-live", help="Live modes")
    tl.add_argument("--mode", type=str, required=True, choices=["observe", "paper"])
    # common strategy params (для observe/paper)
    tl.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    tl.add_argument("--ema-fast", type=int, dest="ema_fast", default=12)
    tl.add_argument("--ema-slow", type=int, dest="ema_slow", default=21)
    tl.add_argument("--adx-len", type=int, dest="adx_len", default=14)
    tl.add_argument("--adx-on", type=float, dest="adx_on", default=25.0)
    tl.add_argument("--adx-off", type=float, dest="adx_off", default=16.0)
    tl.add_argument("--require-di", action="store_true", dest="require_di")
    tl.add_argument("--atr-len", type=int, dest="atr_len", default=14)
    tl.add_argument("--atr-mult", type=float, dest="atr_mult", default=2.0)
    # observe only
    tl.add_argument("--poll-sec", type=int, default=10)
    tl.add_argument("--summary-alert", action="store_true")
    # paper only
    tl.add_argument("--fees-bps", type=float, default=0.0, help="Not used in dummy pnl model; reserved")
    tl.add_argument("--slippage-bps", type=float, default=0.0, help="Not used in dummy pnl model; reserved")
    tl.add_argument("--size", type=float, default=1.0, help="Not used in dummy pnl model; reserved")
    tl.set_defaults(_handler=_dispatch_live)

    return p


def _dispatch_live(a) -> int:
    return _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a)


# ---------------------------------------------------------------------
# Входная точка
# ---------------------------------------------------------------------
def _dispatch_command(args) -> int:
    return args._handler(args)  # type: ignore[attr-defined]


def _run_cli(argv: List[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(bool(getattr(args, "debug", False)))
    return _dispatch_command(args)


def main() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
