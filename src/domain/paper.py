# src/domain/paper.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import math
import numpy as np
import pandas as pd

# ==== Метрики (те же ключи, что и в Selector API) ====
_METRIC_NAMES = ("n_trades", "win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar")


def _empty_metrics() -> Dict[str, float]:
    return {k: 0.0 for k in _METRIC_NAMES} | {"n_trades": 0}


# ==== Простые индикаторы ====
def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=int(length), adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    a = high - low
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(span=int(length), adjust=False).mean()


def dx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)
    tr = _true_range(high, low, close)
    _atr = tr.ewm(span=int(length), adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=int(length), adjust=False).mean() / _atr)
    minus_di = 100 * (minus_dm.ewm(span=int(length), adjust=False).mean() / _atr)
    _dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = _dx.ewm(span=int(length), adjust=False).mean()
    return adx.fillna(0.0), plus_di.fillna(0.0), minus_di.fillna(0.0)


# ==== Стратегия ema_adx (та же логика, что в app.py) ====
@dataclass
class EmaAdxParams:
    fast: int = 12
    slow: int = 21
    adx_len: int = 14
    on: float = 25.0
    off: float = 16.0
    require_di: bool = True
    atr_len: int = 14
    atr_mult: float = 0.0


@dataclass
class PaperConfig:
    fees_bps: float = 10.0  # комиссия, б.п. (0.01% = 1 bps)
    slippage_bps: float = 0.0  # проскальзывание в б.п. на вход/выход
    size: float = 1.0  # условный размер позиции (в «монетах»)
    price_col: str = "close"  # по какой цене исполняем сделки


def _calc_metrics(trades_pnl: List[float]) -> Dict[str, float]:
    if not trades_pnl:
        return _empty_metrics()
    n_trades = len(trades_pnl)
    total_pnl = float(np.sum(trades_pnl))
    avg_pnl = float(np.mean(trades_pnl))
    win_rate = float((np.array(trades_pnl) > 0).mean())
    ret = pd.Series(trades_pnl, dtype=float)
    std = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0
    sharpe = (avg_pnl / std) if std > 0 else 0.0
    # max drawdown по кумулятивной equity
    eq = ret.cumsum()
    peak = eq.cummax()
    dd = (eq - peak).min() if len(eq) else 0.0
    max_dd = float(dd)
    calmar = (total_pnl / abs(max_dd)) if max_dd < 0 else (
        math.copysign(math.inf, total_pnl) if total_pnl != 0 else 0.0)
    return {
        "n_trades": int(n_trades),
        "win_rate": round(win_rate * 100.0, 6),
        "avg_pnl": round(avg_pnl, 6),
        "total_pnl": round(total_pnl, 6),
        "max_dd": round(max_dd, 6),
        "sharpe": round(sharpe, 6),
        "calmar": round(calmar, 6),
    }


def simulate_ema_adx(df: pd.DataFrame, p: EmaAdxParams, cfg: PaperConfig) -> Tuple[
    pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    """
    Возвращает:
      trades_df: dt_entry, dt_exit, px_entry, px_exit, pnl
      equity_df: dt, equity
      metrics:   метрики Selector API
    """
    if df.empty or len(df) < max(p.fast, p.slow, p.adx_len) + 5:
        return (pd.DataFrame(columns=["dt_entry", "dt_exit", "px_entry", "px_exit", "pnl"]),
                pd.DataFrame(columns=["dt", "equity"]), _empty_metrics())

    close = df[cfg.price_col].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    ema_fast = ema(close, p.fast)
    ema_slow = ema(close, p.slow)
    _adx, plus_di, minus_di = dx(high, low, close, p.adx_len)
    _atr = atr(high, low, close, p.atr_len) if p.atr_mult > 0 else pd.Series(0.0, index=close.index)

    pos = 0
    entry_px = 0.0
    trades: List[Dict[str, Any]] = []
    equity: List[Tuple[pd.Timestamp, float]] = []
    eq = 0.0

    fee = cfg.fees_bps / 10000.0
    slip = cfg.slippage_bps / 10000.0

    for i in range(1, len(close)):
        f = ema_fast.iat[i]
        s = ema_slow.iat[i]
        adx_i = _adx.iat[i]
        plus_i = plus_di.iat[i]
        minus_i = minus_di.iat[i]
        c = float(close.iat[i])
        a = float(_atr.iat[i])
        dt_i = df["dt"].iat[i]

        # проскальзывание: считаем что входим/выходим хуже на slip
        ask = c * (1 + slip)
        bid = c * (1 - slip)

        want_long = (f > s) and (adx_i >= p.on)
        if p.require_di:
            want_long = want_long and (plus_i > minus_i)

        exit_signal = (pos == 1 and (adx_i <= p.off or f < s))
        stop_px = entry_px - p.atr_mult * a if (pos == 1 and p.atr_mult > 0) else -np.inf
        hit_stop = (pos == 1 and bid <= stop_px)

        if pos == 0 and want_long:
            # вход по ask + комиссия
            entry_px = ask * (1 + fee)
            pos = 1
            entry_dt = dt_i
        elif pos == 1 and (exit_signal or hit_stop):
            exit_px = bid * (1 - fee)
            pnl = (exit_px - entry_px) * cfg.size
            trades.append({
                "dt_entry": entry_dt,
                "dt_exit": dt_i,
                "px_entry": round(entry_px, 8),
                "px_exit": round(exit_px, 8),
                "pnl": round(pnl, 8),
                "stop": bool(hit_stop),
            })
            eq += pnl
            pos = 0
            entry_px = 0.0

        equity.append((dt_i, eq))

    if pos == 1:
        # закрываем по последней цене (по bid - комиссия)
        dt_i = df["dt"].iat[-1]
        c = float(close.iat[-1])
        bid = c * (1 - slip)
        exit_px = bid * (1 - fee)
        pnl = (exit_px - entry_px) * cfg.size
        trades.append({
            "dt_entry": entry_dt,
            "dt_exit": dt_i,
            "px_entry": round(entry_px, 8),
            "px_exit": round(exit_px, 8),
            "pnl": round(pnl, 8),
            "stop": False,
        })
        eq += pnl
        equity.append((dt_i, eq))

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity, columns=["dt", "equity"])
    metrics = _calc_metrics([float(x) for x in trades_df["pnl"]] if not trades_df.empty else [])
    return trades_df, equity_df, metrics
