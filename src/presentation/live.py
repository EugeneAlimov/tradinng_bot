# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import time
from datetime import timezone, datetime
from typing import Optional, Tuple

import numpy as np
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

def _append_live_signal_row(
    csv_path: str,
    ts: datetime,
    close: float,
    volume: float,
    sma_fast: float,
    sma_slow: float,
    signal: Optional[str],
) -> None:
    """Пишет одну строку в CSV: time,close,volume,sma_fast,sma_slow,signal."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    iso = ts.astimezone(timezone.utc).isoformat(timespec="seconds")
    sig = "" if not signal else str(signal)

    row = "{time},{close:.8f},{vol:.8f},{f:.8f},{s:.8f},{sig}\n".format(
        time=iso,
        close=float(close),
        vol=float(volume if volume is not None else 0.0),
        f=float(sma_fast if sma_fast is not None else 0.0),
        s=float(sma_slow if sma_slow is not None else 0.0),
        sig=sig,
    )

    directory = os.path.dirname(csv_path) or "."
    os.makedirs(directory, exist_ok=True)
    need_header = (not os.path.exists(csv_path)) or (os.path.getsize(csv_path) == 0)

    with open(csv_path, "a", newline="") as f:
        if need_header:
            f.write("time,close,volume,sma_fast,sma_slow,signal\n")
        f.write(row)


def _read_last_written_ts(csv_path: Optional[str]) -> Optional[pd.Timestamp]:
    """Возвращает последний time из CSV, если файл существует и непустой."""
    if not csv_path or not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return None
    try:
        # читаем последнюю непустую строку
        with open(csv_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            line = b""
            while pos > 0:
                pos -= 1
                f.seek(pos)
                ch = f.read(1)
                if ch == b"\n" and line:
                    break
                line = ch + line
        last = line.decode("utf-8").strip()
        if not last or last.startswith("time,"):
            return None
        # time в первой колонке
        ts_s = last.split(",", 1)[0].strip()
        ts = pd.to_datetime(ts_s, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return pd.Timestamp(ts)
    except Exception:
        return None



def run_live_observe(
    pair: str,
    span: str,
    resample_rule: str,
    fast: int,
    slow: int,
    poll_sec: int = 15,
    heartbeat_sec: int = 60,
    live_log: Optional[str] = None,
    closed_only_log: bool = False,
) -> None:
    """
    Лайв-наблюдение:
      - тянем EXMO свечи, опционально ресемплим
      - считаем SMA(fast/slow) и сигнал ('buy'/'sell'/'none')
      - пишем в CSV РОВНО одну строку на бар (без дублей)
      - печатаем в консоль максимум одну строку на бар
      - если closed_only_log=True — логируем и печатаем только ЗАКРЫТЫЕ бары
    """
    rs_print = resample_rule if (resample_rule and str(resample_rule).strip()) else "—"
    print(f"[live] observe {pair} {span} resample={rs_print} fast={fast} slow={slow} poll={poll_sec}s")

    # последний записанный в CSV бар (устойчиво к перезапуску)
    last_written_ts: Optional[pd.Timestamp] = _read_last_written_ts(live_log)
    # последний выведенный в консоль бар (антиспам)
    last_printed_ts: Optional[pd.Timestamp] = None

    last_hb: float = time.time()

    def _compute_signal(f_now: float, s_now: float, f_prev: float, s_prev: float) -> str:
        if any(map(np.isnan, [f_now, s_now, f_prev, s_prev])):
            return ""
        cross_up = (f_prev <= s_prev) and (f_now > s_now)
        cross_dn = (f_prev >= s_prev) and (f_now < s_now)
        if cross_up:
            return "buy"
        if cross_dn:
            return "sell"
        return "none"

    try:
        while True:
            # 1) загрузка и индекс времени
            df = fetch_exmo_candles(pair, span)
            if df is None or len(df) == 0:
                time.sleep(max(1, int(poll_sec)))
                continue

            if not isinstance(df.index, pd.DatetimeIndex):
                if "time" in df.columns:
                    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
                    df = df.set_index("time")
                else:
                    time.sleep(max(1, int(poll_sec)))
                    continue

            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")
            df = df.sort_index()

            # 2) ресемпл при необходимости
            dfr = df
            if resample_rule and str(resample_rule).strip():
                dfr = resample_ohlcv(df, rule=resample_rule)
                if dfr is None or len(dfr) == 0:
                    time.sleep(max(1, int(poll_sec)))
                    continue

            # 3) SMA
            dfr = dfr.copy()
            dfr["sma_fast"] = dfr["close"].rolling(int(fast), min_periods=1).mean()
            dfr["sma_slow"] = dfr["close"].rolling(int(slow), min_periods=1).mean()

            # сколько баров нужно для выбора индекса
            need_bars = 2 if closed_only_log else 2  # нужно минимум 2, чтобы был и prev
            if len(dfr) < need_bars:
                time.sleep(max(1, int(poll_sec)))
                continue

            # 4) выбираем индекс «текущего» бара для логирования/печати
            #    - если closed_only_log=True, берём ПРЕДпоследний бар (закрытый)
            #    - иначе берём последний бар
            i = len(dfr) - 2 if closed_only_log else len(dfr) - 1
            j = i - 1
            if j < 0:
                time.sleep(max(1, int(poll_sec)))
                continue

            cur_ts = pd.Timestamp(dfr.index[i])
            prev_ts = pd.Timestamp(dfr.index[j])

            close_now = float(dfr.iloc[i]["close"])
            vol_now = float(dfr.iloc[i]["volume"]) if "volume" in dfr.columns else 0.0
            f_now = float(dfr.iloc[i]["sma_fast"])
            s_now = float(dfr.iloc[i]["sma_slow"])
            f_prev = float(dfr.iloc[j]["sma_fast"])
            s_prev = float(dfr.iloc[j]["sma_slow"])

            sig = _compute_signal(f_now, s_now, f_prev, s_prev)

            # 5) Печатаем в консоль только если бар сменился
            if (last_printed_ts is None) or (cur_ts > last_printed_ts):
                ts_iso = cur_ts.tz_convert("UTC").isoformat()
                print(f"[live] {ts_iso} tick  close={close_now:.6f}  f={f_now:.6f}  s={s_now:.6f}")
                last_printed_ts = cur_ts

            # 6) Пишем в CSV только если бар НОВЫЙ относительно последней записи
            if live_log and ((last_written_ts is None) or (cur_ts > last_written_ts)):
                _append_live_signal_row(
                    live_log,
                    ts=cur_ts.to_pydatetime(),
                    close=close_now,
                    volume=vol_now,
                    sma_fast=f_now,
                    sma_slow=s_now,
                    signal=sig,
                )
                last_written_ts = cur_ts

            # 7) heartbeat (по времени, не по барам)
            now = time.time()
            if now - last_hb >= max(5, int(heartbeat_sec)):
                hb_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
                print(f"[live] hb @ {hb_iso}")
                last_hb = now

            time.sleep(max(1, int(poll_sec)))
    except KeyboardInterrupt:
        print("[live] stopped.")

