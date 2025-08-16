# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Optional
import time as _time
import re

import numpy as np
import pandas as pd
import requests


def normalize_resample_rule(rule: Optional[str]) -> Optional[str]:
    """
    Приводит пользовательский ввод вроде '5m'/'5T'/'5min' к безопасному правилу pandas.
    Возвращает None, если ресемпл отключён.
    """
    if not rule:
        return None
    r = str(rule).strip().lower()
    if r in ("", "none", "false", "0"):
        return None

    # '5m' часто путают с месяцами; нам нужны минуты -> '5min'
    if r.endswith("m") and not r.endswith("min"):
        try:
            val = int(r[:-1])
            return f"{val}min"
        except Exception:
            pass

    # Старый алиас минут 'T' -> 'min'
    if r.endswith("t"):
        try:
            val = int(r[:-1])
            return f"{val}min"
        except Exception:
            pass

    # Если уже 'min', 'h', 'd' и т.п. — оставляем как есть
    return r


def _parse_exmo_json(payload: Any) -> pd.DataFrame:
    """
    Превращает ответ EXMO candles_history в DataFrame.
    Поддерживает поля как в массивах, так и в словаре {"candles": [...]}.
    Колонки: time(UTC tz-aware), open, high, low, close, volume.
    """
    data = (isinstance(payload, dict) and (payload.get("candles") or payload.get("data"))) \
           or (payload if isinstance(payload, list) else None)
    if not isinstance(data, list) or not data:
        return pd.DataFrame()

    rows: List[list] = []
    for it in data:
        t = it.get("t", it.get("time"))
        o = it.get("o", it.get("open"))
        h = it.get("h", it.get("high"))
        l = it.get("l", it.get("low"))
        c = it.get("c", it.get("close"))
        v = it.get("v", it.get("volume"))
        rows.append([t, o, h, l, c, v])

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df

    # числовые колонки
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # time: сек или мс -> сек
    tvals = pd.to_numeric(df["time"], errors="coerce")
    if tvals.max() > 1e12:  # миллисекунды
        tvals = (tvals / 1000.0).astype(np.int64)
    else:
        tvals = tvals.astype(np.int64)

    df["time"] = pd.to_datetime(tvals, unit="s", utc=True)
    return df.sort_values("time").reset_index(drop=True)


def fetch_exmo_candles(symbol: str, span: str, *, verbose: bool = True) -> pd.DataFrame:
    """
    Стабильная загрузка последних N свечей EXMO с бэкапными стратегиями:
      - Чанки до 2000 шт.
      - Пробуем limit+to, потом from+to, потом просто limit.
      - Не бросает исключение, если свечи не пришли — вернёт пустой DF с нужными колонками.
    Аргументы:
      symbol: 'DOGE_EUR'
      span:   '1m:5000', '5m:1000', '1h:720', ...
    Возвращает DataFrame с колонками: time(UTC), open, high, low, close, volume.
    """
    try:
        tf_raw, cnt_raw = span.split(":")
    except ValueError:
        raise ValueError(f"Bad exmo-candles span: {span!r}. Expected like '1m:600'.")

    tf_raw = tf_raw.strip().lower()
    want = int(cnt_raw)

    if tf_raw.endswith("m"):
        tf_sec = int(tf_raw[:-1]) * 60
        res_min = int(tf_raw[:-1])
    elif tf_raw.endswith("h"):
        tf_sec = int(tf_raw[:-1]) * 3600
        res_min = int(tf_raw[:-1]) * 60
    elif tf_raw.endswith("d"):
        tf_sec = int(tf_raw[:-1]) * 86400
        res_min = int(tf_raw[:-1]) * 1440
    else:
        raise ValueError(f"Unsupported timeframe: {tf_raw!r}")

    BASES = [
        "https://api.exmo.com/v1.1/candles_history",
        "https://api.exmo.me/v1.1/candles_history",
    ]
    MAX_PER_CALL = 2000

    def _try(params: Dict[str, Any]) -> pd.DataFrame:
        last_err: Optional[Exception] = None
        for base in BASES:
            try:
                r = requests.get(base, params=params, timeout=15)
                if r.status_code != 200:
                    last_err = RuntimeError(f"HTTP {r.status_code}")
                    continue
                dfc = _parse_exmo_json(r.json())
                if not dfc.empty:
                    return dfc
            except Exception as e:
                last_err = e
                continue
        # возвращаем пусто; пусть наружный код решает, что делать
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    remaining = int(want)
    to_ts = int(_time.time())
    safety_loops = 0

    while remaining > 0 and safety_loops < 40:
        take = min(remaining, MAX_PER_CALL)
        frm = to_ts - take * tf_sec

        # A) limit + to
        dfc = _try({"symbol": symbol, "resolution": res_min, "limit": int(take), "to": int(to_ts)})
        if dfc.empty:
            # B) from + to
            dfc = _try({"symbol": symbol, "resolution": res_min, "from": int(frm), "to": int(to_ts)})
            if dfc.empty:
                # C) fallback: только limit (последние)
                dfc = _try({"symbol": symbol, "resolution": res_min, "limit": int(take)})
                if dfc.empty:
                    break

        frames.append(dfc)
        remaining -= len(dfc)
        # следующий чанк уводим назад
        to_ts = int(dfc["time"].iloc[0].timestamp()) - tf_sec
        safety_loops += 1

    if not frames:
        if verbose:
            print(f"[exmo] warning: no candles for {symbol} {span} (returning empty).")
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    out = pd.concat(frames, axis=0, ignore_index=True)
    out = out.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    if len(out) > want:
        out = out.iloc[-want:].reset_index(drop=True)
    return out[["time", "open", "high", "low", "close", "volume"]]


def resample_ohlcv(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    """
    Ресемпл OHLCV с поддержкой:
      - входа с DatetimeIndex ИЛИ с колонкой 'time'
      - таймзоны (приводим к UTC)
      - корректной агрегации: O=first, H=max, L=min, C=last, V=sum

    Возвращает новый DataFrame с теми же колонками (volume опциональна).
    """
    rule_n = normalize_resample_rule(rule)
    if not rule_n:
        return df.copy()

    dfi = df.copy()

    # Гарантируем DatetimeIndex
    if not isinstance(dfi.index, pd.DatetimeIndex):
        if "time" in dfi.columns:
            dfi["time"] = pd.to_datetime(dfi["time"], utc=True, errors="coerce")
            dfi = dfi.set_index("time")
        else:
            raise KeyError("resample_ohlcv: need DatetimeIndex or 'time' column")

    # Таймзона -> UTC
    if dfi.index.tz is None:
        dfi.index = dfi.index.tz_localize("UTC")
    else:
        dfi.index = dfi.index.tz_convert("UTC")

    dfi = dfi.sort_index()

    # Проверяем необходимые колонки
    need_cols = ["open", "high", "low", "close"]
    for c in need_cols:
        if c not in dfi.columns:
            raise KeyError(f"resample_ohlcv: missing column '{c}'")

    has_vol = "volume" in dfi.columns

    o = dfi["open"].resample(rule_n).first()
    h = dfi["high"].resample(rule_n).max()
    l = dfi["low"].resample(rule_n).min()
    c = dfi["close"].resample(rule_n).last()

    if has_vol:
        v = dfi["volume"].resample(rule_n).sum()
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    else:
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})

    # Убираем полностью пустые бары (в случае дыр в данных)
    out = out.dropna(how="all")
    return out
