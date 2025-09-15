# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import re
import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Utilities: time handling (UTC everywhere)
# ---------------------------------------------------------------------


def _to_utc_dtindex(s: pd.Series) -> pd.DatetimeIndex:
    """Coerce a Series to tz-aware UTC DatetimeIndex (no NaT at tail)."""
    dt = pd.to_datetime(s, utc=True, errors="coerce")
    if not isinstance(dt, pd.Series):
        dt = pd.Series(dt)
    # drop NaT rows (keeps index aligned only if used before concat)
    mask = dt.notna()
    return pd.DatetimeIndex(dt[mask].values).tz_convert("UTC")


def _ensure_utc_ts(df: pd.DataFrame, tcol: str = "time") -> pd.DataFrame:
    """
    Ensure df[tcol] is tz-aware UTC; keep as column.
    Does not set index here; resampler will.
    """
    if tcol not in df.columns:
        raise ValueError(f"Timestamp column '{tcol}' not found in DataFrame")
    df = df.copy()
    df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    df = df[df[tcol].notna()]
    # normalize any non-UTC tz to UTC
    if getattr(df[tcol].dt, "tz", None) is None:
        df[tcol] = df[tcol].dt.tz_localize("UTC")
    else:
        df[tcol] = df[tcol].dt.tz_convert("UTC")
    return df


