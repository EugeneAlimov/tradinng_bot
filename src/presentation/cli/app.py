# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast
from src.backtest.execution import ExecConfig, enrich_trades_with_costs, pnls_from_trades
from src.strategies.registry import get_strategy
from src.backtest.schemas import build_trades_schema
from src.backtest.reports import summarize_trades
from src.backtest.manifest import write_manifest

from src.indicators.adx import compute_adx
from src.strategies.ema_adx import signals as ema_adx_signals

import numpy as np
import pandas as pd

# Унификация метрик/артефактов + sanity для OHLC
from src.backtest.selector import (
    Selector,
    SelectorConfig,
    dump_schema,
    make_artifact_path,
)
from src.backtest.ohlc_sanity import sanity_check_ohlc

# ---------------------------------------------------------------------
# HTTP клиент (инфраструктура проекта) + fallback
# ---------------------------------------------------------------------
try:
    from src.infrastructure.http.http_utils import HttpClient, HttpConfig  # type: ignore
except ImportError:
    import urllib3  # type: ignore


    class HttpConfig:  # type: ignore[no-redef]
        def __init__(
                self,
                base_url: str = "https://api.exmo.com",
                retries: int = 3,
                backoff: float = 1.0,
                timeout: float = 15.0,
        ):
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
            status = int(getattr(r, "status", 0) or 0)
            try:
                data = json.loads(r.data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                data = None
            return status, data


# ---------------------------------------------------------------------
# Метрики (проектные или локальный fallback)
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
    win_rate = float(wins / n) if n else 0.0
    max_dd, _ = _local_drawdown_and_equity(pnl)
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


# Попытка использовать проектные метрики, если доступны.
try:
    import src.backtest.metrics as metrics_mod  # type: ignore

    _HAS_COMPUTE_METRICS = hasattr(metrics_mod, "compute_metrics")
    _HAS_EQUITY_METRICS = hasattr(metrics_mod, "compute_equity_metrics")


    def _normalize_base(m: Dict[str, Any], pnl: np.ndarray) -> Dict[str, float]:
        # Нормализуем ключи под наш Selector API
        base = {
            "n_trades": int(m.get("n_trades", len(pnl))),
            "win_rate": float(m.get("win_rate", 0.0)),
            "avg_pnl": float(m.get("avg_pnl", 0.0)),
            "total_pnl": float(m.get("total_pnl", float(np.sum(pnl)))),
            "max_dd": float(m.get("max_dd", 0.0)),
            "sharpe": float(m.get("sharpe", 0.0)),
            "calmar": float(m.get("calmar", 0.0)),
        }
        return base


    def _compute_metrics(pnl: np.ndarray) -> Dict[str, float]:
        # 1) База: проектная compute_metrics, если есть, иначе локальная
        if _HAS_COMPUTE_METRICS:
            m = metrics_mod.compute_metrics(pnl=pnl)  # type: ignore[attr-defined]
            out = _normalize_base(m, pnl)
        else:
            out = _local_metrics(pnl)

        # 2) Расширенные метрики от compute_equity_metrics (если есть)
        if _HAS_EQUITY_METRICS:
            # Кривая эквити: старт 0.0, шаг — накопленные pnl (net)
            equity = np.concatenate([[0.0], np.cumsum(pnl)]) if pnl.size else np.asarray([0.0], dtype=float)
            # n_wins можем оценить по win_rate*n_trades — это опциональный параметр; trade_pnls передадим прямо pnl
            n_trades = int(out.get("n_trades", len(pnl)))
            n_wins = int(round(out.get("win_rate", 0.0) * n_trades))
            adv = metrics_mod.compute_equity_metrics(  # type: ignore[attr-defined]
                equity=equity,
                trade_pnls=pnl,
                n_trades=n_trades,
                n_wins=n_wins,
                # bars_per_year/start_equity/exposure_pct можно не указывать — функция умеет без них
            )
            # Не переопределяем базовые ключи; добавляем только новые
            for k, v in adv.items():
                if k not in out:
                    try:
                        out[k] = float(v) if isinstance(v, (int, float)) else v  # аккуратно приводим
                    except Exception:
                        out[k] = v
        return out

except ImportError:
    _compute_metrics = _local_metrics  # type: ignore[assignment]

# ---------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------
LOG = logging.getLogger("cli")


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _ensure_out_dir(args) -> None:
    """Проверяем, что out_dir существует и доступен для записи. При проблемах — используем /tmp/exmo_artifacts."""
    path = getattr(args, "out_dir", "out/data") or "out/data"
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".__write_test__")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return
    except Exception as e:
        LOG.error("[artifacts] cannot write to out-dir '%s': %s", path, e)

    fallback = "/tmp/exmo_artifacts"
    try:
        os.makedirs(fallback, exist_ok=True)
        test_path = os.path.join(fallback, ".__write_test__")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        setattr(args, "out_dir", fallback)
        LOG.warning("[artifacts] switched out-dir to %s", fallback)
    except Exception as e2:
        LOG.error("[artifacts] fallback out-dir '%s' also not writable: %s", fallback, e2)


# ---------------------------------------------------------------------
# Парсинг "5m:2000"
# ---------------------------------------------------------------------
_RESOLUTION_MAP = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


@dataclass
class CandleSpec:
    tf_str: str
    tf_minutes: int
    bars: int


def _parse_candles(spec: str) -> CandleSpec:
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


