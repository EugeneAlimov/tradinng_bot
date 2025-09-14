# src/storage/db.py
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, Optional

import pandas as pd


def open_store(url: str) -> "BaseStore":
    """
    Открывает стор по URL:
      - sqlite:///absolute/path/to.db
      - sqlite:///:memory:
      - duckdb:///absolute/path/to.duckdb
    """
    if not isinstance(url, str) or "://" not in url:
        raise ValueError(f"Invalid store url: {url!r}")

    scheme, rest = url.split("://", 1)
    scheme = scheme.lower()

    if scheme == "sqlite":
        path = _parse_sqlite_path(rest)
        return SQLiteStore(path)

    if scheme == "duckdb":
        return DuckDBStore(rest)

    raise ValueError(f"Unsupported store scheme: {scheme}")


class BaseStore:
    def write_candles(self, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
        raise NotImplementedError

    def read_candles(
            self,
            symbol: str,
            timeframe: str,
            start: Optional[pd.Timestamp] = None,
            end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        raise NotImplementedError

    def write_signal(self, payload: Dict[str, Any]) -> int:
        raise NotImplementedError


# ---------- SQLite ----------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    ts_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low  REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (ts_utc, symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    strategy TEXT,
    side TEXT,
    price REAL,
    run_id TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_ts ON candles(symbol, timeframe, ts_utc);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts_utc);
"""


def _parse_sqlite_path(rest: str) -> str:
    if rest == "/:memory:" or rest == "///:memory:":
        return ":memory:"
    if rest.startswith("///"):
        return rest[2:]
    return rest.lstrip("/")


class SQLiteStore(BaseStore):
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        for stmt in filter(None, _SQLITE_SCHEMA.split(";")):
            s = stmt.strip()
            if s:
                self._conn.execute(s)

    def write_candles(self, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
        if df.empty:
            return 0
        if df.index.name is None:
            df = df.copy()
            df.index.name = "time"
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")

        cols = ["open", "high", "low", "close", "volume"]
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"OHLCV column missing: {c}")

        rows = [
            (
                ts.isoformat(),
                symbol,
                timeframe,
                float(df.at[ts, "open"]),
                float(df.at[ts, "high"]),
                float(df.at[ts, "low"]),
                float(df.at[ts, "close"]),
                float(df.at[ts, "volume"]),
            )
            for ts in idx
        ]
        cur = self._conn.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO candles
            (ts_utc, symbol, timeframe, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return cur.rowcount or 0

    def read_candles(
            self,
            symbol: str,
            timeframe: str,
            start: Optional[pd.Timestamp] = None,
            end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        conds = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [symbol, timeframe]
        if start is not None:
            conds.append("ts_utc >= ?")
            params.append(pd.to_datetime(start, utc=True).isoformat())
        if end is not None:
            conds.append("ts_utc <= ?")
            params.append(pd.to_datetime(end, utc=True).isoformat())
        where = " AND ".join(conds)
        q = f"""
            SELECT ts_utc, open, high, low, close, volume
            FROM candles
            WHERE {where}
            ORDER BY ts_utc
        """
        cur = self._conn.cursor()
        cur.execute(q, params)
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            ).set_index(pd.DatetimeIndex([], name="time"))

        df = pd.DataFrame(
            rows, columns=["ts_utc", "open", "high", "low", "close", "volume"]
        )
        idx = pd.to_datetime(df["ts_utc"], utc=True)
        df = df.drop(columns=["ts_utc"])
        df.index = idx
        df.index.name = "time"
        return df

    def write_signal(self, payload: Dict[str, Any]) -> int:
        # Нормализуем время и JSON, чтобы не падать на Timestamp
        ts_iso = pd.to_datetime(payload.get("time"), utc=True).isoformat()

        safe = dict(payload)
        safe["time"] = ts_iso
        payload_json = json.dumps(safe, ensure_ascii=False, default=str)

        row = (
            ts_iso,
            payload.get("symbol"),
            payload.get("timeframe"),
            payload.get("strategy"),
            payload.get("side"),
            float(payload["price"]) if payload.get("price") is not None else None,
            payload.get("run_id"),
            payload_json,
        )
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO signals
            (ts_utc, symbol, timeframe, strategy, side, price, run_id, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        return int(cur.lastrowid or 0)


# ---------- DuckDB (опционально) ----------

class DuckDBStore(BaseStore):
    def __init__(self, rest: str):
        path = rest[2:] if rest.startswith("///") else rest.lstrip("/")
        try:
            import duckdb  # type: ignore
        except Exception as e:
            raise RuntimeError(
                f"DuckDB is not installed. Install with `pip install duckdb`. Details: {e}"
            )
        self._duckdb = duckdb
        self._con = duckdb.connect(path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS candles (
                ts_utc TIMESTAMP WITH TIME ZONE,
                symbol TEXT,
                timeframe TEXT,
                open DOUBLE,
                high DOUBLE,
                low  DOUBLE,
                close DOUBLE,
                volume DOUBLE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_pk
              ON candles(ts_utc, symbol, timeframe);

            CREATE TABLE IF NOT EXISTS signals (
                id BIGINT AUTO_INCREMENT,
                ts_utc TIMESTAMP WITH TIME ZONE,
                symbol TEXT,
                timeframe TEXT,
                strategy TEXT,
                side TEXT,
                price DOUBLE,
                run_id TEXT,
                payload_json TEXT
            );
            """
        )

    def write_candles(self, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
        if df.empty:
            return 0
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        tdf = df.copy()
        tdf = tdf.assign(
            ts_utc=idx,
            symbol=symbol,
            timeframe=timeframe,
        )[["ts_utc", "symbol", "timeframe", "open", "high", "low", "close", "volume"]]
        self._con.register("tmp_df", tdf)
        self._con.execute(
            "INSERT OR REPLACE INTO candles SELECT * FROM tmp_df"
        )
        return int(len(tdf))

    def read_candles(
            self,
            symbol: str,
            timeframe: str,
            start: Optional[pd.Timestamp] = None,
            end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        conds = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [symbol, timeframe]
        if start is not None:
            conds.append("ts_utc >= ?")
            params.append(pd.to_datetime(start, utc=True))
        if end is not None:
            conds.append("ts_utc <= ?")
            params.append(pd.to_datetime(end, utc=True))
        where = " AND ".join(conds)
        q = f"""
            SELECT ts_utc, open, high, low, close, volume
            FROM candles
            WHERE {where}
            ORDER BY ts_utc
        """
        df = self._con.execute(q, params).fetch_df()
        if df.empty:
            return df.reindex(columns=["open", "high", "low", "close", "volume"]).set_index(
                pd.DatetimeIndex([], name="time")
            )
        idx = pd.to_datetime(df["ts_utc"], utc=True)
        df = df.drop(columns=["ts_utc"])
        df.index = idx
        df.index.name = "time"
        return df

    def write_signal(self, payload: Dict[str, Any]) -> int:
        ts = pd.to_datetime(payload.get("time"), utc=True)
        safe = dict(payload)
        safe["time"] = ts.isoformat()
        payload_json = json.dumps(safe, ensure_ascii=False, default=str)

        row = pd.DataFrame(
            [
                {
                    "ts_utc": ts,
                    "symbol": payload.get("symbol"),
                    "timeframe": payload.get("timeframe"),
                    "strategy": payload.get("strategy"),
                    "side": payload.get("side"),
                    "price": float(payload["price"]) if payload.get("price") is not None else None,
                    "run_id": payload.get("run_id"),
                    "payload_json": payload_json,
                }
            ]
        )
        self._con.register("tmp_sig", row)
        out = self._con.execute(
            "INSERT INTO signals SELECT * FROM tmp_sig RETURNING id"
        ).fetchall()
        return int(out[0][0]) if out else 0