def _fmt_rfc3339_basic(dt: pd.Timestamp | datetime) -> str:
    """Format as YYYY-MM-DDTHH:MM:SS+0000 (no colon in offset)."""
    if isinstance(dt, pd.Timestamp):
        if dt.tzinfo is None:
            dt = dt.tz_localize("UTC")
        else:
            dt = dt.tz_convert("UTC")
        dt = dt.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _to_utc_naive_ts(obj: pd.Series | pd.DatetimeIndex) -> pd.Series | pd.DatetimeIndex:
    """
    Приводит Series/DatetimeIndex к UTC и делает их naive (без tz).
    Корректно обрабатывает и tz-aware, и tz-naive.
    """
    if isinstance(obj, pd.Series):
        s = pd.to_datetime(obj, errors="coerce", utc=False)
        tz = getattr(s.dt, "tz", None)
        if tz is None:
            s = s.dt.tz_localize("UTC")
        else:
            s = s.dt.tz_convert("UTC")
        return s.dt.tz_localize(None)
    elif isinstance(obj, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(obj)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        return idx.tz_localize(None)
    else:
        # на всякий случай — приведём к Series и обработаем как Series
        s = pd.to_datetime(pd.Series(obj), errors="coerce", utc=True)
        return s.dt.tz_localize(None)


# ---------------------------------------------------------------------
# Demo data and CSV loader
# ---------------------------------------------------------------------


def _demo_ohlcv(n_minutes: int = 600, start: Optional[datetime] = None) -> pd.DataFrame:
    """
    Generate a simple 1m OHLCV demo series.
    """
    if start is None:
        start = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
            minutes=n_minutes
        )
    idx = pd.date_range(start, periods=n_minutes, freq="1min", tz="UTC")
    # random walk for close; derived ohlc; volume random-ish
    rng = np.random.default_rng(42)
    steps = rng.normal(0, 0.3, size=n_minutes).cumsum() + 100.0
    close = steps
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.random(n_minutes) * 0.5
    low = np.minimum(open_, close) - rng.random(n_minutes) * 0.5
    vol = rng.integers(80, 150, size=n_minutes).astype(float)

    df = pd.DataFrame(
        {
            "time": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )
    return df


def _read_csv_ohlcv(path: str, tcol: str = "time") -> pd.DataFrame:
    """
    Minimal CSV reader: expects columns time, open, high, low, close[, volume].
    """
    df = pd.read_csv(path)
    if tcol not in df.columns:
        # try a couple of common names
        for cand in ("timestamp", "datetime", "date"):
            if cand in df.columns:
                tcol = cand
                break
    # normalize column names (lower)
    df.columns = [c.strip().lower() for c in df.columns]
    if tcol not in df.columns:
        raise ValueError(f"Timestamp column '{tcol}' not present in CSV '{path}'")
    # coerce numeric columns if present
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = _ensure_utc_ts(df, tcol=tcol)
    return df


# ---------------------------------------------------------------------
# Resampling with DuckDB fallback
# ---------------------------------------------------------------------


def _parse_rule_to_duck_interval(rule: str) -> str:
    """
    Convert pandas-like rule (e.g., '5min', '1h') to DuckDB INTERVAL string.
    Supports: s, sec, second(s); min; h; d.
    """
    r = rule.strip().lower()
    # quick map of suffixes
    mapping = {
        ("s", "sec", "secs", "second", "seconds"): "second",
        ("t", "min", "mins", "minute", "minutes"): "minute",
        ("h", "hour", "hours"): "hour",
        ("d", "day", "days"): "day",
    }
    num = ""
    unit = ""
    for ch in r:
        if ch.isdigit():
            num += ch
        else:
            unit += ch
    num = num or "1"
    unit = unit.strip()
    unit_std = None
    for keys, val in mapping.items():
        if unit in keys:
            unit_std = val
            break
    if unit_std is None:
        # fallback: assume minutes if unspecified
        unit_std = "minute"
    return f"{int(num)} {unit_std}"


def _resample_ohlc_pandas(
        df: pd.DataFrame, rule: str, tcol: str = "time"
) -> pd.DataFrame:
    """
    Pandas resample to OHLCV with UTC-aware DatetimeIndex.
    """
    df = df.copy()
    df = _ensure_utc_ts(df, tcol=tcol)
    df = df.set_index(tcol).sort_index()
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(rule).agg(agg).dropna(how="all")
    # ensure tz-aware UTC
    out.index = out.index.tz_convert("UTC")
    out.index.name = "time"
    return out


def _rule_to_seconds(rule: str) -> int:
    r = rule.strip().lower()
    num = "".join(ch for ch in r if ch.isdigit()) or "1"
    unit = "".join(ch for ch in r if ch.isalpha()) or "min"
    n = int(num)
    if unit in ("s", "sec", "secs", "second", "seconds"):
        return n
    if unit in ("m", "t", "min", "mins", "minute", "minutes"):
        return n * 60
    if unit in ("h", "hour", "hours"):
        return n * 3600
    if unit in ("d", "day", "days"):
        return n * 86400
    return n * 60  # дефолт: минуты


def _resample_ohlc_duckdb(df: pd.DataFrame, rule: str, tcol: str = "time") -> pd.DataFrame:
    import duckdb
    interval = _parse_rule_to_duck_interval(rule)
    bin_sec = _rule_to_seconds(rule)

    con = duckdb.connect()
    try:
        con.register("t", df.copy())
        try:
            q1 = f"""
            SELECT
                DATE_BIN(INTERVAL '{interval}', {tcol}) AS time,
                FIRST(open) AS open,
                MAX(high)   AS high,
                MIN(low)    AS low,
                LAST(close) AS close,
                SUM(COALESCE(volume, 0)) AS volume
            FROM t
            GROUP BY 1
            ORDER BY 1
            """
            res = con.sql(q1).df()
        except Exception:
            q2 = f"""
            SELECT
                to_timestamp(floor(epoch({tcol})/{bin_sec})*{bin_sec}) AS time,
                FIRST(open) AS open,
                MAX(high)   AS high,
                MIN(low)    AS low,
                LAST(close) AS close,
                SUM(COALESCE(volume, 0)) AS volume
            FROM t
            GROUP BY 1
            ORDER BY 1
            """
            res = con.sql(q2).df()
    finally:
        con.close()

    res["time"] = pd.to_datetime(res["time"], utc=True)
    res = res.set_index("time").sort_index()
    res.index = res.index.tz_convert("UTC")
    return res


def _rule_to_duck_interval(rule: str) -> str:
    s = rule.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d+)(s|sec|second|m|min|minute|h|hour|d|day)", s)
    if not m:
        raise ValueError(f"Unsupported resample rule for DuckDB: {rule!r}")
    n = int(m.group(1))
    unit = m.group(2)
    unit_map = {
        "s": "SECOND", "sec": "SECOND", "second": "SECOND",
        "m": "MINUTE", "min": "MINUTE", "minute": "MINUTE",
        "h": "HOUR", "hour": "HOUR",
        "d": "DAY", "day": "DAY",
    }
    return f"INTERVAL {n} {unit_map[unit]}"


