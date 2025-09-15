# src/strategies/runtime_registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple, Any

import numpy as np
import pandas as pd

Side = str  # "LONG" | "SHORT" | "FLAT"
SignalFn = Callable[[pd.DataFrame, Dict[str, Any]], Tuple[Side, Dict[str, float]]]


def _ema(a: pd.Series, span: int) -> pd.Series:
    return a.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
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
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _dx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    # +DM / -DM
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move

    tr = _true_range(df)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / (atr + 1e-12))
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / (atr + 1e-12))

    dx = 100 * ( (plus_di - minus_di).abs() / ((plus_di + minus_di).replace(0, np.nan)) )
    return dx.fillna(0.0)


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _dx(df, period=period).ewm(alpha=1/period, adjust=False).mean()


# ---- Стратегии -------------------------------------------------------------
def _ema_cross(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[Side, Dict[str, float]]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    price = df["close"]
    ema_fast = _ema(price, fast)
    ema_slow = _ema(price, slow)
    last_fast = float(ema_fast.iloc[-1])
    last_slow = float(ema_slow.iloc[-1])
    side: Side = "LONG" if last_fast > last_slow else ("SHORT" if last_fast < last_slow else "FLAT")
    return side, {"ema_fast": last_fast, "ema_slow": last_slow}


def _rsi_basic(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[Side, Dict[str, float]]:
    length = int(params.get("length", 14))
    low_th = float(params.get("low", 30))
    high_th = float(params.get("high", 70))
    rsi = _rsi(df["close"], length)
    r = float(rsi.iloc[-1])
    if r < low_th:
        side: Side = "LONG"
    elif r > high_th:
        side = "SHORT"
    else:
        side = "FLAT"
    return side, {"rsi": r}


def _macd_cross(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[Side, Dict[str, float]]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    price = df["close"]
    ema_fast = _ema(price, fast)
    ema_slow = _ema(price, slow)
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    last_macd = float(macd.iloc[-1])
    last_sig = float(sig.iloc[-1])
    side: Side = "LONG" if last_macd > last_sig else ("SHORT" if last_macd < last_sig else "FLAT")
    return side, {"macd": last_macd, "signal": last_sig}


def _ema_adx_atr(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[Side, Dict[str, float]]:
    # базовый EMA-кросс
    side, details = _ema_cross(df, params)
    # ADX-фильтр
    adx_len = int(params.get("adx_len", 14))
    on = float(params.get("adx_th", params.get("on", 20)))   # допускаем оба имени
    off = float(params.get("off", max(on - 4, 10)))
    adx = _adx(df, adx_len)
    last_adx = float(adx.iloc[-1])

    # ATR в метриках (например, для пост-обработки стопов)
    atr_len = int(params.get("atr_len", 14))
    atr = _atr(df, atr_len)
    last_atr = float(atr.iloc[-1])

    # гистерезисная логика включения/выключения по ADX
    trending = df.attrs.get("_trending", False)
    if last_adx >= on:
        trending = True
    elif last_adx <= off:
        trending = False
    df.attrs["_trending"] = trending

    if not trending:
        side_out: Side = "FLAT"
    else:
        side_out = side

    details.update({"adx": last_adx, "atr": last_atr})
    return side_out, details


@dataclass(frozen=True)
class StrategySpec:
    name: str
    fn: SignalFn
    defaults: Dict[str, Any]


class StrategyRegistry:
    def __init__(self) -> None:
        self._map: Dict[str, StrategySpec] = {}
        self._register("ema_cross", _ema_cross, {"fast": 12, "slow": 26})
        self._register("rsi", _rsi_basic, {"length": 14, "low": 30, "high": 70})
        self._register("macd", _macd_cross, {"fast": 12, "slow": 26, "signal": 9})
        self._register("ema_adx_atr", _ema_adx_atr, {"fast": 12, "slow": 26, "adx_len": 14, "on": 22.0, "off": 18.0})

    def _register(self, key: str, fn: SignalFn, defaults: Dict[str, Any]) -> None:
        self._map[key] = StrategySpec(name=key, fn=fn, defaults=defaults or {})

    def resolve(self, name: str | None) -> StrategySpec:
        if not name:
            return self._map["ema_cross"]
        key = name.strip().lower()
        return self._map.get(key, self._map["ema_cross"])

    def names(self) -> list[str]:
        return sorted(self._map.keys())

    def defaults(self, name: str) -> Dict[str, Any]:
        return (self.resolve(name)).defaults.copy()


# singleton
registry = StrategyRegistry()