def _normalize_epoch_seconds(ts: pd.Series) -> pd.Series:
    """
    Нормализует Unix time к секундам.
    Поддерживает вход в секундах, миллисекундах, микросекундах.
    """
    s = pd.to_numeric(ts, errors="coerce")
    if s.empty:
        return s.astype("int64")

    vmax = float(np.nanmax(s.to_numpy()))
    scale = 1
    if vmax > 1e14:  # ~микросекунды (сейчас ~1.7e15)
        scale = 1_000_000
        LOG.debug("[ohlc] detected microsecond timestamps → ÷1e6")
    elif vmax > 1e12:  # ~миллисекунды (сейчас ~1.7e12)
        scale = 1_000
        LOG.debug("[ohlc] detected millisecond timestamps → ÷1e3")

    if scale != 1:
        s = (s // scale)

    return s.astype("int64")


def _fetch_exmo_ohlc(args, pair: str, candles: str) -> pd.DataFrame:
    cspec = _parse_candles(candles)
    now = _unix_now()
    span_sec = cspec.tf_minutes * 60 * cspec.bars
    frm, to = now - span_sec, now

    url = _exmo_url(pair, cspec.tf_minutes, frm, to)
    if os.getenv("EXMO_DEBUG"):
        LOG.debug("Starting new HTTPS connection (1): api.exmo.com:443")
        LOG.debug("[EXMO] → GET %s", url)

    status, payload = _get_http(args).get_json(url)  # type: ignore[attr-defined]
    if os.getenv("EXMO_DEBUG"):
        keys = list(payload.keys()) if isinstance(payload, dict) else None
        LOG.debug("[EXMO] ← status=%s keys=%s", status, keys)

    if status != 200 or payload is None or "candles" not in payload:
        LOG.error(
            "HTTPSConnectionPool(host='api.exmo.com', port=443): fetch failed (status=%s) %s",
            status,
            url,
        )
        return pd.DataFrame()

    data = payload.get("candles") or []
    if not isinstance(data, list) or not data:
        LOG.warning("[ohlc] empty payload")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    # Возможные поля EXMO: {t,o,c,h,l,v}
    if "t" in df.columns:
        df.rename(
            columns={"t": "timestamp", "o": "open", "c": "close", "h": "high", "l": "low", "v": "volume"},
            inplace=True,
        )
    elif "time" in df.columns:  # fallback
        df.rename(columns={"time": "timestamp"}, inplace=True)

    # Приведение типов + нормализация единиц времени
    df["timestamp"] = _normalize_epoch_seconds(df["timestamp"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Sanity check + сортировка/очистка
    df, warns = sanity_check_ohlc(df)
    for w in warns:
        LOG.warning("[OHLC] %s", w)

    if df.empty:
        return df

    # Конвертация в datetime (уже в секундах)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------
# Индикаторы/сигналы/стратегии
# ---------------------------------------------------------------------
def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_adx(df: pd.DataFrame, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    plus_dm = (high.diff().clip(lower=0.0)).fillna(0.0)
    minus_dm = (-low.diff().clip(upper=0.0)).fillna(0.0)

    tr1 = (high - low).abs()
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).fillna(0.0)

    # Wilder smoothing через EWM(alpha = 1/length)
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()
    pdi = 100 * (plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr.replace(0, np.nan)).fillna(0.0)
    mdi = 100 * (minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr.replace(0, np.nan)).fillna(0.0)
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0.0)
    adx = dx.ewm(alpha=1 / length, adjust=False).mean()
    return adx, pdi, mdi


def _signals_ema_adx(
        df: pd.DataFrame,
        fast: int,
        slow: int,
        adx_len: int,
        on: float,
        off: float,
        require_di: bool,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    close = df["close"].astype(float)
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    adx, pdi, mdi = _compute_adx(df, adx_len)

    long_on = cast(pd.Series, (ema_fast > ema_slow) & (adx >= on))
    if require_di:
        long_on = cast(pd.Series, long_on & (pdi > mdi))
    long_off = cast(pd.Series, (ema_fast < ema_slow) | (adx <= off))
    return long_on, long_off, ema_fast, ema_slow, adx


def _build_trades_from_signals(
        df: pd.DataFrame,
        long_on: pd.Series,
        long_off: pd.Series,
        ema_fast: Optional[pd.Series] = None,
        ema_slow: Optional[pd.Series] = None,
        adx: Optional[pd.Series] = None,
) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """
    Восстановление сделок по сигналам. Одна позиция long, flip не используем.
    Возвращает (список сделок, np.ndarray pnl).
    """
    close = df["close"].astype(float).values
    ts = df["timestamp"].astype(int).values
    pos = False
    entry_px = 0.0
    entry_i = -1
    trades: List[Dict[str, Any]] = []

    for i in range(len(df)):
        if (not pos) and bool(long_on.iat[i]):
            pos = True
            entry_px = float(close[i])
            entry_i = i
            # фиксируем ts прямо из массива без локальной переменной
            e_ts = int(ts[i])
            reason = "ema_cross_up"
            if adx is not None and ema_fast is not None and ema_slow is not None:
                r: List[str] = []
                if ema_fast.iat[i] > ema_slow.iat[i]:
                    r.append("ema_fast>ema_slow")
                r.append(f"adx={float(adx.iat[i]):.2f}")
                reason = "+".join(r)
            trades.append(
                {
                    "side": "long",
                    "entry_px": entry_px,
                    "entry_ts": e_ts,
                    "entry_dt": datetime.fromtimestamp(e_ts, tz=timezone.utc).isoformat(),
                    "entry_reason": reason,
                }
            )
        elif pos and bool(long_off.iat[i]):
            exit_px = float(close[i])
            exit_ts = int(ts[i])
            pnl = float(exit_px - entry_px)
            bars_held = int(i - entry_i) if entry_i >= 0 else 0

            reason = "exit_signal"
            if ema_fast is not None and ema_slow is not None and adx is not None:
                if ema_fast.iat[i] < ema_slow.iat[i]:
                    reason = "ema_cross_down"
                elif adx.iat[i] <= adx.iat[max(i - 1, 0)] and adx.iat[i] < 20:
                    reason = "weak_trend"
                elif adx.iat[i] <= 0:
                    reason = "adx_off"

            # обновляем последнюю открытую сделку
            for j in range(len(trades) - 1, -1, -1):
                if "exit_px" not in trades[j]:
                    trades[j].update(
                        {
                            "exit_px": exit_px,
                            "exit_ts": exit_ts,
                            "exit_dt": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
                            "exit_reason": reason,
                            "pnl": pnl,
                            "bars_held": bars_held,
                        }
                    )
                    break
            pos = False
            entry_px = 0.0
            entry_i = -1

    # Закрытие в конце (бумажная фиксация)
    if pos:
        i = len(df) - 1
        exit_px = float(close[-1])
        exit_ts = int(ts[-1])
        pnl = float(exit_px - entry_px)
        bars_held = int(i - entry_i) if entry_i >= 0 else 0
        for j in range(len(trades) - 1, -1, -1):
            if "exit_px" not in trades[j]:
                trades[j].update(
                    {
                        "exit_px": exit_px,
                        "exit_ts": exit_ts,
                        "exit_dt": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
                        "exit_reason": "close_on_last_bar",
                        "pnl": pnl,
                        "bars_held": bars_held,
                    }
                )
                break

    pnls = np.asarray([t.get("pnl", 0.0) for t in trades if "pnl" in t], dtype=float)
    return trades, pnls


def _strategy_ema_adx(df: pd.DataFrame, **params) -> np.ndarray:
    trades, pnls = get_strategy("ema_adx")(df, **params)
    return pnls


def _strategy_ema_adx_trades(df: pd.DataFrame, **params):
    return get_strategy("ema_adx")(df, **params)


def _strategy_ema_adx_atr(df: pd.DataFrame, **params) -> np.ndarray:
    trades, pnls = get_strategy("ema_adx_atr")(df, **params)
    return pnls


def _strategy_ema_adx_atr_trades(df: pd.DataFrame, **params):
    return get_strategy("ema_adx_atr")(df, **params)


# ---------------------------------------------------------------------
# Утилиты печати/сплита
# ---------------------------------------------------------------------
def _print_selected(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        LOG.info("No rows selected.")
        return
    with pd.option_context("display.max_colwidth", 200):
        print(df.to_string(index=False))


def _split_df_into_windows(df: pd.DataFrame, windows: int) -> List[pd.DataFrame]:
    n = len(df)
    windows = max(1, int(windows))
    edges = np.linspace(0, n, windows + 1, dtype=int)
    parts: List[pd.DataFrame] = []
    for i in range(windows):
        a, b = edges[i], edges[i + 1]
        if a < b:
            parts.append(df.iloc[a:b].copy())
    return parts


def _make_observe_table(df: pd.DataFrame, *, fast: int, slow: int, adx_len: int, on: float, off: float,
                        require_di: bool) -> pd.DataFrame:
    """
    Возвращает компактную табличку последних баров с индикаторами и сигналами.
    Колонки: [dt, close, ema_fast, ema_slow, adx, pdi, mdi, on, off, crossover, adx_state, di_state]
    """
    # сигналы и EMA/ADX
    long_on, long_off, ema_f, ema_s, adx = ema_adx_signals(
        df, fast=fast, slow=slow, adx_len=adx_len, on=on, off=off, require_di=require_di
    )
    # pdi/mdi для информативности
    adx2, pdi, mdi = compute_adx(df, adx_len)

    out = pd.DataFrame({
        "dt": df["dt"].astype("datetime64[ns, UTC]") if "dt" in df.columns else pd.to_datetime(df["timestamp"],
                                                                                               unit="s", utc=True),
        "close": df["close"].astype(float),
        "ema_fast": ema_f.astype(float),
        "ema_slow": ema_s.astype(float),
        "adx": adx.astype(float),
        "pdi": pdi.astype(float),
        "mdi": mdi.astype(float),
        "on": long_on.astype(bool),
        "off": long_off.astype(bool),
    })

    # производные статусы
    cross_up = (out["ema_fast"] > out["ema_slow"]) & (out["ema_fast"].shift(1) <= out["ema_slow"].shift(1))
    cross_dn = (out["ema_fast"] < out["ema_slow"]) & (out["ema_fast"].shift(1) >= out["ema_slow"].shift(1))
    out["crossover"] = np.select([cross_up, cross_dn], ["up", "down"], default=".")
    out["adx_state"] = np.select([out["adx"] >= on, out["adx"] <= off], ["on", "off"], default="mid")
    out["di_state"] = np.select([out["pdi"] > out["mdi"], out["pdi"] < out["mdi"]], ["+DI>", "-DI>"], default="=")

    # чуть округлим для консоли
    num_cols = ["close", "ema_fast", "ema_slow", "adx", "pdi", "mdi"]
    out[num_cols] = out[num_cols].round(4)
    return out


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
            "fast": [8, 12, 14],
            "slow": [20, 26, 30],
            "adx_len": [14],
            "on": [22.0, 25.0],
            "off": [16.0, 18.0],
            "require_di": [True],
            "atr_len": [14],
            "sl_mult": [0.0, 1.5, 2.0],
            "tp_mult": [0.0, 3.0],
            "trail_mult": [0.0, 1.0, 1.5],
            "tp1_mult": [0.0, 2.0],
            "tp1_frac": [0.0, 0.5],
            "tp2_mult": [0.0, 3.0, 4.0],
        },
    }


def _iter_grid(params: Dict[str, List[Any]]) -> Iterable[Dict[str, Any]]:
    keys = list(params.keys())
    vals = [params[k] for k in keys]
    idxes = [range(len(v)) for v in vals]
    for pos in np.array(np.meshgrid(*idxes, indexing="ij")).T.reshape(-1, len(vals)):
        yield {keys[i]: vals[i][pos[i]] for i in range(len(keys))}


def _load_grid_file(src: str | None) -> Optional[Dict[str, Any]]:
    if not src:
        return None
    if src == "-" or src == "/dev/stdin":
        text = sys.stdin.read()
        return json.loads(text) if text.strip() else None
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


def _print_observe_table(df: pd.DataFrame, *, last_rows: int = 20) -> None:
    if df.empty:
        LOG.info("[observe] empty frame")
        return
    tail = df.tail(max(1, int(last_rows)))
    disp = tail.copy()
    for bcol in ("on", "off"):
        if bcol in disp.columns:
            disp[bcol] = disp[bcol].astype(int)
    LOG.info("\n%s", disp.to_string(index=False))


# ---------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------
def _rows_to_selected(rows: List[Dict[str, Any]], metric: str, top_n: int, min_trades: int) -> pd.DataFrame:
    selector = Selector(SelectorConfig(metric=metric, top_n=top_n, min_trades=min_trades))
    return selector.run(rows)


def _dump_tabular(args, pair: str, candles: str, cmd: str, selected_df: pd.DataFrame) -> None:
    entries: List[Dict[str, Any]] = []

    # schema — всегда
    schema_path = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, f"{cmd}_schema", "json")
    dump_schema(selected_df, schema_path)
    entries.append({"kind": "schema", "path": schema_path})

    if getattr(args, "schema_only", False):
        write_manifest(args.out_dir, args.out_prefix, pair, candles, entries, stem=f"{cmd}_manifest")
        return

    # csv
    if not getattr(args, "no_csv", False):
        csv_path = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, f"{cmd}", "csv")
        selected_df.to_csv(csv_path, index=False)
        entries.append({"kind": "csv", "path": csv_path})

    # jsonl
    if getattr(args, "jsonl", False):
        jsonl_path = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, f"{cmd}", "jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for _, r in selected_df.iterrows():
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        entries.append({"kind": "jsonl", "path": jsonl_path})

    # manifest для этой команды
    write_manifest(args.out_dir, args.out_prefix, pair, candles, entries, stem=f"{cmd}_manifest")


