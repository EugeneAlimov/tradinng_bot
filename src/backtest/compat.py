# Исправление для src/backtest/compat.py или где вызывается fetch_exmo_candles_cached

import time
import requests
import pandas as pd
import numpy as np
from typing import Optional


def fetch_exmo_candles_cached(pair: str, span: str) -> pd.DataFrame:
    """
    Исправленная функция для получения свечей EXMO с правильными параметрами
    """
    try:
        tf, count = span.split(":")
        count = int(count)
    except ValueError:
        raise ValueError(f"Bad span format: {span}. Expected 'tf:count', e.g. '1m:720'")

    # Конвертируем timeframe в минуты для resolution
    tf = tf.strip().lower()
    if tf.endswith("m"):
        resolution = int(tf[:-1])
    elif tf.endswith("h"):
        resolution = int(tf[:-1]) * 60
    elif tf.endswith("d"):
        resolution = int(tf[:-1]) * 1440
    else:
        raise ValueError(f"Unsupported timeframe: {tf}")

    # Вычисляем временные рамки
    current_time = int(time.time())
    period_seconds = resolution * 60
    from_time = current_time - (count * period_seconds)
    to_time = current_time

    # Правильные параметры для EXMO API
    url = "https://api.exmo.com/v1.1/candles_history"
    params = {
        "symbol": pair,
        "resolution": resolution,
        "from": from_time,
        "to": to_time
    }

    try:
        response = requests.get(url, params=params, timeout=20)

        if response.status_code != 200:
            print(f"EXMO API HTTP error {response.status_code}: {response.text[:100]}")
            return pd.DataFrame()

        data = response.json()

        # Проверяем на ошибки API
        if isinstance(data, dict):
            if data.get('result') == False and 'error' in data:
                print(f"EXMO API error: {data['error']}")
                return pd.DataFrame()
            elif data.get('s') == 'error':
                print(f"EXMO API error: {data.get('errmsg', 'unknown')}")
                return pd.DataFrame()
            elif 'candles' in data:
                # Успешный ответ
                candles = data['candles']
                if not candles:
                    print(f"EXMO returned empty candles for {pair}")
                    return pd.DataFrame()

                # Обрабатываем данные
                df = pd.DataFrame(candles)

                # Переименовываем колонки
                df = df.rename(columns={
                    "t": "timestamp",
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "v": "volume"
                })

                # Конвертируем в числовые типы
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                # Обрабатываем timestamp (миллисекунды -> секунды)
                ts = pd.to_numeric(df["timestamp"], errors="coerce")
                if ts.max() > 10_000_000_000:  # миллисекунды
                    ts = ts / 1000.0

                # Создаем datetime index
                df["dt"] = pd.to_datetime(ts, unit="s", utc=True)
                df = df.set_index("dt").sort_index()

                # Удаляем дубликаты
                df = df[~df.index.duplicated(keep='first')]

                # Возвращаем нужные колонки
                return df[["open", "high", "low", "close", "volume"]].dropna()

        print(f"EXMO unexpected response format: {type(data)}")
        return pd.DataFrame()

    except Exception as e:
        print(f"EXMO API request failed: {e}")
        return pd.DataFrame()


# Альтернативно, если нужно исправить конкретно _fetch_exmo_ohlc в engine.py
def _fetch_exmo_ohlc_fixed(args, pair: str, candles: str) -> pd.DataFrame:
    """
    Исправленная версия _fetch_exmo_ohlc для engine.py
    """
    try:
        tf, n = candles.split(":")
        n = int(n)
    except Exception as e:
        print(f"Bad --candles: {e}")
        return pd.DataFrame()

    # Маппинг timeframes
    periods = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

    if tf not in periods:
        print(f"Unsupported timeframe '{tf}'")
        return pd.DataFrame()

    period = periods[tf]
    resolution = period // 60  # минуты

    # Временные рамки
    t_to = int(time.time())
    t_from = t_to - n * period

    # API запрос с правильными параметрами
    url = "https://api.exmo.com/v1.1/candles_history"
    params = {
        "symbol": pair,
        "resolution": resolution,
        "from": t_from,
        "to": t_to
    }

    try:
        response = requests.get(url, params=params, timeout=20)

        if response.status_code != 200:
            print(f"[exmo] HTTP {response.status_code}: {response.text[:100]}")
            return pd.DataFrame()

        data = response.json()

        # Проверка на ошибки
        if not isinstance(data, dict) or 'candles' not in data:
            print(f"[exmo] bad response: {data}")
            return pd.DataFrame()

        candles = data['candles']
        if not candles:
            print(f"[exmo] empty candles for {pair}")
            return pd.DataFrame()

        # Обрабатываем данные как в оригинальном коде
        df = pd.DataFrame(candles)
        df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})

        for c in ("open", "high", "low", "close", "volume"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        ts = pd.to_numeric(df["timestamp"], errors="coerce").astype("Int64").to_numpy(dtype="float64")
        if np.nanmean(ts) > 10_000_000_000:  # ms → s
            ts = ts / 1000.0

        df["timestamp"] = ts.astype("int64", copy=False)
        df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.sort_values("dt").drop_duplicates(subset=["dt"]).reset_index(drop=True)

        # Sanity check for high/low
        if {"open", "high", "low", "close"}.issubset(df.columns):
            hi = df[["open", "close"]].max(axis=1)
            lo = df[["open", "close"]].min(axis=1)
            df["high"] = df["high"].fillna(hi).where(df["high"] >= hi, hi)
            df["low"] = df["low"].fillna(lo).where(df["low"] <= lo, lo)

        print(f"[exmo] success: {len(df)} candles for {pair}")
        return df[["dt", "timestamp", "open", "high", "low", "close", "volume"]]

    except Exception as e:
        print(f"[exmo] request failed: {e}")
        return pd.DataFrame()
