# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# --- интеграция EXMO (прямая) ---
try:
    from ..integrations.exmo import fetch_exmo_candles as _FETCH
    from ..integrations.exmo import resample_ohlcv as _RESAMPLE
    try:
        from ..integrations.exmo import normalize_resample_rule as _NORM
    except Exception:
        _NORM = None
except Exception:
    _FETCH = None
    _RESAMPLE = None
    _NORM = None


def _normalize_rule(rule: str) -> str:
    if _NORM is not None:
        return _NORM(rule)
    if not rule:
        return ""
    r = str(rule).strip().lower()
    if r.endswith("m"):
        return f"{int(r[:-1])}min"
    if r.endswith("min"):
        return r
    if r.endswith("h"):
        return f"{int(r[:-1])}h"
    if r.endswith("d"):
        return f"{int(r[:-1])}d"
    return r


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if not rule:
        return df.copy()
    if _RESAMPLE is not None:
        return _RESAMPLE(df, rule)
    x = df.copy()
    if "time" in x.columns:
        x["time"] = pd.to_datetime(x["time"], utc=True, errors="coerce")
        x = x.set_index("time")
    if not isinstance(x.index, pd.DatetimeIndex):
        raise ValueError("DataFrame должен содержать DatetimeIndex или колонку 'time'.")
    o = x["open"].resample(rule).first()
    h = x["high"].resample(rule).max()
    l = x["low"].resample(rule).min()
    c = x["close"].resample(rule).last()
    v = x["volume"].resample(rule).sum() if "volume" in x.columns else None
    y = {"open": o, "high": h, "low": l, "close": c}
    if v is not None:
        y["volume"] = v
    out = pd.DataFrame(y).dropna().reset_index()
    return out


def _fetch(pair: str, span: str) -> pd.DataFrame:
    if _FETCH is None:
        raise RuntimeError("integrations.exmo.fetch_exmo_candles недоступен.")
    return _FETCH(pair, span)


# ---- TF utils ----
def _parse_span(span: str) -> Tuple[str, int]:
    tf, n = span.split(":")
    return tf.strip().lower(), int(n)


def _tf_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    raise ValueError(f"Unsupported TF {tf!r}")


# ---- CSV helpers (устойчивость к перезапускам, без дублей) ----
def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)


def _read_last_written_ts(csv_path: Optional[str]) -> Optional[pd.Timestamp]:
    if not csv_path or not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return None
    try:
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
        ts_s = last.split(",", 1)[0].strip()
        ts = pd.to_datetime(ts_s, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return pd.Timestamp(ts)
    except Exception:
        return None


def _append_live_signal_row(
    csv_path: str,
    ts: datetime,
    close: float,
    volume: float,
    sma_fast: float,
    sma_slow: float,
    signal: Optional[str],
) -> None:
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

    _ensure_dir(csv_path)
    need_header = (not os.path.exists(csv_path)) or (os.path.getsize(csv_path) == 0)
    with open(csv_path, "a", newline="") as f:
        if need_header:
            f.write("time,close,volume,sma_fast,sma_slow,signal\n")
        f.write(row)


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
      - тянем EXMO свечи
      - опционально ресемплим
      - считаем SMA(fast/slow) и сигнал ('buy'/'sell'/'none')
      - печать в консоль максимум 1 раз на бар
      - лог в CSV максимум 1 строка на бар (устойчиво к перезапускам)
      - при closed_only_log=True — пишем только ЗАКРЫТЫЕ бары
    """
    rule = _normalize_rule(resample_rule) if resample_rule else ""
    rs_print = rule or "—"
    print(f"[live] observe {pair} {span} resample={rs_print} fast={fast} slow={slow} poll={poll_sec}s")

    # таймфрейм для проверки "закрытости" бара
    base_tf, _ = _parse_span(span)
    base_tf_sec = _tf_seconds(base_tf)
    rs_tf_sec = None
    if rule:
        # грубая оценка секунд из pandas rule: '5min'/'15min'/'1h'/'1d'
        r = rule.lower()
        if r.endswith("min"):
            rs_tf_sec = int(r[:-3]) * 60
        elif r.endswith("h"):
            rs_tf_sec = int(r[:-1]) * 3600
        elif r.endswith("d"):
            rs_tf_sec = int(r[:-1]) * 86400

    last_written_ts: Optional[pd.Timestamp] = _read_last_written_ts(live_log)
    last_printed_ts: Optional[pd.Timestamp] = None
    last_hb: float = time.time()

    try:
        while True:
            df = _fetch(pair, span)
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

            dfr = df
            if rule:
                dfr = _resample_ohlcv(df, rule)
                if dfr is None or len(dfr) == 0:
                    time.sleep(max(1, int(poll_sec)))
                    continue
                # после фолбэк-ресемпла в колонках есть 'time'
                if "time" in dfr.columns:
                    dfr["time"] = pd.to_datetime(dfr["time"], utc=True, errors="coerce")
                    dfr = dfr.set_index("time").sort_index()

            dfr = dfr.copy()
            dfr["sma_fast"] = dfr["close"].rolling(int(fast), min_periods=1).mean()
            dfr["sma_slow"] = dfr["close"].rolling(int(slow), min_periods=1).mean()
            if len(dfr) < 2:
                time.sleep(max(1, int(poll_sec)))
                continue

            last_ts = pd.Timestamp(dfr.index[-1])
            prev_ts = pd.Timestamp(dfr.index[-2])

            close_now = float(dfr.iloc[-1]["close"])
            vol_now = float(dfr.iloc[-1]["volume"]) if "volume" in dfr.columns else 0.0
            f_now = float(dfr.iloc[-1]["sma_fast"])
            s_now = float(dfr.iloc[-1]["sma_slow"])
            f_prev = float(dfr.iloc[-2]["sma_fast"])
            s_prev = float(dfr.iloc[-2]["sma_slow"])

            sig = _compute_signal(f_now, s_now, f_prev, s_prev)

            # печать в консоль — только при смене бара
            if (last_printed_ts is None) or (last_ts > last_printed_ts):
                ts_iso = last_ts.tz_convert("UTC").isoformat()
                print(f"[live] {ts_iso} tick  close={close_now:.6f}  f={f_now:.6f}  s={s_now:.6f}")
                last_printed_ts = last_ts

            # определяем, «закрыт» ли бар (для режима closed_only_log)
            is_closed = True
            if closed_only_log:
                now_utc = datetime.now(timezone.utc)
                # если есть ресемпл — используем его длительность, иначе базовый TF
                tf_sec = rs_tf_sec or base_tf_sec
                # считаем бар закрытым, если его ts < now_utc - tf_sec
                is_closed = (now_utc.timestamp() - last_ts.timestamp()) >= tf_sec - 1e-6

            # запись в CSV — только новый бар и (опц.) только закрытый
            if live_log and ((last_written_ts is None) or (last_ts > last_written_ts)) and is_closed:
                _append_live_signal_row(
                    live_log,
                    ts=last_ts.to_pydatetime(),
                    close=close_now,
                    volume=vol_now,
                    sma_fast=f_now,
                    sma_slow=s_now,
                    signal=sig,
                )
                last_written_ts = last_ts

            # heartbeat — по времени
            now = time.time()
            if now - last_hb >= max(5, int(heartbeat_sec)):
                hb_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
                print(f"[live] hb @ {hb_iso}")
                last_hb = now

            time.sleep(max(1, int(poll_sec)))
    except KeyboardInterrupt:
        print("[live] stopped.")
