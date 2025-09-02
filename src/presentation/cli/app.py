# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

LOG = logging.getLogger("cli")

# =============================================================================
# HTTP совместимость: используем ваш HttpClient, если он есть, иначе requests
# =============================================================================

_ExternalHttpClient = None
try:
    from src.infrastructure.http.http_utils import HttpClient as _ExternalHttpClient  # type: ignore
except Exception:
    _ExternalHttpClient = None


class CompatHttpClient:
    """
    Адаптер с методом get_json(url_or_path, params) -> (status:int, payload:any).
    Поддерживает ретраи/бэкофф/таймаут.
    """

    def __init__(
            self,
            base_url: str = "",
            timeout: float = 15.0,
            retries: int = 0,
            backoff: float = 0.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))

        self._client = None
        if _ExternalHttpClient is not None:
            # пытаемся инициализировать ваш HttpClient
            try:
                self._client = _ExternalHttpClient(base_url=self.base_url, timeout=self.timeout)  # type: ignore
            except Exception:
                try:
                    self._client = _ExternalHttpClient()  # type: ignore
                except Exception:
                    self._client = None

    def _full_url(self, url_or_path: str) -> str:
        if url_or_path.startswith(("http://", "https://")):
            return url_or_path
        return f"{self.base_url}/{url_or_path.lstrip('/')}" if self.base_url else url_or_path

    def get_json(self, url_or_path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        url = self._full_url(url_or_path)
        last_error: Optional[str] = None

        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                if self._client is not None and hasattr(self._client, "get"):
                    resp = self._client.get(url, params=params)  # type: ignore[attr-defined]
                    status = getattr(resp, "status_code", 0) or 0
                    try:
                        body = resp.json()
                    except Exception:
                        body = getattr(resp, "text", "")
                    return int(status), body

                import requests  # lazy import

                resp = requests.get(url, params=params, timeout=self.timeout)
                status = int(resp.status_code)
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text
                return status, body

            except Exception as ex:
                last_error = f"{type(ex).__name__}: {ex}"
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** attempt))
                else:
                    break
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                LOG.debug("[http] GET %s in %.1fms (try %d/%d)", url, dt_ms, attempt + 1, self.retries + 1)

        return 0, {"error": last_error or "HTTP error"}


# =============================================================================
# Метрики: используем проектные, если есть; иначе лёгкий фоллбек
# =============================================================================

def _compute_metrics(pnl: np.ndarray) -> Dict[str, float]:
    try:
        from src.backtest import metrics as metrics_mod  # type: ignore

        if hasattr(metrics_mod, "compute_metrics"):
            m = metrics_mod.compute_metrics(pnl=pnl)  # type: ignore[attr-defined, call-arg]
            for k in ["n_trades", "win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar"]:
                m.setdefault(k, float("nan"))
            return m
    except Exception as e:
        LOG.debug("metrics fallback: %s", e)

    pnl = np.asarray(pnl, dtype=float)
    total_pnl = float(np.nansum(pnl)) if pnl.size else 0.0
    avg = float(np.nanmean(pnl)) if pnl.size else 0.0
    std = float(np.nanstd(pnl)) if pnl.size else 0.0
    sharpe = (avg / std) * math.sqrt(252) if std > 0 else 0.0

    eq = np.nancumsum(pnl) if pnl.size else np.array([], dtype=float)
    if eq.size:
        roll_max = np.maximum.accumulate(eq)
        dd = roll_max - eq
        max_dd = float(np.nanmax(dd))
        calmar = (total_pnl / max_dd) if max_dd > 0 else float("inf")
    else:
        max_dd, calmar = 0.0, 0.0

    wins = float(np.sum(pnl > 0))
    losses = float(np.sum(pnl < 0))
    n_trades = int(wins + losses)
    win_rate = (wins / n_trades) if n_trades else 0.0

    return {
        "n_trades": float(n_trades),
        "win_rate": float(win_rate),
        "avg_pnl": float(avg),
        "total_pnl": float(total_pnl),
        "max_dd": float(max_dd),
        "sharpe": float(sharpe),
        "calmar": float(calmar),
    }


# =============================================================================
# Реестр стратегий (ожидается в проекте)
# =============================================================================

BuildTrades = Tuple[List[Dict[str, Any]], np.ndarray]


