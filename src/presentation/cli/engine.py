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

_PERIODS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def _utc_stamp() -> str:
    return _dt.now(_UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_candles(flag: str) -> Tuple[str, int]:
    tf, n = flag.split(":", 1)
    return tf.strip(), int(n)


# ===== HTTP small client =====

class _HttpClient:
    def __init__(self, base_url: str, timeout: float, retries: int, backoff: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        import requests  # lazy import
        url = self._url(path)
        last_err: Optional[str] = None
        for i in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                r = requests.get(url, params=params, timeout=self.timeout)
                st = int(r.status_code)
                try:
                    js = r.json()
                except Exception:
                    js = r.text
                return st, js
            except Exception as ex:
                last_err = f"{type(ex).__name__}: {ex}"
                if i < self.retries:
                    time.sleep(self.backoff * (2 ** i))
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                LOG.debug("[http] GET %s in %.1fms (try %d/%d)", url, dt_ms, i + 1, self.retries + 1)
        return 0, {"error": last_err or "HTTP error"}


def _fetch_exmo_ohlc(args, pair: str, candles: str) -> pd.DataFrame:
    tf, n = _parse_candles(candles)
    period = _PERIODS.get(tf, 300)
    now = int(time.time())
    params = {"symbol": pair, "resolution": int(period / 60), "from": now - n * period, "to": now}
    base_url = "https://api.exmo.com/v1.1"
    client = _HttpClient(base_url, args.http_timeout, args.http_retries, args.http_backoff)
    st, js = client.get_json("/candles_history", params=params)
    if st != 200 or not isinstance(js, dict) or "candles" not in js:
        LOG.warning("[exmo] bad response status=%s body=%s", st, str(js)[:200])
        return pd.DataFrame()
    rows = js.get("candles", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # normalize
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    ts = pd.to_numeric(df["timestamp"], errors="coerce").astype("Int64").to_numpy(dtype="float64")
    # some APIs return ms
    if np.nanmean(ts) > 10_000_000_000:
        ts = ts / 1000.0
    df["timestamp"] = ts.astype("int64", copy=False)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.sort_values("dt").drop_duplicates(subset=["dt"]).reset_index(drop=True)

    # high/low sanity
    if {"open", "high", "low", "close"}.issubset(df.columns):
        hi = df[["open", "close"]].max(axis=1)
        lo = df[["open", "close"]].min(axis=1)
        df["high"] = df["high"].fillna(hi).where(df["high"] >= hi, hi)
        df["low"] = df["low"].fillna(lo).where(df["low"] <= lo, lo)

    return df[["dt", "timestamp", "open", "high", "low", "close", "volume"]]


# ===== Registry bridges =====

def _registry_get_builder() -> Dict[str, Any]:
    from src.backtest.registry import get_registry_builder
    return get_registry_builder()


def _registry_get_grid(strategy: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    from src.backtest.registry import get_default_grid as _get_grid
    # support both signatures (get_default_grid() vs get_default_grid(name))
    try:
        grid_map = _get_grid()  # type: ignore[misc]
        if isinstance(grid_map, dict):
            if strategy is None:
                return grid_map
            return {strategy: list(grid_map.get(strategy, []))}
    except TypeError:
        pass
    if strategy is None:
        names = list(_registry_get_builder().keys())
        out: Dict[str, List[Dict[str, Any]]] = {}
        for n in names:
            try:
                out[n] = list(_get_grid(n))  # type: ignore[misc]
            except Exception:
                out[n] = []
        return out
    return {strategy: list(_get_grid(strategy))}  # type: ignore[misc]


def _metrics_fast(pnls: np.ndarray) -> Dict[str, float]:
    pnls = np.asarray(pnls, dtype=float)
    n = len(pnls)
    if n == 0:
        return {"n_trades": 0, "total_pnl": 0.0, "sharpe": -float("inf"), "winrate": 0.0}
    total = float(pnls.sum())
    wins = float((pnls > 0.0).sum()) / float(n)
    mean = float(pnls.mean())
    std = float(pnls.std(ddof=1)) if n > 1 else 0.0
    sharpe = mean / std if std > 0 else (math.copysign(float("inf"), mean) if mean != 0 else 0.0)
    return {"n_trades": int(n), "total_pnl": total, "winrate": wins, "sharpe": sharpe}


def _build_trades(strategy: str, df: pd.DataFrame, params: Dict[str, Any]):
    builders = _registry_get_builder()
    if strategy not in builders:
        raise KeyError(f"strategy not registered: {strategy}")
    build_fn = builders[strategy].build
    trades, pnls, _extra = build_fn(df, params)
    if isinstance(pnls, pd.Series):
        pnls = pnls.to_numpy()
    return trades, np.asarray(pnls, dtype=float)


# ===== Helpers for auto-escalation =====

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
    LOG.info("[auto] ослабляю min_trades: -> %d", args.min_trades)
    return True


def _save_csv(args, df: pd.DataFrame, suffix: str) -> None:
    os.makedirs(args.out_dir, exist_ok=True)
    pair = args.pair
    candles = args.candles
    path = os.path.join(
        args.out_dir,
        f"{(args.out_prefix + '_') if args.out_prefix else ''}"
        f"{pair.replace('/', '_')}_{candles.replace(':', '_')}_{suffix}_{_utc_stamp()}.csv"
    )
    df.to_csv(path, index=False)
    LOG.info("[out] saved %s rows=%d", path, len(df))


# ===== Commands =====

def run_optimize(args) -> int:
    LOG.info("Command: optimize strategy=%s", args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0

    grid_map = _registry_get_grid(args.strategy)
    grid = list(grid_map.get(args.strategy, []))
    if not grid:
        LOG.warning("Empty param grid for %s", args.strategy)
        return 0

    rows: List[Dict[str, Any]] = []
    for p in grid:
        try:
            _, pnls = _build_trades(args.strategy, df, p)
            m = _metrics_fast(pnls)
            m["params"] = p
            rows.append(m)
        except Exception as e:
            LOG.debug("optimize: skip params %s: %s", p, e)

    if not rows:
        print("(no rows)")
        return 0

    metric = getattr(args, "metric", "sharpe")
    rows.sort(key=lambda r: r.get(metric, -math.inf), reverse=True)
    if getattr(args, "top_n", None):
        rows = rows[: int(args.top_n)]

    out = pd.DataFrame(rows)
    _save_csv(args, out, "optimize")
    return 0


def run_robustness(args) -> int:
    LOG.info("Command: robustness strategy=%s", args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0
    params = getattr(args, "params", None)
    if not params:
        grid = _registry_get_grid(args.strategy).get(args.strategy, [])
        params = grid[0] if grid else {}

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
            m["window"] = f"{i + 1}/{windows}"
            m["params"] = params
            rows.append(m)
        except Exception as e:
            LOG.debug("robustness: skip fold %s: %s", f"{i + 1}/{windows}", e)

    if not rows:
        print("(no rows)")
        return 0

    out = pd.DataFrame(rows)
    _save_csv(args, out, "robustness")
    return 0


def run_walk_forward(args) -> int:
    LOG.info("Command: walk-forward strategy=%s", args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0
    folds = max(2, int(getattr(args, "wf_folds", 6)))
    train_frac = float(getattr(args, "wf_train_frac", 0.7))
    grid = _registry_get_grid(args.strategy).get(args.strategy, [])
    min_tr = int(getattr(args, "min_trades", 1))
    metric = getattr(args, "metric", "sharpe")

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
            except Exception as e:
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
        except Exception as e:
            LOG.debug("wf: test skip params %s: %s", best["params"], e)

    if not rows:
        print("(no rows)")
        return 0

    out = pd.DataFrame(rows)
    _save_csv(args, out, "walk_forward")
    return 0


# ===== LIVE (observe/paper) =====

def _live_params_from_args(args) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    # ema_adx
    if hasattr(args, "ema_fast"):
        params["fast"] = int(args.ema_fast)
    if hasattr(args, "ema_slow"):
        params["slow"] = int(args.ema_slow)
    if hasattr(args, "adx_len"):
        params["adx_len"] = int(args.adx_len)
    if hasattr(args, "adx_on"):
        params["on"] = float(args.adx_on)
    if hasattr(args, "adx_off"):
        params["off"] = float(args.adx_off)
    if hasattr(args, "require_di"):
        params["require_di"] = bool(args.require_di)

    # fees/slip (если билдер их учитывает — передадим)
    if hasattr(args, "fee_bps"):
        params["fees_bps"] = float(args.fee_bps)
    if hasattr(args, "slip_bps"):
        params["slippage_bps"] = float(args.slip_bps)

    return params


def _evaluate_last_signal(strategy: str, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Строим сигналы на полной истории и читаем последнюю точку.
    """
    builders = _registry_get_builder()
    if strategy not in builders:
        return {"ok": False, "msg": f"strategy not registered: {strategy}"}

    build_fn = builders[strategy].build
    try:
        # билдер возвращает (trades, pnls, extra); нам нужны extra, чтобы понять EMA/ADX и пр.,
        # но для простоты прочитаем по косвенным признакам (или расширим extra — на твой вкус).
        trades, pnls, extra = build_fn(df, params)
        last_row = df.iloc[-1]
        # простое резюме
        status = {
            "ok": True,
            "ts": int(last_row["timestamp"]),
            "dt": str(last_row["dt"]),
            "close": float(last_row["close"]),
            "n_trades_alltime": int(len(trades)),
        }
        # добавим из extra, если есть
        if isinstance(extra, dict):
            for k in ("ema_fast", "ema_slow", "adx"):
                if k in extra:
                    ser = extra[k]
                    try:
                        status[k] = float(pd.to_numeric(ser.iloc[-1], errors="coerce"))
                    except Exception:
                        pass
        return status
    except Exception as e:
        return {"ok": False, "msg": f"build failed: {e}"}


def run_trade_live(args) -> int:
    LOG.info("Command: trade-live mode=%s strategy=%s", args.mode, args.strategy)

    # Начальная загрузка истории
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0

    print(f"[live] {args.mode} {args.pair} {args.candles} strategy={args.strategy} rows={len(df)}")

    poll = int(getattr(args, "poll_sec", 10))
    summary = bool(getattr(args, "summary_alert", False))
    params = _live_params_from_args(args)

    # внутреннее состояние наблюдения (без реальной торговли)
    last_print_ts: Optional[int] = None
    simulated_in_pos = False  # просто отображение (можно расширить до paper)

    try:
        while True:
            # обновим последний кусок истории (оставим ту же глубину, это быстрее и воспроизводимо)
            df = _fetch_exmo_ohlc(args, args.pair, args.candles)
            if df.empty:
                LOG.warning("[live] empty data on refresh")
                time.sleep(poll)
                continue

            last = df.iloc[-1]
            last_ts = int(last["timestamp"])
            close = float(last["close"])

            # оценим сигнал на последней свече
            sig = _evaluate_last_signal(args.strategy, df, params)
            if not sig.get("ok"):
                LOG.debug("[live] eval error: %s", sig.get("msg"))

            # простая симуляция статуса: если EMAfast>EMAslow и ADX>on — считаем вход, иначе выход
            # (это консистентно с ema_adx.signals)
            fast = sig.get("ema_fast")
            slow = sig.get("ema_slow")
            adx = sig.get("adx")
            entered = exited = False
            if fast is not None and slow is not None and adx is not None:
                long_cond = (fast > slow) and (adx >= float(params.get("on", 20.0)))
                off_cond = (adx <= float(params.get("off", 14.0))) or (fast <= slow)
                if long_cond and not simulated_in_pos:
                    simulated_in_pos = True
                    entered = True
                elif simulated_in_pos and off_cond:
                    simulated_in_pos = False
                    exited = True

            # Вывод
            if summary:
                # печатаем только на изменениях свэчи/сигнала, чтобы не сыпать логами
                if last_print_ts != last_ts or entered or exited:
                    state = "IN" if simulated_in_pos else "OUT"
                    bits = [
                        f"[tick] {args.pair} {args.candles} {args.strategy}",
                        f"dt={last['dt']} close={close:.6f}",
                        f"state={state}",
                    ]
                    if fast is not None and slow is not None:
                        bits.append(f"ema_f={fast:.6f} ema_s={slow:.6f}")
                    if adx is not None:
                        bits.append(f"adx={adx:.3f} on={params.get('on', 20.0)} off={params.get('off', 14.0)}")
                    if entered:
                        bits.append("SIG=ENTER")
                    if exited:
                        bits.append("SIG=EXIT")
                    print("  ".join(bits))
                    last_print_ts = last_ts
            else:
                # лаконичный heartbeat
                print(f"[live] {last['dt']} close={close:.6f} rows={len(df)}", flush=True)

            time.sleep(poll)

    except KeyboardInterrupt:
        print("\n[live] stopped by user")
        return 0
    except Exception as e:
        LOG.exception("[live] failure: %s", e)
        return 1


def run_auto(args) -> int:
    LOG.info("Command: auto (strategies=%s, score=%s)", ",".join(args.strategies), args.score)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        print("(no data)")
        return 0
    score = getattr(args, "score", "sharpe")
    best: Optional[Dict[str, Any]] = None
    for strat in args.strategies:
        grid = _registry_get_grid(strat).get(strat, [])
        for p in grid:
            try:
                _, pnls = _build_trades(strat, df, p)
                m = _metrics_fast(pnls)
                val = m.get(score, -math.inf)
                if (best is None) or (val > best["val"]):
                    best = {"strategy": strat, "params": p, "metrics": m, "val": val}
            except Exception as e:
                LOG.debug("auto: skip %s %s: %s", strat, p, e)
    if not best:
        print("(no rows)")
        return 0

    stamp = _utc_stamp()
    out_json = os.path.join("out", "auto",
                            f"{args.pair.replace('/', '_')}_{args.candles.replace(':', '_')}_auto_best_{stamp}.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(best, f, ensure_ascii=False, indent=2)
        f.write("\n")
    LOG.info("[out] saved %s", out_json)
    return 0
