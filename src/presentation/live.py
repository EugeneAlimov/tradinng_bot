# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import time
from typing import Optional, Tuple

import pandas as pd

try:
    # пакетный запуск
    from ..integrations.exmo import fetch_exmo_candles, resample_ohlcv, normalize_resample_rule
except Exception:
    # запуск из корня
    from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv, normalize_resample_rule


def _parse_span(span: str) -> Tuple[str, int]:
    """'1m:600' -> ('1m', 600)"""
    tf, n = span.split(":")
    return tf.strip().lower(), int(n)


def _tf_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"): return int(tf[:-1]) * 60
    if tf.endswith("h"): return int(tf[:-1]) * 3600
    if tf.endswith("d"): return int(tf[:-1]) * 86400
    raise ValueError(f"Unsupported TF {tf!r}")


def _detect_cross(f_prev: float, s_prev: float, f_cur: float, s_cur: float) -> Optional[str]:
    """'buy' при пересечении вверх, 'sell' при пересечении вниз, иначе None."""
    if pd.isna(f_prev) or pd.isna(s_prev) or pd.isna(f_cur) or pd.isna(s_cur):
        return None
    if f_prev <= s_prev and f_cur > s_cur:
        return "buy"
    if f_prev >= s_prev and f_cur < s_cur:
        return "sell"
    return None


def _append_csv(path: str, row: dict) -> None:
    """Безопасно дописывает одну строку в CSV (создаёт файл и заголовок при необходимости)."""
    import csv
    header_exists = os.path.exists(path) and os.path.getsize(path) > 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not header_exists:
            w.writeheader()
        w.writerow(row)


def run_live_observe(
        pair: str,
        span: str,
        resample_rule: str,
        fast: int,
        slow: int,
        poll_sec: Optional[int] = None,
        lookback_bars: int = 400,
        log_csv: str = "",
        heartbeat_sec: int = 0,
) -> None:
    """
    Периодически тянет свечи и печатает/логирует состояние SMA.
    - Печатает сигнал только на кроссе.
    - Если задан heartbeat_sec > 0, периодически печатает «пульс» (текущие цены/SMA).
    - Если задан log_csv, на каждом последнем баре дописывает строку в CSV.
    Останавливается Ctrl+C.
    """
    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else ""

    last_signal_ts: Optional[pd.Timestamp] = None
    last_logged_ts: Optional[pd.Timestamp] = None
    next_heartbeat = time.time() + max(heartbeat_sec, 0)

    print(f"[live] observe {pair} {span} resample={rule or '—'} fast={fast} slow={slow} poll={poll}s")

    try:
        while True:
            df = fetch_exmo_candles(pair, span, verbose=False)
            if df.empty:
                print("[live] warning: no candles, retry…")
                time.sleep(poll)
                continue

            if rule:
                df = resample_ohlcv(df, rule)

            # SMA
            df["sma_fast"] = df["close"].rolling(fast, min_periods=fast).mean()
            df["sma_slow"] = df["close"].rolling(slow, min_periods=slow).mean()

            if len(df) < max(fast, slow) + 2:
                time.sleep(poll)
                continue

            # текущий и предыдущий бар
            f_prev, s_prev = df["sma_fast"].iloc[-2], df["sma_slow"].iloc[-2]
            f_cur, s_cur = df["sma_fast"].iloc[-1], df["sma_slow"].iloc[-1]
            ts = df["time"].iloc[-1]
            price = float(df["close"].iloc[-1])
            vol = float(df["volume"].iloc[-1])

            # 1) сигнал
            signal = _detect_cross(f_prev, s_prev, f_cur, s_cur)
            if signal and (last_signal_ts is None or ts > last_signal_ts):
                side = "BUY " if signal == "buy" else "SELL"
                print(f"[live] {ts.isoformat()} {side} @ {price:.6f}  (f={f_cur:.6f}, s={s_cur:.6f})")
                last_signal_ts = ts

            # 2) лог
            if log_csv and (last_logged_ts is None or ts > last_logged_ts):
                _append_csv(log_csv, {
                    "time": ts.isoformat(),
                    "close": price,
                    "volume": vol,
                    "sma_fast": float(f_cur) if pd.notna(f_cur) else "",
                    "sma_slow": float(s_cur) if pd.notna(s_cur) else "",
                    "signal": signal or "",
                })
                last_logged_ts = ts

            # 3) heartbeat
            if heartbeat_sec > 0 and time.time() >= next_heartbeat:
                print(f"[live] {ts.isoformat()} tick  close={price:.6f}  f={f_cur:.6f}  s={s_cur:.6f}")
                next_heartbeat = time.time() + heartbeat_sec

            time.sleep(poll)
    except KeyboardInterrupt:
        print("\n[live] stopped.")