def _registry_get_builder() -> Dict[str, Any]:
    try:
        from src.backtest.registry import get_registry_builder  # type: ignore
        return get_registry_builder()
    except Exception as e:
        raise RuntimeError(
            "Strategy registry not found. Expected src/backtest/registry.py with get_registry_builder()."
        ) from e


def _registry_get_param_grid() -> Dict[str, List[Dict[str, Any]]]:
    try:
        from src.backtest.registry import get_default_grid  # type: ignore
        grid = get_default_grid()
        grid.setdefault(
            "ema_adx",
            [{"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True}],
        )
        grid.setdefault(
            "ema_adx_atr",
            [{"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True, "atr_len": 14}],
        )
        return grid
    except Exception:
        return {
            "ema_adx": [{"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True}],
            "ema_adx_atr": [
                {"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True, "atr_len": 14}
            ],
        }


# =============================================================================
# Очистка OHLC
# =============================================================================

def _clean_ohlc(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    warns: List[str] = []
    try:
        from src.infrastructure.ohlc.sanity import clean_ohlc  # type: ignore

        out, warns = clean_ohlc(df)
        return out, list(warns or [])
    except Exception as e:
        LOG.debug("clean_ohlc fallback: %s", e)
        if df.empty:
            return df, warns
        out = df.sort_values("dt").drop_duplicates(subset=["dt"]).copy()
        if {"open", "high", "low", "close"}.issubset(out.columns):
            hi = out[["open", "close"]].max(axis=1)
            lo = out[["open", "close"]].min(axis=1)
            out["high"] = np.maximum(out["high"], hi)
            out["low"] = np.minimum(out["low"], lo)
        return out, warns


# =============================================================================
# Загрузка свечей EXMO
# =============================================================================

_PERIODS = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def _parse_candles_flag(flag: str) -> Tuple[str, int]:
    if ":" not in flag:
        raise ValueError("candles must be like '5m:2500'")
    tf, n_str = flag.split(":", 1)
    tf = tf.strip()
    n = int(n_str)
    if tf not in _PERIODS:
        raise ValueError(f"Unsupported timeframe '{tf}'. Use one of: {', '.join(sorted(_PERIODS))}")
    return tf, n


def _exmo_url() -> str:
    return "https://api.exmo.com/v1.1"


def _make_http(args: argparse.Namespace) -> CompatHttpClient:
    return CompatHttpClient(
        base_url=_exmo_url(),
        timeout=float(getattr(args, "http_timeout", 15.0) or 15.0),
        retries=int(getattr(args, "http_retries", 0) or 0),
        backoff=float(getattr(args, "http_backoff", 0.0) or 0.0),
    )


def _fetch_exmo_ohlc(args: argparse.Namespace, pair: str, candles_flag: str) -> pd.DataFrame:
    """
    Получаем свечи через /candles_history?symbol=PAIR&resolution=TF&from=...&to=...
    Возвращаем нормализованный DataFrame или пустой, если что-то пошло не так.
    """
    try:
        tf, n = _parse_candles_flag(candles_flag)
    except Exception as e:
        LOG.error("bad --candles: %s", e)
        return pd.DataFrame()

    period = _PERIODS[tf]
    t_to = int(time.time())
    t_from = max(0, t_to - n * period)

    params = {"symbol": pair, "resolution": tf, "from": t_from, "to": t_to}
    http = _make_http(args)
    status, payload = http.get_json("candles_history", params=params)

    if status != 200:
        LOG.warning("[http] non-200 or no candles: status=%s", status)
        return pd.DataFrame()

    try:
        candles = None
        if isinstance(payload, dict):
            if "candles" in payload:
                candles = payload["candles"]
            elif isinstance(payload.get("result"), dict) and "candles" in payload["result"]:
                candles = payload["result"]["candles"]
        if candles is None:
            LOG.warning("[http] unexpected payload keys: %s",
                        list(payload) if isinstance(payload, dict) else type(payload))
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        if df.empty:
            return df

        # Нормализация столбцов
        rename_map = {"t": "timestamp", "time": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close",
                      "v": "volume"}
        df = df.rename(columns=rename_map)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        ts_col = "timestamp" if "timestamp" in df.columns else None
        if ts_col is None:
            for c in ("ts", "date"):
                if c in df.columns:
                    ts_col = c
                    break
        if ts_col is None:
            LOG.warning("[http] no timestamp column in payload")
            return pd.DataFrame()

        ts = pd.to_numeric(df[ts_col], errors="coerce").astype("Int64")
        ts_np = ts.to_numpy(dtype="float64")
        if np.nanmean(ts_np) > 10_000_000_000:  # вероятно миллисекунды
            ts_np = ts_np / 1000.0
        df["timestamp"] = ts_np.astype("int64", copy=False)

        df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.sort_values("dt").reset_index(drop=True)

        # sanity
        df, warns = _clean_ohlc(df)
        for w in warns:
            LOG.warning("[ohlc] %s", w)

        keep = ["dt", "timestamp", "open", "high", "low", "close", "volume"]
        return df[[c for c in keep if c in df.columns]].copy()

    except Exception as e:
        LOG.warning("[http] parse error: %s", e)
        return pd.DataFrame()


# =============================================================================
# Связка со стратегиями из реестра
# =============================================================================

def _build_trades_from_registry(strategy: str, df: pd.DataFrame, params: Dict[str, Any]) -> BuildTrades:
    builders = _registry_get_builder()
    if strategy not in builders:
        raise ValueError(f"Unknown strategy '{strategy}'. Available: {', '.join(sorted(builders))}")
    fn = builders[strategy]
    trades, pnl = fn(df=df, params=params)  # type: ignore[misc]
    return trades, np.asarray(pnl, dtype=float)


# =============================================================================
# Вспомогательные утилиты отбора/вывода
# =============================================================================

def _rows_to_selected(rows: List[Dict[str, Any]], metric: str, top_n: int, min_trades: int) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "n_trades" in df.columns:
        df = df[df["n_trades"] >= float(min_trades)]
    if metric not in df.columns:
        LOG.warning("metric '%s' not found; available: %s", metric,
                    [c for c in df.columns if c not in ("strategy", "params")])
        metric = "sharpe" if "sharpe" in df.columns else df.columns[-1]
    ascending = metric in {"max_dd"}  # для max_dd — меньше лучше
    df = df.sort_values(metric, ascending=ascending).reset_index(drop=True)
    return df.head(top_n)


def _print_selected(df: pd.DataFrame) -> None:
    if df.empty:
        print("(no rows)")
        return
    cols = ["strategy", "params", "n_trades", "win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar"]
    cols = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
    print(df[cols].to_string(index=False))


# =============================================================================
# Сохранение артефактов
# =============================================================================

def _out_dir(args: argparse.Namespace) -> str:
    base = args.out_dir or os.path.join("out", "data")
    os.makedirs(base, exist_ok=True)
    return base


def _ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _fname(args: argparse.Namespace, pair: str, candles: str, suffix: str, ext: str) -> str:
    prefix = (args.out_prefix + "_") if args.out_prefix else ""
    safe_pair = pair.replace("/", "_")
    safe_candles = candles.replace(":", "_")
    return f"{prefix}{safe_pair}_{safe_candles}_{suffix}_{_ts_now()}.{ext}"


def _dump_tabular(args: argparse.Namespace, pair: str, candles: str, suffix: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    path = os.path.join(_out_dir(args), _fname(args, pair, candles, suffix, "csv"))
    df.to_csv(path, index=False)
    LOG.info("[out] saved %s rows=%d", path, len(df))


def _dump_json(args: argparse.Namespace, pair: str, candles: str, suffix: str, obj: Any) -> None:
    path = os.path.join(_out_dir(args), _fname(args, pair, candles, suffix, "json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    LOG.info("[out] saved %s", path)


# =============================================================================
# Команды: sweep / optimize / robustness / walk-forward
# =============================================================================

def _default_params(strategy: str) -> Dict[str, Any]:
    if strategy == "ema_adx":
        return {"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True}
    if strategy == "ema_adx_atr":
        p = _default_params("ema_adx")
        p.update({"atr_len": 14, "atr_mult": 2.0})
        return p
    return {}


def _run_sweep(args) -> int:
    LOG.info("Command: sweep")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_selected(pd.DataFrame())
        return 0

    strategies = ["ema_adx", "ema_adx_atr"] if args.strategies == "auto" else [
        s.strip() for s in args.strategies.split(",") if s.strip()
    ]

    rows: List[Dict[str, Any]] = []
    for name in strategies:
        params = _default_params(name)
        trades, pnls = _build_trades_from_registry(name, df, params)
        met = _compute_metrics(pnls)
        rows.append({"strategy": name, "params": params, **met})

    selected = _rows_to_selected(rows, args.metric, args.top_n, args.min_trades)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "sweep", selected)
    return 0


def _grid_iter(grid: Dict[str, Iterable[Any]]) -> Iterable[Dict[str, Any]]:
    keys = list(grid.keys())
    if not keys:
        yield {}
        return

    def rec(i: int, cur: Dict[str, Any]):
        if i == len(keys):
            yield dict(cur)
            return
        k = keys[i]
        vs = list(grid[k])
        if not vs:
            yield from rec(i + 1, cur)
            return
        for v in vs:
            cur[k] = v
            yield from rec(i + 1, cur)

    yield from rec(0, {})


def _parse_grid_file(path: Optional[str]) -> Optional[Dict[str, Iterable[Any]]]:
    if not path:
        return None
    data = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8").read()
    grid = json.loads(data)
    if not isinstance(grid, dict):
        raise ValueError("grid-file must be a JSON object {param: [values...]}")
    return {k: v for k, v in grid.items()}


def _run_optimize(args) -> int:
    LOG.info("Command: optimize strategy=%s", args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_selected(pd.DataFrame())
        return 0

    grid = _parse_grid_file(args.grid_file)
    if grid is None:
        if args.strategy == "ema_adx":
            grid = {
                "fast": [10, 12, 14],
                "slow": [21, 26, 30],
                "adx_len": [14, 16],
                "on": [22, 25, 28],
                "off": [16, 18, 20],
                "require_di": [True],
            }
        else:
            grid = {
                "fast": [10, 12, 14],
                "slow": [21, 26, 30],
                "adx_len": [14, 16],
                "on": [22, 25, 28],
                "off": [16, 18, 20],
                "require_di": [True],
                "atr_len": [14, 20],
                "atr_mult": [1.5, 2.0, 2.5],
            }

    rows: List[Dict[str, Any]] = []
    for p in _grid_iter(grid):
        params = _default_params(args.strategy)
        params.update(p)
        _, pnls = _build_trades_from_registry(args.strategy, df, params)
        met = _compute_metrics(pnls)
        rows.append({"strategy": args.strategy, "params": params, **met})

    selected = _rows_to_selected(rows, args.metric, args.top_n, args.min_trades)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "optimize", selected)

    if args.jsonl:
        out_path = os.path.join(_out_dir(args), _fname(args, args.pair, args.candles, "optimize_full", "jsonl"))
        with open(out_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        LOG.info("[out] saved %s (%d rows)", out_path, len(rows))
    return 0


def _run_robustness(args) -> int:
    import random, numpy as np
    if getattr(args, "seed", None) is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)

    LOG.info("Command: robustness strategy=%s", args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0

    n = len(df)
    k = max(1, int(args.rb_windows))
    win = max(10, n // k)

    base_params = _default_params(args.strategy)
    rows: List[Dict[str, Any]] = []

    for i in range(k):
        lo = i * win
        hi = min(n, (i + 1) * win)
        part = df.iloc[lo:hi].copy()
        if part.empty:
            continue
        _, pnls = _build_trades_from_registry(args.strategy, part, base_params)
        met = _compute_metrics(pnls)
        rows.append({"strategy": args.strategy, "params": base_params, "window": f"{i + 1}/{k}", **met})

    selected = _rows_to_selected(rows, args.metric, top_n=len(rows), min_trades=args.min_trades)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "robustness", selected)
    return 0


def _run_walk_forward(args) -> int:
    import random, numpy as np
    if getattr(args, "seed", None) is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)

    LOG.info("Command: walk-forward strategy=%s", args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0

    folds = max(2, int(args.wf_folds))
    train_frac = min(0.95, max(0.5, float(args.wf_train_frac)))
    n = len(df)
    fold_len = max(1, n // folds)

    rows: List[Dict[str, Any]] = []
    for i in range(folds):
        lo = i * fold_len
        hi = min(n, (i + 1) * fold_len)
        part = df.iloc[lo:hi].copy()
        if part.empty:
            continue
        split = int(len(part) * train_frac)
        train = part.iloc[:split]
        valid = part.iloc[split:]
        if train.empty or valid.empty:
            continue

        # простая локальная оптимизация на train
        best_params = _default_params(args.strategy)
        best_score = -1e18
        for tweak in _grid_iter({"on": [22, 25, 28], "off": [16, 18, 20]}):
            p = dict(best_params)
            p.update(tweak)
            _, pnls = _build_trades_from_registry(args.strategy, train, p)
            met = _compute_metrics(pnls)
            score = float(met.get(args.metric, float("nan")))
            if math.isnan(score):
                continue
            better = (score > best_score) if args.metric != "max_dd" else (score < best_score or best_score == -1e18)
            if better:
                best_score = score
                best_params = p

        # валидация
        _, pnls_val = _build_trades_from_registry(args.strategy, valid, best_params)
        met_val = _compute_metrics(pnls_val)
        rows.append({"fold": f"{i + 1}/{folds}", "strategy": args.strategy, "params": best_params, **met_val})

    df_res = _rows_to_selected(rows, args.metric, top_n=len(rows), min_trades=args.min_trades)
    print("<wf best per fold from %d folds>" % folds)
    _print_selected(df_res)
    _dump_tabular(args, args.pair, args.candles, "walk_forward", df_res)
    return 0


# =============================================================================
# trade-live: paper / observe
# =============================================================================

def _trade_summary(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"closed": 0, "win_rate": 0.0, "pf": 0.0, "avg_pnl": 0.0}
    pnls = np.array([t.get("pnl", 0.0) for t in trades], dtype=float)
    closed = int(len(pnls))
    wins = float(np.sum(pnls > 0))
    losses = float(np.sum(pnls < 0))
    win_rate = (wins / closed) if closed else 0.0
    pf = (pnls[pnls > 0].sum() / -pnls[pnls < 0].sum()) if np.any(pnls < 0) else float("inf")
    avg_pnl = float(np.mean(pnls)) if closed else 0.0
    return {"closed": closed, "win_rate": win_rate, "pf": pf, "avg_pnl": avg_pnl}


def _calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False).mean()


def _calc_adx(df: pd.DataFrame, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Небольшая реализация ADX (+DI/-DI), чтобы выводить таблицу в observe без внешних зависимостей.
    Возвращает (adx, +di, -di) как pd.Series такой же длины как df.
    """
    n = max(2, int(length))
    if len(df) < n + 2 or not {"high", "low", "close"}.issubset(df.columns):
        nan = pd.Series([np.nan] * len(df), index=df.index)
        return nan.copy(), nan.copy(), nan.copy()

    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)

    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    def wilder_smooth(x: np.ndarray, n: int) -> np.ndarray:
        if len(x) == 0:
            return np.array([], dtype=float)
        out = np.empty_like(x, dtype=float)
        out[:] = np.nan
        if len(x) <= n:
            return out
        s = np.nansum(x[:n])
        out[n] = s
        for i in range(n + 1, len(x)):
            s = s - (s / n) + x[i]
            out[i] = s
        return out

    tr_n = wilder_smooth(tr, n)
    plus_dm_n = wilder_smooth(plus_dm, n)
    minus_dm_n = wilder_smooth(minus_dm, n)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * (plus_dm_n / tr_n)
        minus_di = 100.0 * (minus_dm_n / tr_n)
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

    adx = np.empty(len(df))
    adx[:] = np.nan
    if len(dx) > n:
        adx[1 + n:] = pd.Series(dx[n:]).rolling(window=n, min_periods=1).mean().values

    pad_len = len(df) - (len(plus_di) + 1)
    pad = np.array([np.nan] * max(0, pad_len))
    pdi = np.concatenate(([np.nan], plus_di, pad))
    mdi = np.concatenate(([np.nan], minus_di, pad))

    return pd.Series(adx, index=df.index), pd.Series(pdi, index=df.index), pd.Series(mdi, index=df.index)


def _observe_snapshot(df: pd.DataFrame, args: argparse.Namespace) -> None:
    cols = ["dt", "close"]
    if "ema_fast" in df.columns:
        cols += ["ema_fast", "ema_slow"]
    if {"adx", "pdi", "mdi"}.issubset(df.columns):
        cols += ["adx", "pdi", "mdi"]
    tail = df.tail(args.observe_rows)
    LOG.info("\n%s", tail[cols].to_string(index=False))


def _run_live_paper(args) -> int:
    LOG.info("[live] paper %s %s strategy=%s", args.pair, args.candles, args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.warning("[paper] no candles")
        return 0

    base_params = _default_params(args.strategy)
    trades, pnls = _build_trades_from_registry(args.strategy, df, base_params)
    met = _compute_metrics(pnls)
    LOG.info(
        "[paper] trades=%d total_pnl=%.6f sharpe=%.3f",
        int(met.get("n_trades", 0)),
        float(met.get("total_pnl", 0.0)),
        float(met.get("sharpe", 0.0)),
    )
    if args.print_trade_summary:
        summ = _trade_summary(trades)
        LOG.info(
            "[paper] summary: closed=%d win_rate=%.2f%% pf=%.3f avg_pnl=%.6f",
            summ["closed"],
            summ["win_rate"] * 100.0,
            summ["pf"],
            summ["avg_pnl"],
        )

    _dump_json(args, args.pair, args.candles, "metrics", met)
    _dump_json(args, args.pair, args.candles, "trades", trades)
    eq = pd.DataFrame({"step": np.arange(len(pnls)), "pnl": pnls, "equity": np.cumsum(pnls)})
    path_eq = os.path.join(_out_dir(args), _fname(args, args.pair, args.candles, "equity", "csv"))
    eq.to_csv(path_eq, index=False)
    LOG.info("[out] saved %s", path_eq)
    return 0


def _run_live_observe(args) -> int:
    LOG.info("[live] observe %s %s strategy=%s", args.pair, args.candles, args.strategy)
    LOG.info(
        "[observe] poll every %ds; summary_alert=%s; print=%s; max_mins=%d max_iter=%d",
        int(args.poll_sec),
        bool(args.summary_alert),
        args.observe_print,
        int(args.max_mins),
        int(args.max_iter),
    )

    started = time.time()
    printed_last_bar_ts: Optional[int] = None
    it = 0

    while True:
        it += 1
        df = _fetch_exmo_ohlc(args, args.pair, args.candles)
        if df.empty:
            LOG.warning("[observe] no data")
        else:
            if {"close", "high", "low"}.issubset(df.columns):
                df["ema_fast"] = _calc_ema(df["close"], args.ema_fast)
                df["ema_slow"] = _calc_ema(df["close"], args.ema_slow)
                adx, pdi, mdi = _calc_adx(df, args.adx_len)
                df["adx"], df["pdi"], df["mdi"] = adx, pdi, mdi

            cur_ts = int(df["timestamp"].iloc[-1]) if "timestamp" in df.columns and not df.empty else None
            should_print = args.observe_print == "always" or (
                    args.observe_print == "on-new-bar" and (cur_ts is not None and cur_ts != printed_last_bar_ts)
            )
            if should_print:
                _observe_snapshot(df, args)
                printed_last_bar_ts = cur_ts

        if args.summary_alert and not df.empty:
            LOG.debug("[observe] last close=%.6f", float(df["close"].iloc[-1]))

        if args.max_iter and it >= args.max_iter:
            break
        if args.max_mins and (time.time() - started) >= args.max_mins * 60:
            break
        time.sleep(float(args.poll_sec))

    LOG.info("[observe] stopped by user or limit")
    return 0


# =============================================================================
# Парсер/диспетчер CLI
# =============================================================================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot")

    # Глобальные флаги
    p.add_argument("--pair", required=True, help="Trading pair like DOGE_EUR")
    p.add_argument("--candles", required=True, help="Format TF:COUNT e.g. 5m:2500")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--out-dir", default=os.path.join("out", "data"))
    p.add_argument("--out-prefix", default="", help="Prefix for artifact file names")
    p.add_argument("--jsonl", action="store_true", help="Dump full optimization results to JSONL")
    p.add_argument("--print-trade-summary", action="store_true", help="Print closed trades summary for paper mode")

    # HTTP флаги
    p.add_argument("--http-retries", type=int, default=3)
    p.add_argument("--http-backoff", type=float, default=1.0)
    p.add_argument("--http-timeout", type=float, default=15.0)

    sub = p.add_subparsers(dest="cmd", required=True)

    # sweep
    sw = sub.add_parser("sweep")
    sw.add_argument("--strategies", default="auto", help="Comma separated or 'auto'")
    sw.add_argument("--metric", default="sharpe")
    sw.add_argument("--top-n", type=int, default=5)
    sw.add_argument("--min-trades", type=int, default=1)
    sw.set_defaults(_handler=_run_sweep)

    # optimize
    opt = sub.add_parser("optimize")
    opt.add_argument("--strategy", required=True, choices=["ema_adx", "ema_adx_atr"])
    opt.add_argument("--grid-file", default=None, help="Path to JSON grid or '-' to read from stdin")
    opt.add_argument("--metric", default="sharpe")
    opt.add_argument("--top-n", type=int, default=10)
    opt.add_argument("--min-trades", type=int, default=1)
    opt.set_defaults(_handler=_run_optimize)

    # robustness
    rb = sub.add_parser("robustness")
    rb.add_argument("--strategy", required=True, choices=["ema_adx", "ema_adx_atr"])
    rb.add_argument("--rb-windows", type=int, default=8)
    rb.add_argument("--min-trades", type=int, default=1)
    rb.add_argument("--metric", default="sharpe")
    rb.add_argument("--seed", type=int, default=0, help="Random seed for robustness (0 = deterministic default)")
    rb.set_defaults(_handler=_run_robustness)

    # walk-forward
    wf = sub.add_parser("walk-forward")
    wf.add_argument("--strategy", required=True, choices=["ema_adx", "ema_adx_atr"])
    wf.add_argument("--wf-folds", type=int, default=6)
    wf.add_argument("--wf-train-frac", type=float, default=0.7)
    wf.add_argument("--min-trades", type=int, default=1)
    wf.add_argument("--metric", default="sharpe")
    wf.add_argument("--seed", type=int, default=0, help="Random seed for walk-forward (0 = deterministic default)")
    wf.set_defaults(_handler=_run_walk_forward)

    # trade-live
    tl = sub.add_parser("trade-live")
    tl.add_argument("--mode", required=True, choices=["observe", "paper"])
    tl.add_argument("--strategy", required=True, choices=["ema_adx", "ema_adx_atr"])
    # параметры стратегии
    tl.add_argument("--ema-fast", type=int, default=12)
    tl.add_argument("--ema-slow", type=int, default=21)
    tl.add_argument("--adx-len", type=int, default=14)
    tl.add_argument("--adx-on", type=float, default=25.0)
    tl.add_argument("--adx-off", type=float, default=16.0)
    tl.add_argument("--require-di", action="store_true", default=False)
    tl.add_argument("--atr-len", type=int, default=14)
    tl.add_argument("--atr-mult", type=float, default=2.0)
    # observe
    tl.add_argument("--poll-sec", type=int, default=10)
    tl.add_argument("--summary-alert", action="store_true", default=False)
    tl.add_argument("--observe-rows", type=int, default=20, help="How many recent rows to print in observe table")
    tl.add_argument("--observe-print", choices=["always", "on-new-bar", "never"], default="on-new-bar")
    tl.add_argument("--max-mins", type=int, default=0, help="Stop after N minutes (0=forever)")
    tl.add_argument("--max-iter", type=int, default=0, help="Stop after N iterations (0=forever)")

    tl.add_argument("--fees-bps", type=float, default=0.0, help="Fees in basis points (round-trip)")
    tl.add_argument("--slippage-bps", type=float, default=0.0, help="Slippage per trade in bps")
    tl.add_argument("--size", type=float, default=100.0, help="Nominal position size")
    tl.add_argument("--sl-mult", type=float, default=0.0, help="Stop-loss ATR multiple (0=off)")
    tl.add_argument("--tp-mult", type=float, default=0.0, help="Take-profit ATR multiple (0=off)")
    tl.add_argument("--trail-mult", type=float, default=0.0, help="Trailing stop ATR multiple (0=off)")
    tl.set_defaults(_handler=lambda a: _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a))

    return p


def _dispatch_command(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        raise RuntimeError("No handler attached to sub-command")
    return int(handler(args))


def _run_cli(argv: Sequence[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return _dispatch_command(args)


def main() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
