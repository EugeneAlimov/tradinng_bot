# src/presentation/live.py
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv


@dataclass
class ObserveConfig:
    pair: str
    span: str
    resample_rule: str  # "" -> без ресемплинга
    fast: int
    slow: int
    poll_sec: int = 10
    heartbeat_sec: int = 60
    live_log: Optional[str] = None
    closed_only_log: Optional[str] = None  # для совместимости с app.py; в observe не используется


# ---------- утилиты ----------

def _ensure_parent(path: str) -> None:
    if not path:
        return
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _append_csv_row(csv_path: str, header: list[str], row: list[str]) -> None:
    """Безопасная допись строки в CSV с автозаголовком."""
    _ensure_parent(csv_path)
    need_header = True
    if os.path.exists(csv_path):
        try:
            need_header = os.path.getsize(csv_path) == 0
        except OSError:
            need_header = True
    with open(csv_path, "a", encoding="utf-8") as f:
        if need_header:
            f.write(",".join(header) + "\n")
        f.write(",".join(row) + "\n")


def _iso(dt: pd.Timestamp) -> str:
    if not isinstance(dt, pd.Timestamp):
        dt = pd.to_datetime(dt, utc=True)
    if dt.tz is None:
        dt = dt.tz_localize("UTC")
    return dt.isoformat()


def _compute_sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def _ensure_time_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Гарантируем колонку 'time' в UTC, даже если время в индексе.
    Также удаляем возможные дубликаты по времени.
    """
    d = df.copy()

    # Если 'time' нет в колонках, попытаться вынести из индекса
    if "time" not in d.columns:
        if isinstance(d.index, pd.DatetimeIndex):
            d = d.reset_index()
            # имя индекса может быть 'time' или None/'index'
            idx_name = d.columns[0]
            d = d.rename(columns={idx_name: "time"})
        else:
            # Попытка найти потенциальные колонки времени
            for cand in ("timestamp", "date", "Datetime", "datetime"):
                if cand in d.columns:
                    d = d.rename(columns={cand: "time"})
                    break

    if "time" not in d.columns:
        raise KeyError("DataFrame doesn't contain 'time' column and no DatetimeIndex to derive it from.")

    # Приводим к datetime64[ns, UTC]
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    d = d.dropna(subset=["time"])

    # Удаляем дубликаты по времени (берём последнюю свечу)
    if d["time"].duplicated().any():
        d = (
            d.sort_values("time")
            .groupby("time", as_index=False)
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            })
        )

    # Сортируем по времени
    d = d.sort_values("time").reset_index(drop=True)

    # Убеждаемся в наличии основных колонок
    for col in ("open", "high", "low", "close", "volume"):
        if col not in d.columns:
            raise KeyError(f"Required column '{col}' not found after time normalization.")

    # Типы
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0.0)

    return d


# ---------- основной режим observe ----------

def run_live_observe(
    pair: str,
    span: str,
    resample_rule: str,
    fast: int,
    slow: int,
    poll_sec: int,
    heartbeat_sec: int,
    live_log: Optional[str] = None,
    closed_only_log: Optional[str] = None,  # пришёл из app.py — игнорируем в observe
) -> None:
    """
    Лайв-наблюдение без торговли: печатаем тики/режим и логируем в CSV без дублей.
    'closed_only_log' принимается для совместимости, но в режиме observe не используется.
    """
    cfg = ObserveConfig(
        pair=pair,
        span=span,
        resample_rule=resample_rule or "",
        fast=fast,
        slow=slow,
        poll_sec=max(1, int(poll_sec or 10)),
        heartbeat_sec=max(5, int(heartbeat_sec or 60)),
        live_log=live_log or None,
        closed_only_log=closed_only_log or None,
    )

    resample_label = cfg.resample_rule if cfg.resample_rule else "—"
    print(
        f"[live] observe {cfg.pair} {cfg.span} resample={resample_label} "
        f"fast={cfg.fast} slow={cfg.slow} poll={cfg.poll_sec}s"
    )

    header = ["time", "close", "volume", "sma_fast", "sma_slow", "signal"]
    last_logged_ts: Optional[pd.Timestamp] = None
    last_hb = time.time()

    while True:
        # 1) Берём сырые свечи
        df_raw = fetch_exmo_candles(cfg.pair, cfg.span)  # ожидаем time, open, high, low, close, volume (UTC)

        # 2) Ресемплинг (если есть) + нормализация времени в колонку
        if cfg.resample_rule:
            dfr = resample_ohlcv(df_raw, rule=cfg.resample_rule)
        else:
            dfr = df_raw

        dfr = _ensure_time_column(dfr)

        if len(dfr) < max(cfg.fast, cfg.slow, 2):
            now = time.time()
            if now - last_hb >= cfg.heartbeat_sec:
                print("[live] hb (warming up...)")
                last_hb = now
            time.sleep(cfg.poll_sec)
            continue

        # 3) Сигналы SMA
        dfr = dfr.copy()
        dfr["sma_fast"] = _compute_sma(dfr["close"], cfg.fast)
        dfr["sma_slow"] = _compute_sma(dfr["close"], cfg.slow)

        sub = dfr.tail(2).reset_index(drop=True)
        ts = pd.to_datetime(sub.loc[len(sub) - 1, "time"], utc=True)
        close = float(sub.loc[len(sub) - 1, "close"])
        vol = float(sub.loc[len(sub) - 1, "volume"])
        f_now = float(sub.loc[len(sub) - 1, "sma_fast"])
        s_now = float(sub.loc[len(sub) - 1, "sma_slow"])
        if len(sub) >= 2:
            f_prev = float(sub.loc[len(sub) - 2, "sma_fast"])
            s_prev = float(sub.loc[len(sub) - 2, "sma_slow"])
        else:
            f_prev, s_prev = f_now, s_now

        signal = "none"
        if (f_now > s_now) and (f_prev <= s_prev):
            signal = "buy"
        elif (f_now < s_now) and (f_prev >= s_prev):
            signal = "sell"

        # 4) Консоль
        print(f"[live] {_iso(ts)} tick  close={close:.6f}  f={f_now:.6f}  s={s_now:.6f}")

        # 5) CSV: одна строка на бар (антидубль по ts)
        if cfg.live_log:
            if (last_logged_ts is None) or (pd.Timestamp(ts) != pd.Timestamp(last_logged_ts)):
                _append_csv_row(
                    cfg.live_log,
                    header,
                    [
                        _iso(ts),
                        f"{close:.8f}",
                        f"{vol:.8f}",
                        f"{f_now:.8f}",
                        f"{s_now:.8f}",
                        signal,
                    ],
                )
                last_logged_ts = ts

        # 6) Heartbeat только в консоль
        now = time.time()
        if now - last_hb >= cfg.heartbeat_sec:
            print(f"[live] hb @ {_iso(pd.Timestamp.utcnow())}")
            last_hb = now

        time.sleep(cfg.poll_sec)
