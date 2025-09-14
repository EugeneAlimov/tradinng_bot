# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


# ---------- утилиты времени/правил ----------

def _normalize_rule(rule: Optional[str]) -> Optional[str]:
    if not rule:
        return None
    r = rule.strip().lower()
    if r.endswith("m") and not r.endswith("min"):
        try:
            n = int(r[:-1])
            return f"{n}min"
        except ValueError:
            pass
    return r


def _to_utc_index(ser: pd.Series) -> pd.DatetimeIndex:
    dt = pd.to_datetime(ser, utc=True, errors="coerce")
    return pd.DatetimeIndex(dt).sort_values()


# ---------- загрузка источников ----------

def _load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).set_index(
            pd.DatetimeIndex([], name="time")
        )
    df = pd.read_csv(path)
    ts_col = None
    for c in ["timestamp", "time", "ts", "date"]:
        if c in df.columns:
            ts_col = c
            break
    if ts_col is None:
        ts_col = df.columns[0]
    idx = _to_utc_index(df[ts_col])
    cols = ["open", "high", "low", "close", "volume"]
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    out = df[cols].copy()
    out.index = idx
    out.index.name = "time"
    out = out.sort_index()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"]).fillna(0.0)
    return out


def _resample_ohlc_pandas(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    if not rule or df.empty:
        return df
    rule = _normalize_rule(rule)
    o = df["open"].resample(rule, origin="start_day").first()
    h = df["high"].resample(rule, origin="start_day").max()
    l = df["low"].resample(rule, origin="start_day").min()
    c = df["close"].resample(rule, origin="start_day").last()
    v = df["volume"].resample(rule, origin="start_day").sum()
    out = pd.concat({"open": o, "high": h, "low": l, "close": c, "volume": v}, axis=1)
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out


def _resample_ohlc(df: pd.DataFrame, rule: Optional[str], prefer_duck: bool = False) -> pd.DataFrame:
    if not rule or df.empty:
        return df
    if prefer_duck:
        try:
            from src.storage.duckops import resample_via_duckdb
            return resample_via_duckdb(df, _normalize_rule(rule) or "1min")
        except Exception as e:
            print(f"[trade-live] duckdb resample disabled: {e}", file=sys.stderr)
    return _resample_ohlc_pandas(df, rule)


# ---------- стратегия/реестр ----------

def _parse_params_env(s: Optional[str]) -> Dict[str, Any]:
    """
    Разбор TB_STRATEGY_PARAMS="k=v, k2=v2" -> dict
    """
    if not s:
        return {}
    out: Dict[str, Any] = {}
    for part in s.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        # попытка конверсии типов
        if v.lower() in ("true", "false"):
            out[k] = (v.lower() == "true")
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def _resolve_strategy(name: Optional[str]):
    from src.strategies.runtime_registry import registry
    return registry.resolve(name)


# ---------- Args-контейнер ----------

@dataclass
class Args:
    mode: Optional[str] = None
    strategy: Optional[str] = None
    exmo_pair: Optional[str] = None
    exmo_candles: Optional[str] = None
    resample: Optional[str] = None
    poll_sec: int = 10
    data: Optional[str] = None
    demo: bool = False
    bars: int = 720
    once: bool = False
    stdout_json: bool = False
    pure_json: bool = False
    out_json: Optional[str] = None
    signal_json: bool = False
    quiet: bool = False


def _should_quiet_json(args: Args | Any) -> bool:
    return bool(getattr(args, "pure_json", False) or getattr(args, "quiet", False)
                or getattr(args, "stdout_json", False) or getattr(args, "signal_json", False))


# ---------- загрузка данных ----------

def _load_source(args: Args | Any) -> tuple[pd.DataFrame, str, str]:
    prefer_duck = os.getenv("TB_USE_DUCKDB", "0") == "1"
    resample_rule = getattr(args, "resample", None)

    if getattr(args, "data", None):
        df = _load_csv(getattr(args, "data"))
        df = _resample_ohlc(df, resample_rule, prefer_duck=prefer_duck)
        return df, (getattr(args, "exmo_pair", None) or "CSV"), (_normalize_rule(resample_rule) or "1min")

    if getattr(args, "exmo_pair", None) and getattr(args, "exmo_candles", None):
        try:
            from src.backtest.compat import fetch_exmo_candles_cached
            pair, span = getattr(args, "exmo_pair"), getattr(args, "exmo_candles")
            df = fetch_exmo_candles_cached(pair, span)
            df = _resample_ohlc(df, resample_rule, prefer_duck=prefer_duck)
            return df, pair, (_normalize_rule(resample_rule) or "1min")
        except Exception:
            pass

    # demo
    bars = int(getattr(args, "bars", 720) or 720)
    idx = pd.date_range(end=pd.Timestamp.utcnow().floor("min"), periods=bars, freq="1min", tz="UTC")
    rng = np.random.default_rng(42)
    rets = rng.normal(0, 0.0015, size=len(idx))
    price = 100 * np.exp(np.cumsum(rets))
    close = pd.Series(price, index=idx)
    spread = np.abs(rng.normal(0, 0.0025, size=len(idx))) * close.values
    high = close + spread
    low = close - spread
    open_ = close.shift(1).fillna(close.iloc[0])
    vol = rng.integers(50, 500, size=len(idx)).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
    df = _resample_ohlc(df, resample_rule, prefer_duck=prefer_duck)
    return df, "DEMO", (_normalize_rule(resample_rule) or "1min")


# ---------- агрегаты/статистика ----------

def _summary_stats(close: pd.Series, lookback: int = 500) -> Dict[str, float]:
    if len(close) == 0:
        return {"trades": 0.0, "exposure_pct": 0.0, "pnl_pct": 0.0, "max_dd_pct": 0.0, "sharpe": 0.0}
    s = close.tail(lookback)
    ret = s.pct_change().fillna(0.0)
    pnl = (s.iat[-1] / s.iat[0] - 1.0) * 100.0 if len(s) > 1 else 0.0
    trades = int((ret.abs() > ret.std() * 1.5).sum())
    exposure = min(100.0, trades / max(1, len(s)) * 100.0 * 2)
    max_dd = (s / s.cummax() - 1.0).min() * 100.0
    sharpe = (ret.mean() / (ret.std() + 1e-9)) * np.sqrt(252 * 24 * 12)
    return {
        "trades": float(trades),
        "exposure_pct": float(round(exposure, 1)),
        "pnl_pct": float(pnl),
        "max_dd_pct": float(max_dd),
        "sharpe": float(sharpe),
    }


# ---------- стор/паркет ----------

def _maybe_open_store():
    url = os.getenv("TB_STORE_URL")
    if not url:
        return None
    try:
        from src.storage.db import open_store
        return open_store(url)
    except Exception as e:
        print(f"[trade-live] storage disabled: {e}", file=sys.stderr)
        return None


# ---------- run/main/handler ----------

def run(args: Args | Any) -> int:
    header = (
        f"[trade-live] mode={getattr(args, 'mode', None)} strategy={getattr(args, 'strategy', None)} "
        f"pair={getattr(args, 'exmo_pair', None)} span={getattr(args, 'exmo_candles', None)} "
        f"resample={getattr(args, 'resample', None)} poll_sec={getattr(args, 'poll_sec', 10)} "
        f"data={getattr(args, 'data', None)} demo={getattr(args, 'demo', False)} bars={getattr(args, 'bars', 720)}"
    )
    if not _should_quiet_json(args):
        print(header)

    df, symbol, timeframe = _load_source(args)
    if df.empty:
        if not _should_quiet_json(args):
            print(
                "[trade-live] Пустые данные. Варианты:\n"
                "  • --demo [--bars N] — сгенерировать синтетические свечи\n"
                "  • --data /путь/к/ohlcv.csv — загрузить локальный CSV\n"
                "  • --exmo-pair ... --exmo-candles ... — если кэш EXMO уже прогрет"
            )
        return 0

    # выбор стратегии
    spec = _resolve_strategy(getattr(args, "strategy", None))
    params_env = _parse_params_env(os.getenv("TB_STRATEGY_PARAMS"))
    params = {**spec.defaults, **params_env}

    side, extras = spec.fn(df, params)
    last_ts = df.index[-1]
    last_close = float(df["close"].iat[-1])
    summary = _summary_stats(df["close"], lookback=500)

    # parquet sink (опц.)
    parquet_dir = os.getenv("TB_PARQUET_DIR")
    if parquet_dir:
        try:
            from src.storage.duckops import write_parquet_partitioned
            write_parquet_partitioned(df, parquet_dir, symbol=symbol, timeframe=timeframe)
        except Exception as e:
            print(f"[trade-live] parquet disabled: {e}", file=sys.stderr)

    # вывод сигнала
    if getattr(args, "signal_json", False):
        payload = {
            "time": last_ts.isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": spec.name,
            "price": last_close,
            "side": side,
            **extras,
            **summary,
            "lookback": 500,
        }
        text = json.dumps(payload, ensure_ascii=False)
        print(text)
        if getattr(args, "out_json", None):
            os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
            with open(args.out_json, "a", encoding="utf-8") as f:
                f.write(text + "\n")

        store = _maybe_open_store()
        if store and os.getenv("TB_WRITE_SIGNALS", "1") == "1":
            run_id = os.getenv("TB_RUN_ID") or pd.Timestamp.utcnow().strftime("run-%Y%m%d-%H%M%S")
            to_db = {
                "time": last_ts,  # стор сам нормализует к ISO
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy": spec.name,
                "side": side,
                "price": last_close,
                "run_id": run_id,
                "payload": payload,
            }
            try:
                store.write_signal(to_db)
            except Exception as e:
                print(f"[trade-live] failed to write signal: {e}", file=sys.stderr)

        if store and os.getenv("TB_WRITE_CANDLES", "0") == "1":
            try:
                store.write_candles(df, symbol=symbol, timeframe=timeframe)
            except Exception as e:
                print(f"[trade-live] failed to write candles: {e}", file=sys.stderr)

    else:
        if not _should_quiet_json(args):
            extras_str = " ".join(f"{k}={v:.6f}" for k, v in extras.items() if isinstance(v, (int, float)))
            print(
                f"[trade-live] signal={side} time={last_ts.isoformat()} price={last_close:.6f} {extras_str}"
            )
            print(
                f"[trade-live] summary (lookback=500): trades={int(summary['trades'])} "
                f"exposure={summary['exposure_pct']:.1f}% pnl={summary['pnl_pct']:.2f}% "
                f"maxDD={summary['max_dd_pct']:.2f}% sharpe={summary['sharpe']:.2f}"
            )

    return 0


def main(args: Args | Any) -> int:
    return run(args)


def handler(args: Args | Any) -> int:
    return run(args)
