# src/presentation/cli/engine.py
from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import UTC as _UTC, datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

LOG = logging.getLogger("cli")

# ===========================
# --- HTTP / EXMO OHLC
# ===========================

try:
    # если в инфраструктуре есть HttpClient — аккуратно используем
    from src.infrastructure.http.http_utils import HttpClient as _ExternalHttpClient  # type: ignore
except Exception:  # noqa: BLE001
    _ExternalHttpClient = None


class CompatHttpClient:
    """Мини-клиент: старается взять внешний HttpClient, иначе падает на requests."""

    def __init__(self, base_url: str, timeout: float, retries: int, backoff: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))
        self._client = None
        if _ExternalHttpClient is not None:
            try:
                self._client = _ExternalHttpClient(base_url=self.base_url,
                                                   timeout=self.timeout)  # type: ignore[call-arg]
            except Exception:  # noqa: BLE001
                try:
                    self._client = _ExternalHttpClient()  # type: ignore[call-arg]
                except Exception:  # noqa: BLE001
                    self._client = None

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        url = self._url(path)
        last_error = None
        for i in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                if self._client is not None and hasattr(self._client, "get"):
                    r = self._client.get(url, params=params)  # type: ignore[attr-defined]
                    st = int(getattr(r, "status_code", 0) or 0)
                    try:
                        return st, r.json()
                    except Exception:  # noqa: BLE001
                        return st, getattr(r, "text", "")
                # fallback — обычный requests
                import requests  # lazy import
                r = requests.get(url, params=params, timeout=self.timeout)
                st = int(r.status_code)
                try:
                    return st, r.json()
                except Exception:  # noqa: BLE001
                    return st, r.text
            except Exception as ex:  # noqa: BLE001
                last_error = f"{type(ex).__name__}: {ex}"
                if i < self.retries:
                    time.sleep(self.backoff * (2 ** i))
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                LOG.debug("[http] GET %s in %.1fms (try %d/%d)", url, dt_ms, i + 1, self.retries + 1)
        return 0, {"error": last_error or "HTTP error"}


_PERIODS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def _parse_candles(flag: str) -> Tuple[str, int]:
    tf, n = flag.split(":", 1)
    return tf.strip(), int(n)