def _resample_ohlc_with_duckdb_fallback(
        df: pd.DataFrame,
        rule: str,
        tcol: str = "time",
        use_duckdb: bool = True,
) -> pd.DataFrame:
    """
    Ресэмплинг OHLCV: DuckDB (date_bin -> time_bucket) -> pandas.resample().
    На вход можно давать что угодно по времени (столбец или индекс, tz/без tz).
    Везде нормализуем к UTC.
    """
    # подготовим временную шкалу
    if tcol in df.columns:
        ts_naive = _to_utc_naive_ts(df[tcol])
    else:
        ts_naive = _to_utc_naive_ts(df.index)

    work = df[["open", "high", "low", "close", "volume"]].copy()
    work.insert(0, "ts", ts_naive)

    if use_duckdb:
        try:
            import duckdb  # noqa: WPS433

            con = duckdb.connect()
            con.register("df", work)
            interval = _rule_to_duck_interval(rule)

            # 1) пробуем date_bin(...)
            sql_date_bin = f"""
                SELECT
                  bucket,
                  arg_min(open, ts)   AS open,
                  max(high)           AS high,
                  min(low)            AS low,
                  arg_max(close, ts)  AS close,
                  sum(volume)         AS volume
                FROM (
                  SELECT date_bin({interval}, ts, TIMESTAMP '1970-01-01') AS bucket,
                         ts, open, high, low, close, volume
                  FROM df
                )
                GROUP BY bucket
                ORDER BY bucket
            """
            try:
                out = con.execute(sql_date_bin).fetch_df()
            except Exception:
                # 2) если функции нет — пробуем time_bucket(...)
                sql_time_bucket = f"""
                    SELECT
                      bucket,
                      arg_min(open, ts)   AS open,
                      max(high)           AS high,
                      min(low)            AS low,
                      arg_max(close, ts)  AS close,
                      sum(volume)         AS volume
                    FROM (
                      SELECT time_bucket({interval}, ts) AS bucket,
                             ts, open, high, low, close, volume
                      FROM df
                    )
                    GROUP BY bucket
                    ORDER BY bucket
                """
                out = con.execute(sql_time_bucket).fetch_df()

            con.close()

            out.rename(columns={"bucket": tcol}, inplace=True)
            out[tcol] = pd.to_datetime(out[tcol], utc=True)
            out.set_index(tcol, inplace=True)
            return out

        except Exception as e:
            print(f"[duckops] DuckDB resample failed ({e}), fallback to pandas.resample()")

    # --- pandas fallback ---
    work.set_index("ts", inplace=True)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = (
        work
        .resample(rule, label="right", closed="right")
        .agg(agg)
        .dropna(how="all")
    )
    # делаем индекс tz-aware (UTC) и называем как tcol
    out.index = out.index.tz_localize("UTC")
    out.index.name = tcol
    return out


# ---------------------------------------------------------------------
# Signal calculation
# ---------------------------------------------------------------------


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """
    Simplified ADX (Wilder’s). Good enough for demo and decision gating.
    """
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = _atr(df, n=1)  # true range daily, then smoothed
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n).mean() / tr.replace(
        0, np.nan
    )
    minus_di = (
            100
            * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n).mean()
            / tr.replace(0, np.nan)
    )
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan) * 100
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return adx


def _parse_params_str(params: Optional[str]) -> Dict[str, float | int | str]:
    """
    Parse 'k1=v1,k2=v2' into dict with best-effort casting to int/float.
    """
    if not params:
        return {}
    out: Dict[str, float | int | str] = {}
    parts = [p.strip() for p in params.split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            continue
        k, v = [x.strip() for x in p.split("=", 1)]
        if v.isdigit():
            out[k] = int(v)
        else:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def _compute_signal(
        df_r: pd.DataFrame, strategy_name: str, params: Dict[str, float | int | str]
) -> Dict[str, float | str]:
    """
    Return dict with keys: side ('LONG'/'SHORT'/'FLAT'), price (float), and extras.
    """
    if df_r.empty:
        return {"side": "FLAT", "price": float("nan")}
    close = df_r["close"].astype(float)

    # Defaults
    fast = int(params.get("ema_fast", 12))
    slow = int(params.get("ema_slow", 26))

    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)

    side = "FLAT"
    if len(close) >= max(fast, slow) + 1:
        cross = np.sign(ema_fast - ema_slow)
        prev, curr = cross.iloc[-2], cross.iloc[-1]
        if curr > 0 and prev <= 0:
            side = "LONG"
        elif curr < 0 and prev >= 0:
            side = "SHORT"
        else:
            side = "FLAT"

    price = float(close.iloc[-1])

    out = {"side": side, "price": price, "ema_fast": float(ema_fast.iloc[-1]), "ema_slow": float(ema_slow.iloc[-1])}

    if strategy_name.lower() == "ema_adx_atr":
        n = int(params.get("window", 14))
        out["atr"] = float(_atr(df_r, n=n).iloc[-1])
        out["adx"] = float(_adx(df_r, n=n).iloc[-1])
    return out


# ---------------------------------------------------------------------
# Signal building + DB writers
# ---------------------------------------------------------------------


