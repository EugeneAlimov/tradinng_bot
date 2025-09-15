from __future__ import annotations

import argparse
import os
import sqlite3
from typing import Optional

from src.storage.db import (
    open_store,
    _parse_sqlite_path,  # reuse
    SIGNALS_DDL,
    CANDLES_DDL,
    SIGNALS_INDEXES,
    CANDLES_INDEXES,
)

APP_NAME = "tb-db"


# ------------------------
# utils
# ------------------------

def _resolve_db_path(url_or_path: Optional[str]) -> str:
    url = url_or_path or os.getenv("TB_STORE_URL", "sqlite:///data/bot.db")
    return _parse_sqlite_path(url)


def _conn(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ------------------------
# commands
# ------------------------

def cmd_migrate(args) -> int:
    store = open_store(args.db)
    # ensure_schema вызывается в __post_init__, этого достаточно
    print("Schema ensured (signals/candles).")
    return 0


def cmd_check(args) -> int:
    store = open_store(args.db)
    counts = store.counts()
    print(f"signals: {counts['signals']}")
    print(f"candles: {counts['candles']}\n")
    if counts["signals"]:
        print("last signals:")
        for r in store.last_signals(limit=10):
            print(
                f"  {r['id']} | {r['time']} | {r['symbol']} {r['timeframe']} | {r['strategy']} {r['side']} @{r['price']} | run={r['run_id']}")
    return 0


def cmd_normalize_time(args) -> int:
    """
    Легкая нормализация формата времени (обрезка пробелов/замена +00:00 -> +0000).
    Для полной нормализации используем уже добавленные утилиты в пайплайне.
    """
    db_path = _resolve_db_path(args.db)
    conn = _conn(db_path)
    with conn:
        # signals
        cur = conn.cursor()
        cur.execute("SELECT id, time FROM signals")
        rows = cur.fetchall()
        for _id, t in rows:
            t2 = (t or "").strip().replace("+00:00", "+0000")
            if t2 != t:
                cur.execute("UPDATE signals SET time=? WHERE id=?", (t2, _id))

        # candles
        cur.execute("SELECT id, time FROM candles")
        rows = cur.fetchall()
        for _id, t in rows:
            t2 = (t or "").strip().replace("+00:00", "+0000")
            if t2 != t:
                cur.execute("UPDATE candles SET time=? WHERE id=?", (t2, _id))
    print("Time normalized (+00:00 -> +0000) for signals/candles.")
    return 0


def cmd_create_indexes(args) -> int:
    db_path = _resolve_db_path(args.db)
    conn = _conn(db_path)
    with conn:
        cur = conn.cursor()
        # таблицы на всякий
        cur.executescript(SIGNALS_DDL + "\n" + CANDLES_DDL)
        # индексы
        for s in SIGNALS_INDEXES + CANDLES_INDEXES:
            cur.execute(s)
    print("Indexes ensured (including uniq_signals_keys).")
    return 0


def cmd_dedupe_signals(args) -> int:
    db_path = _resolve_db_path(args.db)
    conn = _conn(db_path)
    with conn:
        cur = conn.cursor()
        # на всякий — обеспечим уникальный индекс
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uniq_signals_keys ON signals(time, symbol, timeframe, strategy, run_id)")
        # удаление дублей: оставляем минимальный id в группе
        cur.executescript("""
        WITH keep AS (
          SELECT MIN(id) AS id
          FROM signals
          GROUP BY time, symbol, timeframe, strategy, run_id
        )
        DELETE FROM signals
        WHERE id NOT IN (SELECT id FROM keep);
        """)
    print("Signals deduplicated.")
    return 0


# ------------------------
# main
# ------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP_NAME)
    p.add_argument("--db", dest="db", default=None,
                   help='DB URL or path (default: env TB_STORE_URL or "sqlite:///data/bot.db")')

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("migrate", help="Create/upgrade schema")
    sp.set_defaults(func=cmd_migrate)

    sp = sub.add_parser("check", help="Print counts and last signals")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("normalize-time", help="Normalize timestamps formatting")
    sp.set_defaults(func=cmd_normalize_time)

    sp = sub.add_parser("create-indexes", help="Ensure indexes (incl. unique signal key)")
    sp.set_defaults(func=cmd_create_indexes)

    sp = sub.add_parser("dedupe-signals", help="Remove duplicated signals (keep min id in each group)")
    sp.set_defaults(func=cmd_dedupe_signals)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