def _fetch_exmo_ohlc(args, pair: str, candles: str) -> pd.DataFrame:
    """Тянем OHLC из EXMO; приводим к DataFrame с колонками:
    ['dt','timestamp','open','high','low','close','volume'].
    """
    try:
        tf, n = _parse_candles(candles)
    except Exception as e:  # noqa: BLE001
        LOG.error("bad --candles: %s", e)
        return pd.DataFrame()
    if tf not in _PERIODS:
        LOG.error("Unsupported timeframe '%s'", tf)
        return pd.DataFrame()

    period = _PERIODS[tf]
    t_to = int(time.time())
    t_from = t_to - n * period
    http = CompatHttpClient(
        base_url="https://api.exmo.com/v1.1",
        timeout=float(getattr(args, "http_timeout", 15.0)),
        retries=int(getattr(args, "http_retries", 0)),
        backoff=float(getattr(args, "http_backoff", 0.0)),
    )
    st, payload = http.get_json("candles_history", params={
        "symbol": pair, "resolution": tf, "from": t_from, "to": t_to
    })
    if st != 200:
        LOG.warning("[http] non-200 or no candles: status=%s", st)
        return pd.DataFrame()

    try:
        candles_payload = None
        if isinstance(payload, dict):
            if "candles" in payload:
                candles_payload = payload["candles"]
            elif isinstance(payload.get("result"), dict) and "candles" in payload["result"]:
                candles_payload = payload["result"]["candles"]
        if candles_payload is None:
            LOG.warning("[http] unexpected payload: %s", list(payload) if isinstance(payload, dict) else type(payload))
            return pd.DataFrame()

        df = pd.DataFrame(candles_payload)
        if df.empty:
            return df

        df = df.rename(columns={"t": "timestamp", "time": "timestamp",
                                "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        for c in ("open", "high", "low", "close", "volume"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        ts_col = "timestamp" if "timestamp" in df.columns else None
        if ts_col is None:
            for c in ("ts", "date"):
                if c in df.columns:
                    ts_col = c
                    break
        if ts_col is None:
            LOG.warning("[http] no timestamp in payload")
            return pd.DataFrame()

        ts = pd.to_numeric(df[ts_col], errors="coerce").astype("Int64").to_numpy(dtype="float64")
        # детект мс
        if np.nanmean(ts) > 10_000_000_000:
            ts = ts / 1000.0
        df["timestamp"] = ts.astype("int64", copy=False)
        df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.sort_values("dt").drop_duplicates(subset=["dt"]).reset_index(drop=True)

        # sanity: high/low должны покрывать open/close
        if {"open", "high", "low", "close"}.issubset(df.columns):
            hi = df[["open", "close"]].max(axis=1)
            lo = df[["open", "close"]].min(axis=1)
            df["high"] = np.maximum(df["high"], hi)
            df["low"] = np.minimum(df["low"], lo)

        for w in ("ok", "dropped_nonfinite", "duplicates_removed", "was_sorted", "ts_unit_detected"):
            LOG.warning("[ohlc] %s", w)  # ради совместимости с твоими логами

        return df[["dt", "timestamp", "open", "high", "low", "close", "volume"]].copy()
    except Exception as e:  # noqa: BLE001
        LOG.warning("[http] parse error: %s", e)
        return pd.DataFrame()


# ===========================
# --- Метрики / утилиты
# ===========================

def _utc_stamp() -> str:
    return _dt.now(_UTC).strftime("%Y%m%d_%H%M%S")


def _metrics_fast(pnls: np.ndarray) -> Dict[str, float]:
    n = int(len(pnls))
    if n == 0:
        return dict(n_trades=0, win_rate=0.0, avg_pnl=0.0, total_pnl=0.0,
                    max_dd=0.0, sharpe=float("-inf"), calmar=float("-inf"))
    total = float(np.nansum(pnls))
    avg = float(np.nanmean(pnls))
    std = float(np.nanstd(pnls, ddof=1)) if n > 1 else 0.0
    sharpe = (avg / std) if std > 0 else (float("inf") if avg > 0 else float("-inf"))
    eq = np.cumsum(pnls)
    dd = np.maximum.accumulate(eq) - eq
    max_dd = float(np.nanmax(dd)) if len(dd) else 0.0
    calmar = (total / max_dd) if max_dd > 0 else (float("inf") if total > 0 else float("-inf"))
    win_rate = float(np.mean(pnls > 0))
    return dict(n_trades=n, win_rate=win_rate, avg_pnl=avg, total_pnl=total,
                max_dd=max_dd, sharpe=sharpe, calmar=calmar)


# ===========================
# --- Работа с реестром стратегий
# ===========================

BuildTrades = Tuple[List[Dict[str, Any]], np.ndarray]


def _registry_get_builder() -> Dict[str, Any]:
    from src.backtest.registry import get_registry_builder  # type: ignore
    return get_registry_builder()


def _registry_get_grid(strategy: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Вернёт карту параметрических сеток.

    Поддерживает оба API:
      * get_default_grid() -> Dict[str, List[Dict]]
      * get_default_grid(strategy) -> List[Dict]
    Если strategy=None и доступна только новая сигнатура — соберём карту
    по всем стратегиям из реестра.
    """
    try:
        from src.backtest.registry import get_default_grid as _get_grid
    except Exception:  # noqa: BLE001
        return {}

    # 1) старая сигнатура: без аргументов возвращает dict
    try:
        grid_map = _get_grid()  # type: ignore[misc]
        if isinstance(grid_map, dict):
            if strategy is None:
                return grid_map
            return {strategy: list(grid_map.get(strategy, []))}
    except TypeError:
        pass  # значит новая сигнатура

    # 2) новая сигнатура
    try:
        if strategy is not None:
            grid_list = _get_grid(strategy)  # type: ignore[misc]
            if isinstance(grid_list, list):
                return {strategy: grid_list}
            return {strategy: []}
        # strategy не указан — соберём по всем билдерам
        out: Dict[str, List[Dict[str, Any]]] = {}
        for s in _registry_get_builder().keys():
            try:
                out[s] = list(_get_grid(s))  # type: ignore[misc]
            except Exception:  # noqa: BLE001
                out[s] = []
        return out
    except Exception:  # noqa: BLE001
        return {}


def _build_trades(strategy: str, df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """Единообразный вызов билдера стратегии.

    Всегда используем builder.build(...).
    Возвращаем (trades, pnls) и приводим pnls к np.ndarray.
    """
    builders = _registry_get_builder()
    if strategy not in builders:
        raise RuntimeError(f"Неизвестная стратегия: {strategy!r}. Доступны: {list(builders)}")

    builder = builders[strategy]
    if not hasattr(builder, "build"):
        raise RuntimeError(f"StrategyBuilder для {strategy!r} не имеет метода build(df=..., params=...).")

    try:
        res = builder.build(df=df, params=params)
    except TypeError:
        # fallback — вдруг сигнатура позиционная
        res = builder.build(df, params)

    if not isinstance(res, tuple) or len(res) < 2:
        raise RuntimeError("builder.build(...) должен вернуть кортеж (trades, pnls[, extra]).")

    trades, pnls = res[0], res[1]
    if not isinstance(trades, list):
        raise TypeError("trades должен быть list[dict].")

    # приведём pnls
    if hasattr(pnls, "to_numpy"):
        pnls = pnls.to_numpy()  # type: ignore[attr-defined]
    pnls = np.asarray(pnls)

    return trades, pnls


# ===========================
# --- Автоэскалация параметров
# ===========================

def _auto_expand_history(args) -> bool:
    step = int(getattr(args, "auto_candles_step", 400) or 400)
    cap = int(getattr(args, "auto_candles_max", 4000) or 4000)
    tf, n = args.candles.split(":")
    n = int(n)
    if n >= cap:
        return False
    args.candles = f"{tf}:{min(cap, n + step)}"
    LOG.info("[auto] увеличиваю историю: %s -> %s", f"{tf}:{n}", args.candles)
    return True


def _auto_relax_min_trades(args) -> bool:
    if not hasattr(args, "min_trades"):
        return False
    floor = int(getattr(args, "auto_min_trades_min", 1) or 1)
    cur = int(getattr(args, "min_trades", 1) or 1)
    if cur <= floor:
        return False
    args.min_trades = max(floor, cur - 1)
    LOG.info("[auto] ослабляю фильтр: --min-trades -> %d", args.min_trades)
    return True


def _auto_guard_init(args) -> None:
    if getattr(args, "_auto_attempts_left", None) is None:
        args._auto_attempts_left = int(getattr(args, "auto_attempts", 6) or 6)


# ===========================
# --- Общие хелперы CLI
# ===========================

def _strategy_params_from_args(args) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # EMA/ADX
    for a, k in (("ema_fast", "fast"), ("ema_slow", "slow"),
                 ("adx_len", "adx_len"), ("adx_on", "on"), ("adx_off", "off")):
        if hasattr(args, a):
            v = getattr(args, a)
            if v is not None:
                out[k] = int(v) if isinstance(v, int) else float(v)
    if hasattr(args, "require_di"):
        out["require_di"] = bool(args.require_di)

    # ATR (для расширенной версии)
    if hasattr(args, "atr_len") and args.atr_len:
        out["atr_len"] = int(args.atr_len)
    if hasattr(args, "atr_mult") and args.atr_mult is not None:
        out["atr_mult"] = float(args.atr_mult)

    # RSI2
    if hasattr(args, "rsi_len"):
        out["rsi_len"] = int(args.rsi_len)
    if hasattr(args, "rsi_buy_below"):
        out["buy_below"] = float(args.rsi_buy_below)
    if hasattr(args, "rsi_sell_above"):
        out["sell_above"] = float(args.rsi_sell_above)

    # Bollinger breakout
    if hasattr(args, "bb_len"):
        out["bb_len"] = int(args.bb_len)
    if hasattr(args, "bb_k"):
        out["bb_k"] = float(args.bb_k)

    # fees / size / exits
    for a in ("fees_bps", "slippage_bps", "size", "sl_mult", "tp_mult", "trail_mult"):
        if hasattr(args, a):
            out[a] = float(getattr(args, a))
    return out


def _dump_table(args, pair: str, candles: str, suffix: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(
        args.out_dir,
        f"{(args.out_prefix + '_') if args.out_prefix else ''}"
        f"{pair.replace('/', '_')}_{candles.replace(':', '_')}_{suffix}_{_utc_stamp()}.csv"
    )
    df.to_csv(path, index=False)
    LOG.info("[out] saved %s rows=%d", path, len(df))


# ===========================
# --- Команды: OPT / RB / WF / LIVE / AUTO
# ===========================

def run_optimize(args) -> int:
    LOG.info("Command: optimize strategy=%s", args.strategy)
    _auto_guard_init(args)

    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        if args.auto and args._auto_attempts_left > 0 and _auto_expand_history(args):
            args._auto_attempts_left -= 1
            return run_optimize(args)
        print("(no data)")
        return 0

    grid_map = _registry_get_grid(args.strategy)
    grid = list(grid_map.get(args.strategy, []))
    if not grid:
        LOG.warning("Empty param grid for %s", args.strategy)
        print("(no rows)")
        return 0

    rows: List[Dict[str, Any]] = []
    for p in grid:
        try:
            _, pnls = _build_trades(args.strategy, df, p)
            rows.append(dict(strategy=args.strategy, params=p, **_metrics_fast(pnls)))
        except Exception as e:  # noqa: BLE001
            LOG.debug("optimize: skip %s -> %s", p, e)

    if not rows:
        if args.auto and args._auto_attempts_left > 0 and (_auto_expand_history(args) or _auto_relax_min_trades(args)):
            args._auto_attempts_left -= 1
            return run_optimize(args)
        print("(no rows)")
        return 0

    res = pd.DataFrame(rows)
    if getattr(args, "min_trades", 0):
        res = res[res["n_trades"] >= int(args.min_trades)]
    if res.empty:
        if args.auto and args._auto_attempts_left > 0 and (_auto_expand_history(args) or _auto_relax_min_trades(args)):
            args._auto_attempts_left -= 1
            return run_optimize(args)
        print("(no rows)")
        return 0

    metric = getattr(args, "metric", "sharpe")
    res = res.sort_values(by=metric, ascending=(metric == "max_dd"))
    res = res.iloc[::-1] if metric != "max_dd" else res
    shown = res.head(int(getattr(args, "top_n", 10) or 10))

    with pd.option_context("display.max_colwidth", 120, "display.width", 1000):
        print(shown.to_string(index=False))

    _dump_table(args, args.pair, args.candles, "optimize", shown)
    return 0


def run_robustness(args) -> int:
    LOG.info("Command: robustness strategy=%s", args.strategy)
    _auto_guard_init(args)

    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        if args.auto and args._auto_attempts_left > 0 and _auto_expand_history(args):
            args._auto_attempts_left -= 1
            return run_robustness(args)
        print("(no rows)")
        return 0

    params = _strategy_params_from_args(args) or next(
        iter(_registry_get_grid(args.strategy).get(args.strategy, [{}])),
        {}
    )
    windows = max(1, int(getattr(args, "rb_windows", 8)))
    n = len(df)
    rows: List[Dict[str, Any]] = []
    for i in range(windows):
        a, b = int(i * n / windows), int((i + 1) * n / windows)
        part = df.iloc[a:b]
        if part.empty:
            continue
        try:
            _, pnls = _build_trades(args.strategy, part, params)
            m = _metrics_fast(pnls)
            row: Dict[str, Any] = dict(strategy=args.strategy, params=params, **m)
            row["window"] = f"{i + 1}/{windows}"
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            LOG.debug("robustness: skip fold %s: %s", f"{i + 1}/{windows}", e)

    if not rows:
        if args.auto and args._auto_attempts_left > 0 and (_auto_expand_history(args) or _auto_relax_min_trades(args)):
            args._auto_attempts_left -= 1
            return run_robustness(args)
        print("(no rows)")
        return 0

    res = pd.DataFrame(rows)
    if getattr(args, "min_trades", 0):
        res = res[res["n_trades"] >= int(args.min_trades)]
    if res.empty:
        if args.auto and args._auto_attempts_left > 0 and (_auto_expand_history(args) or _auto_relax_min_trades(args)):
            args._auto_attempts_left -= 1
            return run_robustness(args)
        print("(no rows)")
        return 0

    metric = getattr(args, "metric", "sharpe")
    res = res.sort_values(by=metric, ascending=(metric == "max_dd"))
    with pd.option_context("display.max_colwidth", 120, "display.width", 1000):
        print(res.to_string(index=False))

    _dump_table(args, args.pair, args.candles, "robustness", res)
    return 0


def run_walk_forward(args) -> int:
    LOG.info("Command: walk-forward strategy=%s", args.strategy)
    _auto_guard_init(args)

    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        if args.auto and args._auto_attempts_left > 0 and _auto_expand_history(args):
            args._auto_attempts_left -= 1
            return run_walk_forward(args)
        print("(no rows)")
        return 0

    grid = list(_registry_get_grid(args.strategy).get(args.strategy, []))
    if not grid:
        LOG.warning("Empty param grid for %s", args.strategy)
        print("(no rows)")
        return 0

    folds = max(1, int(getattr(args, "wf_folds", 6)))
    train_frac = min(max(float(getattr(args, "wf_train_frac", 0.7)), 0.1), 0.95)
    metric = getattr(args, "metric", "sharpe")
    min_tr = int(getattr(args, "min_trades", 0) or 0)

    n = len(df)
    rows: List[Dict[str, Any]] = []

    for i in range(folds):
        s, e = int(i * n / folds), int((i + 1) * n / folds)
        seg = df.iloc[s:e]
        if seg.empty:
            continue
        split = s + int((e - s) * train_frac)
        train, test = df.iloc[s:split], df.iloc[split:e]
        if train.empty or test.empty:
            continue

        best = None
        for p in grid:
            try:
                _, tr = _build_trades(args.strategy, train, p)
                mt = _metrics_fast(tr)
                if min_tr and mt["n_trades"] < min_tr:
                    continue
                val = mt.get(metric, -math.inf)
                if (best is None) or (val > best["val"]):
                    best = dict(params=p, mt=mt, val=val)
            except Exception as e:  # noqa: BLE001
                LOG.debug("wf: train skip params %s: %s", p, e)
        if best is None:
            continue

        try:
            _, te = _build_trades(args.strategy, test, best["params"])
            ms = _metrics_fast(te)
            row = dict(strategy=args.strategy, fold=f"{i + 1}/{folds}", params=best["params"])
            row.update({f"train_{k}": v for k, v in best["mt"].items()})
            row.update({f"test_{k}": v for k, v in ms.items()})
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            LOG.debug("wf: test failed for %s: %s", best["params"], e)

    if not rows:
        if args.auto and args._auto_attempts_left > 0 and (_auto_expand_history(args) or _auto_relax_min_trades(args)):
            args._auto_attempts_left -= 1
            return run_walk_forward(args)
        print("(no rows)")
        return 0

    res = pd.DataFrame(rows).sort_values(by=f"test_{metric}", ascending=(metric == "max_dd"))
    print(f"<wf best per fold from {folds} folds>")
    with pd.option_context("display.max_colwidth", 120, "display.width", 1000):
        print(res.to_string(index=False))

    _dump_table(args, args.pair, args.candles, "walkforward", res)
    return 0


def run_trade_live(args) -> int:
    mode = args.mode
    LOG.info("[live] %s %s %s strategy=%s", mode, args.pair, args.candles, args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.warning("[live] no candles")
        return 0

    params = _strategy_params_from_args(args)
    trades, pnls = _build_trades(args.strategy, df, params)
    met = _metrics_fast(pnls)

    LOG.info("[live/%s] using params: %s", mode, params)
    LOG.info("[live/%s] trades=%d total_pnl=%.6f sharpe=%.3f",
             mode, int(met["n_trades"]), float(met["total_pnl"]), float(met["sharpe"]))
    return 0


def run_auto(args) -> int:
    LOG.info("Command: auto (strategies=%s, score=%s)", ",".join(args.strategies), args.score)
    _auto_guard_init(args)
    best: Optional[Dict[str, Any]] = None
    best_df: Optional[pd.DataFrame] = None

    # шаги: растим историю; если не вышло — ослабляем min_trades
    base_tf, base_n = _parse_candles(args.candles)
    steps = list(range(base_n, int(args.auto_candles_max) + 1, int(args.auto_candles_step)))
    if steps[-1] != int(args.auto_candles_max):
        steps.append(int(args.auto_candles_max))

    for n in steps + [steps[-1]]:  # повтор с последним шагом, если дальше ослабляем min_trades
        args.candles = f"{base_tf}:{n}"
        df = _fetch_exmo_ohlc(args, args.pair, args.candles)
        if df.empty:
            continue

        all_rows: List[pd.DataFrame] = []
        grid_map = _registry_get_grid()  # можно без strategy

        for strat in args.strategies:
            grid = grid_map.get(strat, [])
            if not grid:
                continue
            rows: List[Dict[str, Any]] = []
            for p in grid:
                try:
                    _, pnls = _build_trades(strat, df, p)
                    rows.append(dict(strategy=strat, params=p, **_metrics_fast(pnls)))
                except Exception as e:  # noqa: BLE001
                    LOG.debug("[auto] %s skip %s -> %s", strat, p, e)
            if rows:
                all_rows.append(pd.DataFrame(rows))

        if not all_rows:
            continue

        cand = pd.concat(all_rows, ignore_index=True)
        if getattr(args, "min_trades", 0):
            cand = cand[cand["n_trades"] >= int(args.min_trades)]
        if cand.empty:
            continue

        metric = args.score
        cand = cand.sort_values([metric, "total_pnl"], ascending=[False, False]).reset_index(drop=True)
        top = cand.iloc[0].to_dict()
        LOG.info("[auto] prelim best: %s %s %s=%.6f n_trades=%d",
                 top["strategy"], top["params"], metric, float(top[metric]), int(top["n_trades"]))
        best, best_df = top, cand
        break

    if best is None:
        if _auto_relax_min_trades(args) and args._auto_attempts_left > 0:
            args._auto_attempts_left -= 1
            return run_auto(args)
        LOG.error("[auto] no viable configuration found")
        return 2

    # сохраняем артефакты
    os.makedirs(os.path.join("out", "auto"), exist_ok=True)
    stamp = _utc_stamp()
    if best_df is not None and not best_df.empty:
        path = os.path.join("out", "auto",
                            f"{args.pair.replace('/', '_')}_{args.candles.replace(':', '_')}_auto_candidates_{stamp}.csv")
        best_df.to_csv(path, index=False)
        LOG.info("[out] saved %s rows=%d", path, len(best_df))

    final = dict(pair=args.pair, candles=args.candles,
                 strategy=best["strategy"], params=best["params"],
                 metric=args.score, score=float(best[args.score]))
    out_json = os.path.join("out", "auto",
                            f"{args.pair.replace('/', '_')}_{args.candles.replace(':', '_')}_auto_best_{stamp}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(final, ensure_ascii=False, indent=2))
        f.write("\n")

    LOG.info("[out] saved %s", out_json)

    # подсказка запуска (paper)
    p = final["params"]
    strat = final["strategy"]
    extra: List[str] = []
    if strat in ("ema_adx", "ema_adx_atr"):
        extra += [f"--ema-fast {p['fast']}", f"--ema-slow {p['slow']}",
                  f"--adx-len {p['adx_len']}", f"--adx-on {p['on']}", f"--adx-off {p['off']}"]
        if p.get("require_di"):
            extra.append("--require-di")
        if strat == "ema_adx_atr" and "atr_len" in p:
            extra.append(f"--atr-len {p['atr_len']}")
    elif strat == "rsi2":
        extra += [f"--rsi-len {p['rsi_len']}", f"--rsi-buy-below {p['buy_below']}",
                  f"--rsi-sell-above {p['sell_above']}"]
    elif strat == "bb_breakout":
        extra += [f"--bb-len {p['bb_len']}", f"--bb-k {p['bb_k']}"]

    LOG.info("")
    LOG.info("▶ Рекомендуемый запуск (paper):")
    LOG.info("PYTHONPATH=. python -m src.presentation.cli.app \\")
    LOG.info("  --pair %s --candles %s \\", args.pair, args.candles)
    LOG.info("  --print-trade-summary \\")
    LOG.info("  trade-live --mode paper --strategy %s \\", strat)
    LOG.info("  %s", " ".join(extra))
    LOG.info("")
    return 0
