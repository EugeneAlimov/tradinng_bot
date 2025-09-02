# src/backtest/registry.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd

BuildResult = Tuple[List[Dict[str, Any]], np.ndarray]


# ---------- indicators ----------
def _ema(x: pd.Series, span: int) -> pd.Series:
    return x.ewm(span=span, adjust=False).mean()


def _adx_pdi_mdi(df: pd.DataFrame, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)

    tr = np.maximum(high[1:], close[:-1]) - np.minimum(low[1:], close[:-1])
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]

    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    n = max(2, int(length))

    def wilder_smooth(x: np.ndarray, n: int) -> np.ndarray:
        out = np.empty_like(x, dtype=float)
        out[:n] = np.nan
        s = np.nansum(x[:n])
        out[n] = s
        for i in range(n + 1, len(x)):
            s = s - (s / n) + x[i]
            out[i] = s
        return out

    tr_n = wilder_smooth(tr, n)
    plus_dm_n = wilder_smooth(plus_dm, n)
    minus_dm_n = wilder_smooth(minus_dm, n)

    plus_di = 100.0 * (plus_dm_n / tr_n)
    minus_di = 100.0 * (minus_dm_n / tr_n)
    dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

    adx = np.empty(len(df))
    adx[:] = np.nan
    adx[1 + n:] = pd.Series(dx[n:]).rolling(window=n, min_periods=1).mean().to_numpy()

    pad = np.array([np.nan] * (len(df) - len(plus_di) - 1))
    pdi = np.concatenate(([np.nan], plus_di, pad))
    mdi = np.concatenate(([np.nan], minus_di, pad))
    return (pd.Series(adx, index=df.index),
            pd.Series(pdi, index=df.index),
            pd.Series(mdi, index=df.index))


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(2, int(length)), adjust=False).mean()


# ---------- tiny long-only backtester ----------
def _bt_long(df: pd.DataFrame, entry: pd.Series, exit_: pd.Series) -> BuildResult:
    entry = entry.fillna(False).astype(bool)
    exit_ = exit_.fillna(False).astype(bool)
    trades: List[Dict[str, Any]] = []
    pnls: List[float] = []

    in_pos = False
    ent_i = None
    ent_price = None

    for i in range(len(df)):
        if not in_pos and entry.iat[i]:
            in_pos = True
            ent_i = i
            ent_price = float(df["close"].iat[i])
        elif in_pos:
            if exit_.iat[i]:
                ex_price = float(df["close"].iat[i])
                pnl = (ex_price - ent_price) / ent_price
                trades.append({
                    "entry_idx": ent_i,
                    "exit_idx": i,
                    "entry_dt": str(df["dt"].iat[ent_i]) if "dt" in df.columns else ent_i,
                    "exit_dt": str(df["dt"].iat[i]) if "dt" in df.columns else i,
                    "entry": ent_price,
                    "exit": ex_price,
                    "pnl": pnl,
                })
                pnls.append(float(pnl))
                in_pos = False
                ent_i = None
                ent_price = None

    return trades, np.asarray(pnls, dtype=float)


# ---------- strategies ----------
def _ema_adx_core(df: pd.DataFrame, params: Dict[str, Any]) -> BuildResult:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 21))
    adx_len = int(params.get("adx_len", 14))
    on = float(params.get("on", 25.0))
    off = float(params.get("off", 16.0))
    require_di = bool(params.get("require_di", False))

    close = df["close"]
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    adx, pdi, mdi = _adx_pdi_mdi(df, adx_len)

    if require_di:
        go = (ema_fast > ema_slow) & (adx >= on) & (pdi > mdi)
        stp = (ema_fast < ema_slow) | (adx <= off) | (pdi <= mdi)
    else:
        go = (ema_fast > ema_slow) & (adx >= on)
        stp = (ema_fast < ema_slow) | (adx <= off)

    return _bt_long(df, go, stp)


def build_ema_adx(df: pd.DataFrame, params: Dict[str, Any]) -> BuildResult:
    return _ema_adx_core(df, params)


def build_ema_adx_atr(df: pd.DataFrame, params: Dict[str, Any]) -> BuildResult:
    # ATR считается (для возможных стопов), но логика вход/выход такая же, чтобы было предсказуемо.
    atr_len = int(params.get("atr_len", 14))
    _ = _atr(df, atr_len)  # сейчас не используем для выхода — можно расширить при желании
    return _ema_adx_core(df, params)


# ---------- registry ----------
def get_registry_builder() -> Dict[str, Any]:
    return {
        "ema_adx": build_ema_adx,
        "ema_adx_atr": build_ema_adx_atr,
    }


def get_default_grid() -> Dict[str, List[Dict[str, Any]]]:
    """
    Небольшая, но осмысленная сетка параметров.
    - несколько пар EMA (fast < slow),
    - 3 набора порогов ADX,
    - с/без require_di,
    - для ema_adx_atr также два atr_len.
    """
    grid_ema: List[Dict[str, Any]] = []
    for fast in [8, 12, 16]:
        for slow in [21, 34, 55]:
            if fast >= slow:
                continue
            for (on, off) in [(20.0, 14.0), (25.0, 16.0), (30.0, 18.0)]:
                for require_di in [False, True]:
                    grid_ema.append({
                        "fast": fast, "slow": slow,
                        "adx_len": 14, "on": on, "off": off,
                        "require_di": require_di,
                    })

    grid_atr: List[Dict[str, Any]] = []
    for base in grid_ema:
        for atr_len in [14, 21]:
            p = dict(base)
            p["atr_len"] = atr_len
            grid_atr.append(p)

    return {
        "ema_adx": grid_ema,
        "ema_adx_atr": grid_atr,
    }
