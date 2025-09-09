# src/backtest/compat.py
from __future__ import annotations

import time
import requests
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass


# === Existing functions (already working) ===

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
                    return pd.DataFrame()

                # Создаем DataFrame
                df = pd.DataFrame(candles)
                df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

                # Конвертируем типы
                df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

                # Создаем datetime index
                df.index = pd.to_datetime(df['timestamp'], unit='s', utc=True)

                return df.dropna()

        # Неожиданный формат ответа
        print(f"EXMO API unexpected response format: {str(data)[:100]}")
        return pd.DataFrame()

    except requests.exceptions.RequestException as e:
        print(f"EXMO API request failed: {e}")
        return pd.DataFrame()
    except Exception as e:
        print(f"EXMO API processing error: {e}")
        return pd.DataFrame()


def normalize_resample_rule(rule: str) -> str:
    """Normalize resample rule to pandas format"""
    r = (rule or "").strip().lower()
    if not r:
        return "5min"
    if r.endswith("m"):
        return f"{int(r[:-1])}min"
    if r.endswith("h"):
        return f"{int(r[:-1])}H"
    if r.endswith("d"):
        return f"{int(r[:-1])}D"
    return r


def resample_ohlc(df: Any, rule: str) -> pd.DataFrame:
    """Минимальный ресемплинг для тестов: поддержка Series/DF с колонкой close или OHLCV."""
    rr = normalize_resample_rule(rule)
    if isinstance(df, pd.Series):
        s = pd.to_numeric(df, errors="coerce")
        out = s.resample(rr).last().to_frame("close").dropna()
        return out
    if isinstance(df, pd.DataFrame):
        cols = set(df.columns)
        if {"open", "high", "low", "close", "volume"}.issubset(cols):
            agg = {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
            return df.resample(rr).agg(agg).dropna(how="all")
        if "close" in cols:
            s = pd.to_numeric(df["close"], errors="coerce")
            return s.resample(rr).last().to_frame("close").dropna()
    raise TypeError("resample_ohlc: unsupported input type")


# === Missing functions that need to be implemented ===

@dataclass
class SimConfig:
    """Configuration for simulation/backtest"""
    pair: str
    span: str
    resample: str
    fast: int
    slow: int
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    fee_bps: int = 10
    slip_bps: int = 5
    qty_eur: float = 100.0
    max_daily_loss_bps: int = 0


def build_bt_config(
        pair: str,
        span: str,
        resample: str,
        fast: int,
        slow: int,
        hysteresis_bps: int = 0,
        cooldown_bars: int = 0,
        qty_eur: float = 100.0,
        fee_bps: int = 10,
        slip_bps: int = 5,
        max_daily_loss_bps: int = 0,
) -> Dict[str, Any]:
    """Build backtest configuration dictionary"""
    return {
        "pair": pair,
        "span": span,
        "resample": resample,
        "fast": fast,
        "slow": slow,
        "hysteresis_bps": hysteresis_bps,
        "cooldown_bars": cooldown_bars,
        "qty_eur": qty_eur,
        "fee_bps": fee_bps,
        "slip_bps": slip_bps,
        "max_daily_loss_bps": max_daily_loss_bps,
    }


def normalize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize metrics to standard format"""
    normalized = dict(metrics)

    # Ensure standard metric names exist
    standard_metrics = [
        "total_return_pct", "max_drawdown_pct", "sharpe", "calmar",
        "profit_factor", "winrate_pct", "avg_trade_eur", "trades"
    ]

    for metric in standard_metrics:
        if metric not in normalized:
            normalized[metric] = 0.0

    # Add any DataFrames as-is (trades_df, equity_df)
    return normalized


def simulate_on_df(df: pd.DataFrame, config: Dict[str, Any]) -> Dict[str, Any]:
    """Simple SMA crossover simulation on DataFrame"""
    if df.empty:
        return {"trades": 0, "total_return_pct": 0.0, "error": "Empty DataFrame"}

    fast = config.get("fast", 10)
    slow = config.get("slow", 30)
    qty_eur = config.get("qty_eur", 100.0)
    fee_bps = config.get("fee_bps", 10)

    # Calculate SMAs
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < max(fast, slow):
        return {"trades": 0, "total_return_pct": 0.0, "error": "Insufficient data"}

    sma_fast = close.rolling(fast).mean()
    sma_slow = close.rolling(slow).mean()

    # Generate signals
    signals = np.where(sma_fast > sma_slow, 1, -1)
    signal_changes = np.diff(signals, prepend=signals[0])

    # Simulate trades
    trades = []
    position = 0
    entry_price = 0
    cash = 1000.0  # Starting cash

    for i, (ts, price, signal_change) in enumerate(zip(df.index, close, signal_changes)):
        if signal_change == 2 and position == 0:  # Buy signal
            shares = (cash * 0.95) / price  # 95% investment, leave some for fees
            fee = shares * price * (fee_bps / 10000)
            cash -= (shares * price + fee)
            position = shares
            entry_price = price

        elif signal_change == -2 and position > 0:  # Sell signal
            proceeds = position * price
            fee = proceeds * (fee_bps / 10000)
            cash += (proceeds - fee)

            trades.append({
                "entry_price": entry_price,
                "exit_price": price,
                "qty": position,
                "pnl": proceeds - (position * entry_price)
            })

            position = 0

    # Calculate metrics
    total_value = cash + (position * close.iloc[-1] if position > 0 else 0)
    total_return_pct = ((total_value / 1000.0) - 1) * 100

    return {
        "trades": len(trades),
        "total_return_pct": total_return_pct,
        "final_value": total_value,
        "cash": cash,
        "position": position,
        "trades_list": trades
    }


def run_backtest_compat(bt_cfg: Dict[str, Any], write_csv: bool = False) -> Dict[str, Any]:
    """Run backtest with compatibility wrapper"""
    try:
        # Fetch data
        df = fetch_exmo_candles_cached(bt_cfg["pair"], bt_cfg["span"])
        if df.empty:
            return {"trades": 0, "total_return_pct": 0.0, "error": "No data"}

        # Resample if needed
        if bt_cfg.get("resample"):
            df = resample_ohlc(df, bt_cfg["resample"])

        # Run simulation
        result = simulate_on_df(df, bt_cfg)

        # Add config info to result
        result["config"] = bt_cfg
        result["bars"] = len(df)

        # Optional: create DataFrames for compatibility
        if write_csv and result.get("trades_list"):
            trades_df = pd.DataFrame(result["trades_list"])
            result["trades_df"] = trades_df

        return result

    except Exception as e:
        return {"trades": 0, "total_return_pct": 0.0, "error": str(e)}


# Aliases for backward compatibility
_normalize_resample_rule = normalize_resample_rule
_resample_ohlc = resample_ohlc