def _reorder_result_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Единый порядок колонок во всех командах."""
    preferred = [
        "strategy", "params",
        "size", "fees_bps", "slippage_bps",
        "n_trades", "win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar",
    ]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    return df.loc[:, cols]


def _run_sweep(args) -> int:
    LOG.info("Command: sweep")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_selected(pd.DataFrame())
        return 0

    strategies = ["ema_adx", "ema_adx_atr"] if args.strategies == "auto" else [
        s.strip() for s in args.strategies.split(",") if s.strip()
    ]

    cfg = ExecConfig(
        size=getattr(args, "size", 1.0),
        fees_bps=getattr(args, "fees_bps", 0.0),
        slippage_bps=getattr(args, "slippage_bps", 0.0),
    )

    rows: List[Dict[str, Any]] = []
    for name in strategies:
        if name == "ema_adx":
            params = {"fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True}
            trades, _ = _strategy_ema_adx_trades(df, **params)
        else:
            params = {
                "fast": 12, "slow": 21, "adx_len": 14, "on": 25.0, "off": 16.0, "require_di": True,
                "atr_len": 14,
                "sl_mult": getattr(args, "sl_mult", 0.0),
                "tp_mult": getattr(args, "tp_mult", 0.0),
                "trail_mult": getattr(args, "trail_mult", 0.0),
                "tp1_mult": getattr(args, "tp1_mult", 0.0),
                "tp1_frac": getattr(args, "tp1_frac", 0.0),
                "tp2_mult": getattr(args, "tp2_mult", 0.0),
            }

            trades, _ = _strategy_ema_adx_atr_trades(df, **params)

        trades = enrich_trades_with_costs(trades, cfg)
        pnls = pnls_from_trades(trades, use_net=True)
        met = _compute_metrics(pnls)
        rows.append({
            "strategy": name,
            "params": params,
            "size": cfg.size,
            "fees_bps": cfg.fees_bps,
            "slippage_bps": cfg.slippage_bps,
            **met
        })

    selected = _rows_to_selected(rows, args.metric, args.top_n, args.min_trades)
    selected = _reorder_result_columns(selected)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "sweep", selected)
    return 0


def _run_optimize(args) -> int:
    LOG.info("Command: optimize")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_selected(pd.DataFrame())
        return 0

    grid = _load_grid_file(args.grid_file) or _default_grid()
    g = grid.get(args.strategy)
    if g is None:
        raise ValueError(f"grid for strategy '{args.strategy}' is not provided")

    cfg = ExecConfig(
        size=getattr(args, "size", 1.0),
        fees_bps=getattr(args, "fees_bps", 0.0),
        slippage_bps=getattr(args, "slippage_bps", 0.0),
    )

    rows: List[Dict[str, Any]] = []
    for params in _iter_grid(g):
        if args.strategy == "ema_adx":
            trades, _ = _strategy_ema_adx_trades(df, **params)
        else:
            trades, _ = _strategy_ema_adx_atr_trades(df, **params)
        trades = enrich_trades_with_costs(trades, cfg)
        pnls = pnls_from_trades(trades, use_net=True)
        met = _compute_metrics(pnls)
        rows.append({
            "strategy": args.strategy,
            "params": params,
            "size": cfg.size,
            "fees_bps": cfg.fees_bps,
            "slippage_bps": cfg.slippage_bps,
            **met
        })

    selected = _rows_to_selected(rows, args.metric, args.top_n, args.min_trades)
    selected = _reorder_result_columns(selected)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "optimize", selected)
    return 0


def _run_robustness(args) -> int:
    LOG.info("Command: robustness")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        _print_selected(pd.DataFrame())
        return 0

    windows = max(int(args.rb_windows), 1)
    splits = _split_df_into_windows(df, windows)

    strat = args.strategy
    base_params: Dict[str, Any] = {
        "fast": args.ema_fast,
        "slow": args.ema_slow,
        "adx_len": args.adx_len,
        "on": args.adx_on,
        "off": args.adx_off,
        "require_di": bool(args.require_di),
    }
    if strat == "ema_adx_atr":
        base_params["atr_len"] = args.atr_len
        base_params["sl_mult"] = getattr(args, "sl_mult", 0.0)
        base_params["tp_mult"] = getattr(args, "tp_mult", 0.0)
        base_params["trail_mult"] = getattr(args, "trail_mult", 0.0)

    cfg = ExecConfig(
        size=getattr(args, "size", 1.0),
        fees_bps=getattr(args, "fees_bps", 0.0),
        slippage_bps=getattr(args, "slippage_bps", 0.0),
    )

    all_pnls: List[float] = []
    for win in splits:
        if win.empty:
            continue
        if strat == "ema_adx":
            trades, _ = _strategy_ema_adx_trades(win, **base_params)
        else:
            trades, _ = _strategy_ema_adx_atr_trades(win, **base_params)
        trades = enrich_trades_with_costs(trades, cfg)
        pnls_win = pnls_from_trades(trades, use_net=True)
        all_pnls.extend(list(pnls_win))

    met = _compute_metrics(np.asarray(all_pnls, dtype=float))
    row = {
        "strategy": strat,
        "params": {**base_params, **({"atr_len": 14, "atr_mult": 0.0} if strat == "ema_adx" else {})},
        "size": cfg.size,
        "fees_bps": cfg.fees_bps,
        "slippage_bps": cfg.slippage_bps,
        **met
    }
    selected = _rows_to_selected([row], "sharpe", 1, args.min_trades)
    selected = _reorder_result_columns(selected)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "robustness", selected)
    return 0


def _run_walk_forward(args) -> int:
    LOG.info("Command: walk-forward")
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.warning("No data for walk-forward.")
        return 0

    folds = int(args.wf_folds)
    train_frac = float(args.wf_train_frac)
    if not (0.1 <= train_frac < 1.0):
        train_frac = 0.7

    parts = _split_df_into_windows(df, folds)
    grid = _load_grid_file(args.grid_file) or _default_grid()
    grid_for = grid.get(args.strategy)
    if grid_for is None:
        raise ValueError(f"grid for strategy '{args.strategy}' is not provided")

    cfg = ExecConfig(
        size=getattr(args, "size", 1.0),
        fees_bps=getattr(args, "fees_bps", 0.0),
        slippage_bps=getattr(args, "slippage_bps", 0.0),
    )

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

        # поиск лучших параметров на train
        cand_rows: List[Dict[str, Any]] = []
        for params in _iter_grid(grid_for):
            if args.strategy == "ema_adx":
                trades_tr, _ = _strategy_ema_adx_trades(train, **params)
            else:
                trades_tr, _ = _strategy_ema_adx_atr_trades(train, **params)
            trades_tr = enrich_trades_with_costs(trades_tr, cfg)
            pnls_tr = pnls_from_trades(trades_tr, use_net=True)
            met = _compute_metrics(pnls_tr)
            cand_rows.append({
                "strategy": args.strategy,
                "params": params,
                "size": cfg.size,
                "fees_bps": cfg.fees_bps,
                "slippage_bps": cfg.slippage_bps,
                **met
            })

        selected_train = _rows_to_selected(cand_rows, args.metric, 1, args.min_trades)
        if selected_train.empty:
            continue
        best_params = selected_train.iloc[0]["params"]
        if isinstance(best_params, str):
            best_params = json.loads(best_params)

        # валидация на valid
        if args.strategy == "ema_adx":
            trades_v, _ = _strategy_ema_adx_trades(valid, **best_params)
        else:
            trades_v, _ = _strategy_ema_adx_atr_trades(valid, **best_params)
        trades_v = enrich_trades_with_costs(trades_v, cfg)
        pnls_valid = pnls_from_trades(trades_v, use_net=True)
        all_valid_pnls.extend(list(pnls_valid))

    if not all_valid_pnls:
        LOG.warning("All folds filtered by --min-trades or no best params found.")
        return 0

    met = _compute_metrics(np.asarray(all_valid_pnls, dtype=float))
    out = {
        "strategy": args.strategy,
        "params": f"<wf best per fold from {folds} folds>",
        "size": cfg.size,
        "fees_bps": cfg.fees_bps,
        "slippage_bps": cfg.slippage_bps,
        **met,
    }
    selected = _rows_to_selected([out], args.metric, 1, args.min_trades)
    selected = _reorder_result_columns(selected)
    _print_selected(selected)
    _dump_tabular(args, args.pair, args.candles, "walk-forward", selected)
    return 0


def _run_live_observe(args) -> int:
    """
    Живое наблюдение: печатаем компактную табличку индикаторов,
    детектим события ENTER/EXIT и при --summary-alert шлём краткие алёрты.
    На события сохраняем JSON-артефакт observe_event.
    """
    LOG.info("[live] observe %s %s strategy=ema_adx", args.pair, args.candles)

    # параметры наблюдения берём из ema_adx
    base_params: Dict[str, Any] = {
        "fast": args.ema_fast,
        "slow": args.ema_slow,
        "adx_len": args.adx_len,
        "on": args.adx_on,
        "off": args.adx_off,
        "require_di": bool(args.require_di),
    }

    # состояние позиции в рамках observe (виртуально)
    pos = False
    last_bar_ts: int | None = None

    poll_sec = max(1, int(getattr(args, "poll_sec", 10)))
    LOG.info("[observe] poll every %ss; summary_alert=%s", poll_sec, bool(getattr(args, "summary_alert", False)))

    try:
        while True:
            df = _fetch_exmo_ohlc(args, args.pair, args.candles)
            if df.empty:
                LOG.warning("[observe] no data")
                time.sleep(poll_sec)
                continue

            tab = _make_observe_table(
                df,
                fast=base_params["fast"],
                slow=base_params["slow"],
                adx_len=base_params["adx_len"],
                on=base_params["on"],
                off=base_params["off"],
                require_di=base_params["require_di"],
            )

            # печать таблицы последних строк
            _print_observe_table(tab, last_rows=int(getattr(args, "observe_rows", 20)))

            # анализ последнего бара
            r = tab.iloc[-1]
            now_ts = int(df["timestamp"].iloc[-1])
            on_sig = bool(r["on"])
            off_sig = bool(r["off"])

            event: str | None = None
            if not pos and on_sig:
                pos = True
                event = "ENTER"
            elif pos and off_sig:
                pos = False
                event = "EXIT"

            # алёрт и артефакт только если новый бар/сигнал
            if getattr(args, "summary_alert", False):
                # не спамим несколько раз на одном и том же баре без изменений
                if event is not None and (last_bar_ts is None or now_ts != last_bar_ts):
                    LOG.info(
                        "[observe] %s @ %s close=%.6f emaF=%.6f emaS=%.6f adx=%.2f (%s %s)",
                        event,
                        pd.to_datetime(now_ts, unit="s", utc=True).isoformat(),
                        float(r["close"]),
                        float(r["ema_fast"]),
                        float(r["ema_slow"]),
                        float(r["adx"]),
                        str(r["crossover"]),
                        str(r["di_state"]),
                    )
                    # сохраняем событие + опционально снапшот
                    entries: List[Dict[str, Any]] = []

                    evt = {
                        "event": event,
                        "pair": args.pair,
                        "candles": args.candles,
                        "params": base_params,
                        "bar": {
                            "timestamp": now_ts,
                            "dt": pd.to_datetime(now_ts, unit="s", utc=True).isoformat(),
                            "close": float(r["close"]),
                            "ema_fast": float(r["ema_fast"]),
                            "ema_slow": float(r["ema_slow"]),
                            "adx": float(r["adx"]),
                            "pdi": float(r["pdi"]),
                            "mdi": float(r["mdi"]),
                            "crossover": str(r["crossover"]),
                            "adx_state": str(r["adx_state"]),
                            "di_state": str(r["di_state"]),
                            "on": bool(r["on"]),
                            "off": bool(r["off"]),
                        },
                    }
                    event_json = make_artifact_path(args.out_dir, args.out_prefix, args.pair, args.candles,
                                                    "observe_event", "json")
                    with open(event_json, "w", encoding="utf-8") as f:
                        f.write(json.dumps(evt, ensure_ascii=False, indent=2))
                    entries.append({"kind": "observe_event", "path": event_json})

                    if getattr(args, "observe_save_snapshots", False):
                        rows = max(1, int(getattr(args, "observe_rows", 20)))
                        snap_csv = make_artifact_path(args.out_dir, args.out_prefix, args.pair, args.candles,
                                                      "observe_snapshot", "csv")
                        tab.tail(rows).to_csv(snap_csv, index=False)
                        entries.append({"kind": "observe_snapshot", "path": snap_csv})

                    # manifest для события
                    write_manifest(args.out_dir, args.out_prefix, args.pair, args.candles, entries,
                                   stem="observe_manifest")

            last_bar_ts = now_ts
            time.sleep(poll_sec)
    except KeyboardInterrupt:
        LOG.info("[observe] stopped by user")
        return 0


def _run_live_paper(args) -> int:
    LOG.info("[live] paper %s %s strategy=%s", args.pair, args.candles, args.strategy)
    df = _fetch_exmo_ohlc(args, args.pair, args.candles)
    if df.empty:
        LOG.info("[paper] empty dataset")
        return 0

    # Параметры стратегии (общие)
    base_params: Dict[str, Any] = {
        "fast": args.ema_fast,
        "slow": args.ema_slow,
        "adx_len": args.adx_len,
        "on": args.adx_on,
        "off": args.adx_off,
        "require_di": bool(args.require_di),
    }
    # Специфика ema_adx_atr: ATR + SL/TP
    if args.strategy == "ema_adx_atr":
        base_params["atr_len"] = args.atr_len
        base_params["sl_mult"] = getattr(args, "sl_mult", 0.0)
        base_params["trail_mult"] = getattr(args, "trail_mult", 0.0)
        base_params["tp_mult"] = getattr(args, "tp_mult", 0.0)
        base_params["tp1_mult"] = getattr(args, "tp1_mult", 0.0)
        base_params["tp1_frac"] = getattr(args, "tp1_frac", 0.0)
        base_params["tp2_mult"] = getattr(args, "tp2_mult", 0.0)

    # Сделки + pnl
    if args.strategy == "ema_adx":
        trades, _ = _strategy_ema_adx_trades(df, **base_params)
    else:
        trades, _ = _strategy_ema_adx_atr_trades(df, **base_params)

    # Учёт исполнения (fees/slippage/size)
    cfg = ExecConfig(size=args.size, fees_bps=args.fees_bps, slippage_bps=args.slippage_bps)
    trades = enrich_trades_with_costs(trades, cfg)
    pnls = pnls_from_trades(trades, use_net=True)

    met = _compute_metrics(pnls)
    row = {
        "strategy": args.strategy,
        "params": dict(base_params),  # логируем фактические параметры
        "size": cfg.size,
        "fees_bps": cfg.fees_bps,
        "slippage_bps": cfg.slippage_bps,
        **met
    }
    LOG.info("[paper] trades=%s total_pnl=%.6f sharpe=%.3f", met["n_trades"], met["total_pnl"], met["sharpe"])

    if "profit_factor" in met:
        LOG.info(
            "[paper] extra: pf=%.3f maxDD%%=%.2f cagr%%=%.2f",
            float(met.get("profit_factor", 0.0)),
            float(met.get("max_drawdown_pct", 0.0)),
            float(met.get("cagr_pct", 0.0)),
        )

    _dump_live_artifacts(args, args.pair, args.candles, row, trades, pnls)
    return 0


# ---------------------------------------------------------------------
# Сохранение результатов
# ---------------------------------------------------------------------
def _dump_live_artifacts(
        args,
        pair: str,
        candles: str,
        metrics_row: Dict[str, Any],
        trades: List[Dict[str, Any]],
        pnls: np.ndarray,
) -> None:
    entries: List[Dict[str, Any]] = []

    # trades_schema.json — всегда
    trades_schema_json = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, "trades_schema", "json")
    schema = build_trades_schema(trades)
    with open(trades_schema_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(schema, ensure_ascii=False, indent=2))
    entries.append({"kind": "trades_schema", "path": trades_schema_json})

    # trades_summary.json — всегда
    summary = summarize_trades(trades)
    trades_summary_json = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, "trades_summary", "json")
    with open(trades_summary_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False, indent=2))
    entries.append({"kind": "trades_summary", "path": trades_summary_json})

    # печать в консоль (опция)
    if getattr(args, "print_trade_summary", False):
        LOG.info(
            "[paper] summary: closed=%s win_rate=%.2f%% pf=%.3f avg_pnl=%.6f",
            summary.get("closed_trades", 0),
            100.0 * float(summary.get("win_rate", 0.0)),
            float(summary.get("profit_factor", 0.0)),
            float(summary.get("avg_pnl", 0.0)),
        )

    if getattr(args, "schema_only", False):
        write_manifest(args.out_dir, args.out_prefix, pair, candles, entries, stem="paper_manifest")
        return

    # trades.json
    trades_json = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, "trades", "json")
    with open(trades_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(trades, ensure_ascii=False, indent=2))
    entries.append({"kind": "trades_json", "path": trades_json})

    # equity.csv (если не отключён CSV)
    if not getattr(args, "no_csv", False):
        equity_csv = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, "equity", "csv")
        equity = np.cumsum(pnls) if pnls.size else np.asarray([], dtype=float)
        pd.DataFrame({"equity": equity}).to_csv(equity_csv, index=False)
        entries.append({"kind": "equity_csv", "path": equity_csv})

    # metrics.json
    metrics_json = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, "metrics", "json")
    with open(metrics_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(metrics_row, ensure_ascii=False, indent=2))
    entries.append({"kind": "metrics_json", "path": metrics_json})

    # trades.jsonl (опционально)
    if getattr(args, "jsonl", False):
        trades_jsonl = make_artifact_path(args.out_dir, args.out_prefix, pair, candles, "trades", "jsonl")
        with open(trades_jsonl, "w", encoding="utf-8") as f:
            for t in trades:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        entries.append({"kind": "trades_jsonl", "path": trades_jsonl})

    # manifest для paper-сеанса
    write_manifest(args.out_dir, args.out_prefix, pair, candles, entries, stem="paper_manifest")


# ---------------------------------------------------------------------
# Аргументы CLI
# ---------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradinng-bot", description="EXMO research & live CLI")

    # === Глобальные ===
    p.add_argument("--pair", type=str, default="DOGE_EUR")
    p.add_argument("--candles", type=str, default="5m:2000")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--out-dir", type=str, default="out/data")
    p.add_argument("--out-prefix", type=str, default="")
    p.add_argument("--jsonl", action="store_true")
    p.add_argument("--print-trade-summary", action="store_true", help="Print trades summary to console (paper mode)")
    p.add_argument("--tp1-mult", type=float, default=0.0, help="ATR multiplier for partial TP1 (0 disables)")
    p.add_argument("--tp1-frac", type=float, default=0.0, help="Fraction to close at TP1 (0..1)")
    p.add_argument("--tp2-mult", type=float, default=0.0, help="ATR multiplier for TP2 (0 disables)")

    # HTTP
    p.add_argument("--http-retries", type=int, default=3)
    p.add_argument("--http-backoff", type=float, default=1.0)
    p.add_argument("--http-timeout", type=float, default=15.0)

    # Execution
    p.add_argument("--fees-bps", type=float, default=0.0)
    p.add_argument("--slippage-bps", type=float, default=0.0)
    p.add_argument("--size", type=float, default=1.0)

    # ATR SL/TP/Trailing (глобально)
    p.add_argument("--sl-mult", type=float, default=0.0, help="ATR multiplier for stop-loss (0 disables)")
    p.add_argument("--tp-mult", type=float, default=0.0, help="ATR multiplier for take-profit (0 disables)")
    p.add_argument("--trail-mult", type=float, default=0.0, help="ATR multiplier for trailing stop (0 disables)")

    # Артефакты
    p.add_argument("--schema-only", action="store_true", help="Write only *_schema.json artifacts")
    p.add_argument("--no-csv", action="store_true", help="Skip CSV artifacts")

    sub = p.add_subparsers(dest="cmd", required=True)

    # sweep
    sp = sub.add_parser("sweep", help="Quick strategies sweep")
    sp.add_argument("--strategies", type=str, default="auto")
    sp.add_argument("--metric", type=str, default="sharpe")
    sp.add_argument("--top-n", type=int, default=3)
    sp.add_argument("--min-trades", type=int, default=1)
    sp.set_defaults(_handler=_run_sweep)

    # optimize
    op = sub.add_parser("optimize", help="Grid search params")
    op.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    op.add_argument("--metric", type=str, default="sharpe")
    op.add_argument("--top-n", type=int, dest="top_n", default=10)
    op.add_argument("--min-trades", type=int, dest="min_trades", default=3)
    op.add_argument("--grid-file", type=str, default="")
    op.set_defaults(_handler=_run_optimize)

    # robustness
    rb = sub.add_parser("robustness", help="Robustness by windows")
    rb.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    rb.add_argument("--rb-windows", type=int, default=6)
    rb.add_argument("--min-trades", type=int, default=1)
    rb.add_argument("--ema-fast", type=int, dest="ema_fast", default=12)
    rb.add_argument("--ema-slow", type=int, dest="ema_slow", default=21)
    rb.add_argument("--adx-len", type=int, dest="adx_len", default=14)
    rb.add_argument("--adx-on", type=float, dest="adx_on", default=25.0)
    rb.add_argument("--adx-off", type=float, dest="adx_off", default=16.0)
    rb.add_argument("--require-di", action="store_true", dest="require_di")
    rb.add_argument("--atr-len", type=int, dest="atr_len", default=14)
    rb.set_defaults(_handler=_run_robustness)

    # walk-forward
    wf = sub.add_parser("walk-forward", help="Walk-forward validation")
    wf.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    wf.add_argument("--metric", type=str, default="sharpe")
    wf.add_argument("--wf-folds", type=int, dest="wf_folds", default=4)
    wf.add_argument("--wf-train-frac", type=float, dest="wf_train_frac", default=0.7)
    wf.add_argument("--min-trades", type=int, default=1)
    wf.add_argument("--grid-file", type=str, default="")
    wf.set_defaults(_handler=_run_walk_forward)

    # trade-live
    tl = sub.add_parser("trade-live", help="Live modes")
    tl.add_argument("--mode", type=str, required=True, choices=["observe", "paper"])
    tl.add_argument("--strategy", type=str, required=True, choices=["ema_adx", "ema_adx_atr"])
    tl.add_argument("--ema-fast", type=int, dest="ema_fast", default=12)
    tl.add_argument("--ema-slow", type=int, dest="ema_slow", default=21)
    tl.add_argument("--adx-len", type=int, dest="adx_len", default=14)
    tl.add_argument("--adx-on", type=float, dest="adx_on", default=25.0)
    tl.add_argument("--adx-off", type=float, dest="adx_off", default=16.0)
    tl.add_argument("--require-di", action="store_true", dest="require_di")
    tl.add_argument("--atr-len", type=int, dest="atr_len", default=14)
    tl.add_argument("--poll-sec", type=int, default=10)
    tl.add_argument("--summary-alert", action="store_true")
    tl.add_argument("--observe-rows", type=int, default=20, help="How many recent rows to print in observe table")
    tl.add_argument("--observe-save-snapshots", action="store_true",
                    help="Save table snapshot CSV on ENTER/EXIT events")
    tl.set_defaults(_handler=_dispatch_live)

    return p


def _dispatch_live(a) -> int:
    return _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a)


def _dispatch_command(args) -> int:
    handler = getattr(args, "_handler")
    return handler(args)


def _run_cli(argv: List[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(bool(getattr(args, "debug", False)))
    _ensure_out_dir(args)
    return _dispatch_command(args)


def main() -> None:
    sys.exit(_run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
