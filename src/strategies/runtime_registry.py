# src/strategies/runtime_registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple, Any

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame, Dict[str, Any]], Tuple[str, Dict[str, float]]]


def _ema(a: pd.Series, span: int) -> pd.Series:
    return a.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    a = (df["high"] - df["low"]).abs()
    b = (df["high"] - prev_close).abs()
    c = (df["low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = _true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    # классическая реализация + EMA сглаживание
    high = df["high"]
    low = df["low"]
    close = df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    tr = _true_range(df)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + 1e-12))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + 1e-12))
    dx = (100 * (plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-12)).fillna(0.0)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx


# === стратегии ===

def sig_ema_cross(df: pd.DataFrame, p: Dict[str, Any]) -> Tuple[str, Dict[str, float]]:
    fast = int(p.get("fast", 10))
    slow = int(p.get("slow", 20))
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    if close.empty:
        return "FLAT", {"ema_fast": float("nan"), "ema_slow": float("nan")}
    side = "LONG" if ema_f.iat[-1] > ema_s.iat[-1] else "SHORT"
    return side, {
        "ema_fast": float(ema_f.iat[-1]),
        "ema_slow": float(ema_s.iat[-1]),
    }


def sig_rsi(df: pd.DataFrame, p: Dict[str, Any]) -> Tuple[str, Dict[str, float]]:
    period = int(p.get("period", 14))
    buy_th = float(p.get("buy", 30))
    sell_th = float(p.get("sell", 70))
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    r = _rsi(close, period)
    if r.empty:
        return "FLAT", {"rsi": float("nan")}
    last = float(r.iat[-1])
    if last < buy_th:
        side = "LONG"
    elif last > sell_th:
        side = "SHORT"
    else:
        side = "FLAT"
    return side, {"rsi": last}


def sig_macd(df: pd.DataFrame, p: Dict[str, Any]) -> Tuple[str, Dict[str, float]]:
    fast = int(p.get("fast", 12))
    slow = int(p.get("slow", 26))
    sig = int(p.get("signal", 9))
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    macd = ema_f - ema_s
    macd_sig = _ema(macd, sig)
    hist = macd - macd_sig
    if macd.empty:
        return "FLAT", {"macd": float("nan"), "signal": float("nan"), "hist": float("nan")}
    side = "LONG" if hist.iat[-1] > 0 else "SHORT"
    return side, {"macd": float(macd.iat[-1]), "signal": float(macd_sig.iat[-1]), "hist": float(hist.iat[-1])}


def sig_ema_adx_atr(df: pd.DataFrame, p: Dict[str, Any]) -> Tuple[str, Dict[str, float]]:
    # простая версия: фильтруем EMA-кросс ADX-порогом
    fast = int(p.get("fast", 10))
    slow = int(p.get("slow", 20))
    adx_p = int(p.get("adx_period", 14))
    adx_th = float(p.get("adx_th", 20))
    atr_p = int(p.get("atr_period", 14))

    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    adx = _adx(df, adx_p)
    atr = _atr(df, atr_p)

    if close.empty:
        return "FLAT", {"ema_fast": float("nan"), "ema_slow": float("nan"), "adx": float("nan"), "atr": float("nan")}

    cross_long = ema_f.iat[-1] > ema_s.iat[-1]
    side = "LONG" if (cross_long and adx.iat[-1] >= adx_th) else "SHORT"
    return side, {
        "ema_fast": float(ema_f.iat[-1]),
        "ema_slow": float(ema_s.iat[-1]),
        "adx": float(adx.iat[-1]),
        "atr": float(atr.iat[-1]),
    }


@dataclass
class StrategySpec:
    name: str
    fn: SignalFn
    defaults: Dict[str, Any]


class StrategyRegistry:
    def __init__(self) -> None:
        self._map: Dict[str, StrategySpec] = {}
        self.register("ema_cross", sig_ema_cross, {"fast": 10, "slow": 20})
        self.register("rsi", sig_rsi, {"period": 14, "buy": 30, "sell": 70})
        self.register("macd", sig_macd, {"fast": 12, "slow": 26, "signal": 9})
        self.register("ema_adx_atr", sig_ema_adx_atr,
                      {"fast": 10, "slow": 20, "adx_period": 14, "adx_th": 20, "atr_period": 14})

    def register(self, name: str, fn: SignalFn, defaults: Dict[str, Any] | None = None) -> None:
        key = name.strip().lower()
        self._map[key] = StrategySpec(name=key, fn=fn, defaults=defaults or {})

    def resolve(self, name: str | None) -> StrategySpec:
        if not name:
            return self._map["ema_cross"]
        key = name.strip().lower()
        return self._map.get(key, self._map["ema_cross"])

    def names(self) -> list[str]:
        return sorted(self._map.keys())


# singleton
registry = StrategyRegistry()
