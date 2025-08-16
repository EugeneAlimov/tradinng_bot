from __future__ import annotations

from pathlib import Path
import csv
import time
import pandas as pd

_SIG_HEADER = ["time", "close", "volume", "sma_fast", "sma_slow", "signal"]


def _ensure_csv_with_header(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(_SIG_HEADER)


def _append_signal_row(path: Path, row: list[str]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def run_live_observe(
        pair: str,
        span: str,
        resample_rule: str,
        fast: int,
        slow: int,
        poll_sec: int = 15,
        heartbeat_sec: int = 60,
        live_log: str | None = None,
        hysteresis_bps: float = 0.0,
) -> None:
    """
    Живое наблюдение: печать/лог последнего бара без дублей.
    Гистерезис: сигнал только если |fast-slow|/price*1e4 >= hysteresis_bps.
    Ctrl-C — без traceback.
    """
    from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv

    pretty_resample = resample_rule if (resample_rule and resample_rule.strip()) else "—"
    print(
        f"[live] observe {pair} {span} resample={pretty_resample} "
        f"fast={fast} slow={slow} poll={poll_sec}s"
    )

    log_path: Path | None = None
    if live_log:
        log_path = Path(live_log)
        _ensure_csv_with_header(log_path)

    next_hb = time.time() + max(1, int(heartbeat_sec)) if heartbeat_sec else float("inf")
    last_written_ts: pd.Timestamp | None = None

    try:
        while True:
            df_raw = fetch_exmo_candles(pair, span)
            if df_raw is None or df_raw.empty:
                time.sleep(poll_sec)
                continue

            if resample_rule and resample_rule.strip():
                df = resample_ohlcv(df_raw, resample_rule)
            else:
                df = df_raw.copy()

            if df is None or df.empty:
                time.sleep(poll_sec)
                continue

            # обеспечить колонку time с UTC
            if "time" in df.columns:
                df = df.copy()
                df["time"] = pd.to_datetime(df["time"], utc=True)
            elif isinstance(df.index, pd.DatetimeIndex):
                df = df.copy()
                idx = df.index
                if idx.tz is None:
                    idx = idx.tz_localize("UTC")
                else:
                    idx = idx.tz_convert("UTC")
                df["time"] = idx
            else:
                time.sleep(poll_sec)
                continue

            # SMA
            df["sma_fast"] = df["close"].rolling(window=fast, min_periods=1).mean()
            df["sma_slow"] = df["close"].rolling(window=slow, min_periods=1).mean()
            if len(df) < 2:
                time.sleep(poll_sec)
                continue

            prev = df.iloc[-2]
            last = df.iloc[-1]

            ts: pd.Timestamp = pd.to_datetime(last["time"], utc=True)
            price = float(last["close"])
            vol = float(last.get("volume", 0.0))
            f = float(last["sma_fast"])
            s = float(last["sma_slow"])
            pf = float(prev["sma_fast"])
            ps = float(prev["sma_slow"])

            # базовый сигнал на пересечении
            sig = "none"
            if pf <= ps and f > s:
                sig = "buy"
            elif pf >= ps and f < s:
                sig = "sell"

            # гистерезис (в б.п. относительно цены)
            if sig != "none" and hysteresis_bps > 0.0:
                diff_bps = abs(f - s) / max(1e-12, price) * 1e4
                if diff_bps < hysteresis_bps:
                    sig = "none"

            if last_written_ts is None or ts > last_written_ts:
                print(f"[live] {ts.isoformat()} tick  close={price:.6f}  f={f:.6f}  s={s:.6f}")
                if log_path:
                    _append_signal_row(
                        log_path,
                        [
                            ts.isoformat(),
                            f"{price:.8f}",
                            f"{vol:.8f}",
                            f"{f:.8f}",
                            f"{s:.8f}",
                            sig,
                        ],
                    )
                last_written_ts = ts

            now = time.time()
            if now >= next_hb:
                print(f"[live] hb @ {pd.Timestamp.utcnow().isoformat()}")
                next_hb = now + max(1, int(heartbeat_sec)) if heartbeat_sec else float("inf")

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        print("[live] stopped.")
        return