def _build_signal(
        df_resampled: pd.DataFrame,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        side: str,
        price: float,
        tcol: str = "time",
        extra: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    if df_resampled.empty:
        raise ValueError("df_resampled is empty; cannot build a signal")
    # ensure we have tz-aware UTC index
    if not isinstance(df_resampled.index, pd.DatetimeIndex):
        raise TypeError("df_resampled.index must be a DatetimeIndex")
    ts = df_resampled.index[-1]
    out = {
        "time": _fmt_rfc3339_basic(ts),
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": strategy_name,
        "price": float(price),
        "side": side,
        "run_id": os.environ.get("TB_RUN_ID"),
    }
    if extra:
        out.update(extra)
    return out


def _write_signal_if_enabled(signal: Dict[str, object]) -> None:
    if os.environ.get("TB_WRITE_SIGNALS", "0") not in ("1", "true", "True"):
        return
    url = os.environ.get("TB_STORE_URL")
    if not url:
        print("No TB_STORE_URL; skip signal write.", file=sys.stderr)
        return
    try:
        from src.storage import db  # local import
        db.write_signal(signal, url=url)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] write_signal failed: {e!s}", file=sys.stderr)


def _write_candles_if_enabled(
        df_r: pd.DataFrame, symbol: str, timeframe: str, tcol: str = "time"
) -> None:
    if os.environ.get("TB_WRITE_CANDLES", "0") not in ("1", "true", "True"):
        return
    url = os.environ.get("TB_STORE_URL")
    if not url:
        print("No TB_STORE_URL; skip candles write.", file=sys.stderr)
        return
    try:
        from src.storage import db  # local import

        out = df_r.reset_index()
        out.rename(columns={"index": tcol}, inplace=True)
        out[tcol] = pd.to_datetime(out[tcol], utc=True)
        # store as string in our unified format
        out[tcol] = out[tcol].map(_fmt_rfc3339_basic)
        cols = ["time", "open", "high", "low", "close"]
        if "volume" in out.columns:
            cols.append("volume")
        out = out[cols]
        db.write_candles(out, symbol=symbol, timeframe=timeframe, url=url)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] write_candles failed: {e!s}", file=sys.stderr)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tb trade-live",
        description="Live/demo signal generation with optional DB persistence.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--demo", action="store_true", help="Use synthetic demo 1m data")
    src.add_argument("--data", type=str, help="CSV with columns time, open, high, low, close[, volume]")

    p.add_argument("--bars", type=int, default=1440, help="Bars for demo 1m series")
    p.add_argument("--symbol", type=str, default="DEMO", help="Symbol label for output/DB")
    p.add_argument("--tcol", type=str, default="time", help="Timestamp column name")
    p.add_argument("--resample", type=str, default="5min", help="Target timeframe (e.g., 5min, 1h)")
    p.add_argument("--once", action="store_true", help="Run once and exit")

    p.add_argument("--strategy", type=str, default="ema_cross", help="Strategy name: ema_cross | ema_adx_atr")
    p.add_argument("--params", type=str, default=None, help="Extra params, e.g. 'ema_fast=12,ema_slow=26'")
    p.add_argument("--signal-json", action="store_true", help="Print the built signal as JSON")
    return p


def _once(args: argparse.Namespace) -> int:
    # 1) Load data
    if args.demo:
        df = _demo_ohlcv(args.bars)
    else:
        df = _read_csv_ohlcv(args.data, tcol=args.tcol)

    # 2) Normalize times & resample
    df = _ensure_utc_ts(df, tcol=args.tcol)
    use_duck = os.environ.get("TB_USE_DUCKDB", "1") in ("1", "true", "True")
    df_r = _resample_ohlc_with_duckdb_fallback(df, rule=args.resample, tcol=args.tcol, use_duckdb=use_duck)

    # 3) Compute signal
    params = _parse_params_str(args.params)
    sig_fields = _compute_signal(df_r, args.strategy, params)
    extra = {k: v for k, v in sig_fields.items() if k not in ("side", "price")}

    # 4) Build and print
    sig = _build_signal(
        df_resampled=df_r,
        symbol=args.symbol if args.data is None else args.symbol,
        timeframe=args.resample,
        strategy_name=args.strategy,
        side=sig_fields["side"],
        price=float(sig_fields["price"]),
        tcol=args.tcol,
        extra=extra,
    )

    if args.signal_json:
        print("[signal]", json.dumps(sig, ensure_ascii=False))

    # 5) Persist
    _write_signal_if_enabled(sig)
    _write_candles_if_enabled(df_r, symbol=args.symbol, timeframe=args.resample, tcol=args.tcol)
    return 0


def main(argv: Optional[Tuple[str, ...]] = None) -> int:
    """
    Entry point; compatible with app launcher which may call main(argv=...).
    """
    parser = build_parser()
    ns = parser.parse_args(list(argv) if argv is not None else None)
    if ns.once:
        return _once(ns)
    # For now, 'once' mode only; a streaming loop can be added later.
    # Run once by default to keep behavior predictable in CI / tests.
    return _once(ns)


if __name__ == "__main__":
    raise SystemExit(main())
