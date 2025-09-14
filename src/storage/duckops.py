# src/storage/duckops.py
from __future__ import annotations

import os
from typing import Optional

import pandas as pd


def _minutes_from_rule(rule: str) -> int:
    r = rule.strip().lower()
    if r.endswith("min"):
        return int(r[:-3].strip())
    if r.endswith("m"):
        return int(r[:-1].strip())
    if r.endswith("h"):
        return int(r[:-1].strip()) * 60
    if r.endswith("hour"):
        return int(r[:-4].strip()) * 60
    raise ValueError(f"Unsupported rule: {rule!r}")


def resample_via_duckdb(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Ресемплинг OHLCV с использованием DuckDB GROUP BY date_bin(...).
    Требования к df: индекс — DatetimeIndex (UTC), есть столбцы open/high/low/close/volume.
    """
    try:
        import duckdb  # type: ignore
    except Exception as e:
        raise RuntimeError("DuckDB is not installed. Install with `pip install duckdb`.") from e

    if df.empty or not rule:
        return df

    nmin = _minutes_from_rule(rule)

    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")

    tmp = df.copy()
    tmp = tmp.assign(ts=idx)

    con = duckdb.connect(":memory:")
    con.register("x", tmp)

    # Основной вариант: date_bin()
    bucket = f"date_bin(INTERVAL '{nmin} minutes', ts, TIMESTAMP '1970-01-01 00:00:00+00:00')"
    sql = f"""
        SELECT
            {bucket} AS time,
            first(open)  AS open,
            max(high)    AS high,
            min(low)     AS low,
            last(close)  AS close,
            sum(volume)  AS volume
        FROM x
        GROUP BY 1
        ORDER BY 1
    """
    try:
        out = con.execute(sql).fetch_df()
    except Exception:
        # Фоллбек через epoch + floor
        sql_fb = f"""
            SELECT
                TIMESTAMP '1970-01-01 00:00:00+00:00'
                  + INTERVAL (floor(epoch(ts) / ({nmin}*60)) * {nmin}*60) SECOND AS time,
                first(open)  AS open,
                max(high)    AS high,
                min(low)     AS low,
                last(close)  AS close,
                sum(volume)  AS volume
            FROM x
            GROUP BY 1
            ORDER BY 1
        """
        out = con.execute(sql_fb).fetch_df()

    out = out.set_index(pd.to_datetime(out["time"], utc=True)).drop(columns=["time"])
    out.index.name = "time"
    return out


def write_parquet_partitioned(
        df: pd.DataFrame,
        out_dir: str,
        symbol: str,
        timeframe: str,
) -> None:
    """
    Пишет df в Parquet через DuckDB.
    Пытается PARTITION_BY (symbol,timeframe), если не получится — пишет единый файл.
    """
    if df.empty:
        return

    try:
        import duckdb  # type: ignore
    except Exception as e:
        raise RuntimeError("DuckDB is not installed. Install with `pip install duckdb`.") from e

    os.makedirs(out_dir, exist_ok=True)

    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")

    tmp = df.copy()
    tmp = tmp.assign(time=idx, symbol=symbol, timeframe=timeframe)

    con = duckdb.connect(":memory:")
    con.register("y", tmp)

    target_dir = os.path.abspath(out_dir)

    sql_part = f"""
        COPY (SELECT time, open, high, low, close, volume, symbol, timeframe FROM y)
        TO '{target_dir}'
        (FORMAT PARQUET, PARTITION_BY (symbol, timeframe))
    """

    try:
        con.execute(sql_part)
        return
    except Exception:
        # fallback — один файл с именем по символу и ТФ
        file_path = os.path.join(target_dir, f"{symbol}_{timeframe}.parquet")
        sql_single = f"""
            COPY (SELECT time, open, high, low, close, volume, symbol, timeframe FROM y)
            TO '{file_path}' (FORMAT PARQUET)
        """
        con.execute(sql_single)
