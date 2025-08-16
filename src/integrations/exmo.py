# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Optional
import time as _time
import re

import numpy as np
import pandas as pd
import requests


def normalize_resample_rule(rule: str) -> str:
    """
    Превращает '5m','15m','1h','1d' в pandas-совместимое:
      5m -> 5min, 1h -> 1H, 1d -> 1D.
    Также конвертирует устаревшее 'T' -> 'min', чтобы не ловить FutureWarning.
    """
    if not rule:
        return rule
    s = rule.strip()
    # уже валидные варианты: 5min, 1H, 1D, 30S, 250MS
    if re.fullmatch(r"\d+\s*(min|H|D|S|MS)", s, flags=re.IGNORECASE):
        return s.upper().replace("MIN", "min")
    # человеческие: 5m, 1h, 1d, 30s, 250ms
    m = re.fullmatch(r"\s*(\d+)\s*([mhd]|s|ms)\s*", s, flags=re.IGNORECASE)
    if m:
        n, u = m.groups()
        u = u.lower()
        if u == "m":  return f"{n}min"
        if u == "h":  return f"{n}H"
        if u == "d":  return f"{n}D"
        if u == "s":  return f"{n}S"
        if u == "ms": return f"{n}MS"
    # устаревшее 'T'
    m = re.fullmatch(r"\s*(\d+)\s*T\s*", s, flags=re.IGNORECASE)
    if m:
        return f"{m.group(1)}min"
    return s


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


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Ресемпл OHLCV по правилу pandas (после normalize_resample_rule):
      - open: first, high: max, low: min, close: last, volume: sum.
    """
    rule = normalize_resample_rule(rule)
    if not rule:
        return df.copy()
    if df.empty:
        return df.copy()

    d = df.set_index("time")
    o = d["open"].resample(rule).first()
    h = d["high"].resample(rule).max()
    l = d["low"].resample(rule).min()
    c = d["close"].resample(rule).last()
    v = d["volume"].resample(rule).sum()
    out = pd.concat([o, h, l, c, v], axis=1).dropna()
    out.reset_index(inplace=True)
    return out
