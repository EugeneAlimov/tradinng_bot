# scripts/smoke_db_write.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.storage import db
from src.utils.timefmt import to_utc_str


def main() -> None:
    url = os.environ.get("TB_STORE_URL", "sqlite:///data/bot.db")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    signal = {
        "time": to_utc_str(now),
        "symbol": "DEMO",
        "timeframe": "5min",
        "strategy": "ema_adx_atr",
        "side": "LONG",
        "price": 123.45,
        "run_id": "smoke",
        "data": None,
    }

    db.write_signal(signal, url=url)

    # Три свечи на 5м
    times = [now - timedelta(minutes=10), now - timedelta(minutes=5), now]
    df = pd.DataFrame(
        {
            "time": [to_utc_str(t) for t in times],
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.8, 10.8, 11.8],
            "close": [10.2, 11.2, 12.2],
            "volume": [100.0, 120.0, 110.0],
        }
    )

    db.write_candles(df, symbol="DEMO", timeframe="5min", url=url)
    print(f"OK: wrote 1 signal and {len(df)} candles to {url}")


if __name__ == "__main__":
    main()
