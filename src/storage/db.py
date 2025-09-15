from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

# =========================
# DDL
# =========================

SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS signals (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  time      TEXT NOT NULL,
  symbol    TEXT,
  timeframe TEXT,
  strategy  TEXT,
  side      TEXT,
  price     REAL,
  run_id    TEXT,
  data      TEXT
);
"""

CANDLES_DDL = """
CREATE TABLE IF NOT EXISTS candles (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  time      TEXT NOT NULL,
  symbol    TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  open      REAL,
  high      REAL,
  low       REAL,
  close     REAL,
  volume    REAL,
  data      TEXT,
  UNIQUE(time, symbol, timeframe)
);
"""

# Индексы
SIGNALS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_signals_time      ON signals(time)",
    "CREATE INDEX IF NOT EXISTS idx_signals_sym_tf_t  ON signals(symbol, timeframe, time)",
    # Уникальность ключа сигнала — нужна для UPSERT
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_signals_keys ON signals(time, symbol, timeframe, strategy, run_id)",
]

CANDLES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_candles_time ON candles(time)",
    "CREATE INDEX IF NOT EXISTS idx_candles_main ON candles(symbol, timeframe, time)",
]


# =========================
# Helpers
# =========================

def _parse_sqlite_path(url_or_path: str) -> str:
    """
    Принимает строку вида "sqlite:///data/bot.db" или путь "data/bot.db"
    и возвращает путь к файлу БД.
    """
    if url_or_path.startswith("sqlite:///"):
        return url_or_path[len("sqlite:///"):]
    return url_or_path


def open_store(url_or_path: Optional[str]) -> "SQLiteStore":
    """
    Универсальный открыватель стора (пока только SQLite).
    """
    url = url_or_path or os.getenv("TB_STORE_URL", "sqlite:///data/bot.db")
    db_path = _parse_sqlite_path(url)
    return SQLiteStore(db_path)


def _json_dumps_or_none(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None


# =========================
# SQLite store
# =========================

@dataclass
class SQLiteStore:
    path: str

    def __post_init__(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self.ensure_schema()

    def ensure_schema(self) -> None:
        # таблицы
        self._conn.executescript(SIGNALS_DDL + "\n" + CANDLES_DDL)
        # индексы
        with self._conn:
            cur = self._conn.cursor()
            self._ensure_indexes(cur, SIGNALS_INDEXES)
            self._ensure_indexes(cur, CANDLES_INDEXES)

    @staticmethod
    def _ensure_indexes(cur: sqlite3.Cursor, stmts: Iterable[str]) -> None:
        for s in stmts:
            cur.execute(s)

    # ---------- API: запись ----------

    def upsert_signal(self, signal: Dict[str, Any]) -> None:
        """
        Идемпотентная запись сигнала по ключу (time,symbol,timeframe,strategy,run_id).
        Обновляет side/price/data при конфликте.
        """
        row = {
            "time": signal.get("time"),
            "symbol": signal.get("symbol"),
            "timeframe": signal.get("timeframe"),
            "strategy": signal.get("strategy"),
            "side": signal.get("side"),
            "price": signal.get("price"),
            "run_id": signal.get("run_id"),
            "data": _json_dumps_or_none(signal.get("data")),
        }
        sql = """
        INSERT INTO signals (time, symbol, timeframe, strategy, side, price, run_id, data)
        VALUES (:time, :symbol, :timeframe, :strategy, :side, :price, :run_id, :data)
        ON CONFLICT(time, symbol, timeframe, strategy, run_id) DO UPDATE SET
            side  = excluded.side,
            price = excluded.price,
            data  = excluded.data
        """
        with self._conn:
            self._conn.execute(sql, row)

    def upsert_candles(
            self,
            candles: Iterable[Dict[str, Any]],
    ) -> None:
        """
        Идемпотентная запись свечей. Ключ (time,symbol,timeframe).
        """
        sql = """
        INSERT INTO candles (time, symbol, timeframe, open, high, low, close, volume, data)
        VALUES (:time, :symbol, :timeframe, :open, :high, :low, :close, :volume, :data)
        ON CONFLICT(time, symbol, timeframe) DO UPDATE SET
            open   = excluded.open,
            high   = excluded.high,
            low    = excluded.low,
            close  = excluded.close,
            volume = excluded.volume,
            data   = excluded.data
        """
        with self._conn:
            self._conn.executemany(sql, candles)

    # ---------- API: чтение/инфо ----------

    def counts(self) -> Dict[str, int]:
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM signals")
        s = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candles")
        c = cur.fetchone()[0]
        return {"signals": s, "candles": c}

    def last_signals(self, limit: int = 10) -> Iterable[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, time, symbol, timeframe, strategy, side, price, run_id
            FROM signals
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


# =========================
# Module-level helpers used around the codebase
# =========================

def write_signal(signal: Dict[str, Any], url: Optional[str] = None) -> None:
    """
    Унифицированная точка записи сигнала из других модулей.
    """
    store = open_store(url)
    store.upsert_signal(signal)


def write_candles(df, symbol: str, timeframe: str, url: Optional[str] = None, tcol: str = "time") -> None:
    """
    df: pandas.DataFrame с колонками [open,high,low,close,volume] и индексом-датой
        или с колонкой времени `tcol`. Все времена должны быть в UTC-ISO.
    """
    try:
        import pandas as pd  # noqa: F401
    except Exception:
        raise RuntimeError("write_candles: требуется pandas DataFrame")

    if tcol in df.columns:
        times = df[tcol].astype(str)
    else:
        times = df.index.astype(str)

    to_rows = []
    for t, row in zip(times, df.itertuples(index=False, name=None)):
        # предполагаем порядок: open,high,low,close,volume [и, возможно, лишние поля]
        o, h, l, c, v = row[:5]
        to_rows.append(
            {
                "time": str(t),
                "symbol": symbol,
                "timeframe": timeframe,
                "open": float(o) if o is not None else None,
                "high": float(h) if h is not None else None,
                "low": float(l) if l is not None else None,
                "close": float(c) if c is not None else None,
                "volume": float(v) if v is not None else None,
                "data": None,
            }
        )

    store = open_store(url)
    store.upsert_candles(to_rows)
