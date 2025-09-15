# src/storage/duckops.py
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, Tuple

import pandas as pd

# Optional imports
try:
    import duckdb  # type: ignore
except Exception:  # pragma: no cover - optional
    duckdb = None  # type: ignore

try:
    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore
except Exception:  # pragma: no cover - optional
    pa = None  # type: ignore
    pq = None  # type: ignore


def _parse_timeframe(tf: str) -> Tuple[str, int]:
    """
    Return ('minute'|'hour'|'day', step)
    Examples: '1min','5min','15min','1h','4h','1D'
    """
    s = tf.strip().lower()
    if s.endswith("min"):
        return "minute", int(s[:-3])
    if s.endswith("m"):
        return "minute", int(s[:-1])
    if s.endswith("h"):
        return "hour", int(s[:-1])
    if s in ("1d", "1day", "d", "day"):
        return "day", 1
    if s.endswith("d"):
        return "day", int(s[:-1])
    raise ValueError(f"Unsupported timeframe: {tf!r}")


def resample_via_duckdb(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Try DuckDB resample with robust SQL (works on 1.3.x), fallback to pandas.
    Input df must contain columns: time/timestamp + open, high, low, close[, volume].
    """
    use_duck = os.environ.get("TB_USE_DUCKDB", "0") not in ("0", "", "false", "False")
    if duckdb is None or not use_duck:
        return _resample_pandas(df, timeframe)

    if df is None or df.empty:
        return df

    # normalize column names and ensure a 'ts' column of TIMESTAMP WITH TIME ZONE
    df = df.copy()
    time_col = None
    for c in df.columns:
        if str(c).lower() in ("time", "timestamp", "ts", "date"):
            time_col = c
            break
    if time_col is None and df.index.name:
        if df.index.name.lower() in ("time", "timestamp", "ts", "date"):
            df = df.reset_index()
            time_col = df.columns[0]

    if time_col is None:
        # last resort: assume index is time
        df = df.reset_index(names="time")
        time_col = "time"

    # Ensure timezone-aware and column name 'ts'
    df["ts"] = pd.to_datetime(df[time_col], utc=True)

    # Fill missing OHLCV columns gracefully
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = None

    unit, step = _parse_timeframe(timeframe)

    con = duckdb.connect(database=":memory:")
    try:
        con.register("t", df)

        # Build bucket via DATEDIFF to avoid date_bin dependency
        # bucket = base + INTERVAL step * FLOOR(DATEDIFF(unit, base, ts) / step)
        base = "TIMESTAMP '1970-01-01 00:00:00+00'"
        bucket = (
            f"{base} + INTERVAL {step} {unit}s * "
            f"(DATEDIFF('{unit}', {base}, ts) / {step})"
        )

        sql = f"""
            SELECT
                {bucket} AS bucket,
                arg_min(open, ts)  AS open,
                max(high)          AS high,
                min(low)           AS low,
                arg_max(close, ts) AS close,
                sum(COALESCE(volume, 0)) AS volume
            FROM t
            GROUP BY 1
            ORDER BY 1
        """
        out = con.execute(sql).fetch_df()
        out = out.rename(columns={"bucket": "time"})
        # ISO strings
        out["time"] = pd.to_datetime(out["time"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        return out
    except Exception as e:
        print(f"[duckops] DuckDB resample failed ({e}), fallback to pandas.resample()")
        return _resample_pandas(df, timeframe)
    finally:
        con.close()


def _resample_pandas(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    df = df.copy()

    # Find/ensure datetime index
    if df.index.dtype.kind == "M":
        idx = pd.to_datetime(df.index, utc=True)
    else:
        time_col = None
        for c in df.columns:
            if str(c).lower() in ("time", "timestamp", "ts", "date"):
                time_col = c
                break
        if time_col is None:
            # fallback: first column is time
            time_col = df.columns[0]
        idx = pd.to_datetime(df[time_col], utc=True)

    df.index = idx
    rule = timeframe.replace("T", "min")  # safety for old alias
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"

    out = df.resample(rule, origin="start_day").agg(agg).dropna(how="all")
    out = out.reset_index().rename(columns={"index": "time"})
    out["time"] = pd.to_datetime(out["time"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return out


def write_parquet_partitioned(
        df: pd.DataFrame,
        base_dir: str,
        symbol: str,
        timeframe: str,
        filename_prefix: Optional[str] = None,
) -> str:
    """
    Write df to path:
      {base_dir}/symbol={symbol}/timeframe={timeframe}/{prefix or yyyymmdd-HHMMSS}.parquet
    Returns written file path.
    """
    if df is None or df.empty:
        raise ValueError("write_parquet_partitioned: empty dataframe")

    # ensure time column
    if "time" not in (c.lower() for c in df.columns):
        raise ValueError("write_parquet_partitioned: df must contain 'time' column")

    base = Path(base_dir)
    out_dir = base / f"symbol={symbol}" / f"timeframe={timeframe}"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = filename_prefix or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{fname}.parquet"

    if pq is not None:
        # arrow path (fast & robust)
        # normalize time to timestamp[ns, tz=UTC] -> stored as UTC
        dfa = df.copy()
        tcol = None
        for c in dfa.columns:
            if str(c).lower() == "time":
                tcol = c
                break
        dfa[tcol] = pd.to_datetime(dfa[tcol], utc=True)
        table = pa.Table.from_pandas(dfa)
        pq.write_table(table, out_path)
    else:
        # pandas fallback
        df.to_parquet(out_path, index=False)

    return str(out_path)
