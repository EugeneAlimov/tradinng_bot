# src/application/research/selector.py
from __future__ import annotations

import itertools
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# Реестр может отсутствовать / не содержать стратегию — это не критично
try:
    from src.domain.strategy import registry
except Exception:  # pragma: no cover
    registry = None  # type: ignore


# ===========================
# ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ
# ===========================

def _ensure_series(x: Sequence[Any] | pd.Series, dtype=None) -> pd.Series:
    if isinstance(x, pd.Series):
        s = x.copy()
        if dtype is not None:
            s = s.astype(dtype, copy=False)
        return s.reset_index(drop=True)
    s = pd.Series(list(x))
    if dtype is not None:
        s = s.astype(dtype, copy=False)
    return s.reset_index(drop=True)


def _extract_from_frame(df: pd.DataFrame) -> pd.Series:
    for col in ("signals", "signal", "sig", "pos", "position"):
        if col in df.columns:
            return _ensure_series(df[col], dtype="int64")
    # если есть один числовой столбец — берём его
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if len(num_cols) == 1:
        return _ensure_series(df[num_cols[0]], dtype="int64")
    raise ValueError("Cannot extract signals from DataFrame")


def _norm_signals(sig: Any, n: int) -> pd.Series:
    """
    Приводим сигналы к pd.Series int {-1,0,+1} длины n.
    Поддерживаем:
      - Series/array/list
      - DataFrame с колонками signals/signal/sig/pos/position
      - dict: {"signals": ...} или {"signal": ...} и т.п.
      - tuple: (signals, state)
    """
    if isinstance(sig, tuple) and len(sig) >= 1:
        sig = sig[0]
    if isinstance(sig, dict):
        for k in ("signals", "signal", "sig", "pos", "position"):
            if k in sig:
                sig = sig[k]
                break

    if isinstance(sig, pd.DataFrame):
        s = _extract_from_frame(sig)
    else:
        s = _ensure_series(sig)

    # Приводим длину
    if len(s) < n:
        s = s.reindex(range(n), fill_value=0)
    elif len(s) > n:
        s = s.iloc[:n]

    s = s.fillna(0)
    # bool -> {0,1}
    if s.dtype == bool:
        s = s.astype("int64")
    # float/int -> округляем и клипим
    if s.dtype.kind in {"f", "i"}:
        s = s.astype(float).round().clip(-1, 1).astype("int64")
    else:
        s = s.astype("int64").clip(-1, 1)
    return s


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / (peak + 1e-12)
    return float(dd.min())


def _sharpe(step_ret: np.ndarray) -> float:
    if step_ret.size < 2:
        return 0.0
    std = float(np.std(step_ret))
    if std <= 0:
        return 0.0
    return float(np.mean(step_ret) / (std + 1e-12))


def _score(stat: Dict[str, Any]) -> float:
    # Комбинированный скор (шарп + pnl - штраф за просадку)
    sh = float(stat.get("sharpe", 0.0))
    dd = float(stat.get("max_dd", 0.0))  # отрицательное число
    pnl = float(stat.get("total_pnl", 0.0))
    return sh + 0.5 * pnl + (0.0 if dd == 0 else 0.5 * (1.0 + dd))


def _calmar(equity_end: float, max_dd: float) -> float:
    if max_dd >= 0:
        return 0.0
    return float((equity_end - 1.0) / abs(max_dd))


# ===========================
# БАЗОВЫЕ ИНДИКАТОРЫ (fallback)
# ===========================

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=max(1, int(n)), adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(window=max(1, int(n)), min_periods=max(1, int(n))).mean()


def _tr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    a = (high - low).abs()
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    tr = _tr(high, low, close)
    # Wilder smoothing (как ewm с alpha=1/n)
    return tr.ewm(alpha=1.0 / max(1, int(n)), adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    n = max(1, int(n))
    up = high.diff()
    down = -low.diff()

    plus_dm = ((up > down) & (up > 0)).astype(float) * up.clip(lower=0)
    minus_dm = ((down > up) & (down > 0)).astype(float) * down.clip(lower=0)

    atr = _atr(high, low, close, n)

    plus_di = 100.0 * (plus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / (atr + 1e-12))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / (atr + 1e-12))
    dx = 100.0 * (plus_di - minus_di).abs() / ((plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=1.0 / n, adjust=False).mean().fillna(0.0)
    return adx.fillna(0.0), plus_di.fillna(0.0), minus_di.fillna(0.0)


def _rsi(close: pd.Series, n: int) -> pd.Series:
    n = max(1, int(n))
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / n, adjust=False).mean()
    roll_down = down.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


# ===========================
# ВСТРОЕННЫЕ СТРАТЕГИИ (fallback)
# ===========================

def _builtin_signals(name: str, ohlc: pd.DataFrame, **p) -> Optional[pd.Series]:
    """
    Если вызовы через реестр не удались — используем простые встроенные реализации.
    Возвращаем Series {-1,0,+1} или None (если стратегия не поддержана тут).
    """
    n = len(ohlc)
    if n == 0:
        return pd.Series([], dtype="int64")

    close = _ensure_series(ohlc["close"], dtype="float64")
    open_ = _ensure_series(ohlc.get("open", close), dtype="float64")
    high = _ensure_series(ohlc.get("high", close), dtype="float64")
    low = _ensure_series(ohlc.get("low", close), dtype="float64")

    nm = name.lower()

    # --- SMA cross ---
    if nm == "sma":
        fast = int(p.get("fast", 10))
        slow = int(p.get("slow", 20))
        f = _sma(close, fast)
        s = _sma(close, slow)
        pos = (f > s).astype("int64")
        return _norm_signals(pos, n)

    # --- EMA cross ---
    if nm == "ema":
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        f = _ema(close, fast)
        s = _ema(close, slow)
        pos = (f > s).astype("int64")
        return _norm_signals(pos, n)

    # --- MACD ---
    if nm == "macd":
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        signal = int(p.get("signal", 9))
        macd = _ema(close, fast) - _ema(close, slow)
        macd_signal = _ema(macd, signal)
        pos = (macd > macd_signal).astype("int64")
        return _norm_signals(pos, n)

    # --- RSI2 (contrarian): long при RSI<low, выход при RSI>high ---
    if nm == "rsi2":
        length = int(p.get("len", 2))
        low_th = float(p.get("low", 10))
        high_th = float(p.get("high", 90))
        r = _rsi(close, length)
        pos = pd.Series(0, index=close.index, dtype="int64")
        in_pos = False
        for i in range(n):
            if not in_pos and r.iat[i] <= low_th:
                in_pos = True
                pos.iat[i] = 1
            elif in_pos and r.iat[i] >= high_th:
                in_pos = False
                pos.iat[i] = 0
            else:
                pos.iat[i] = 1 if in_pos else 0
        return _norm_signals(pos, n)

    # --- Donchian breakout ---
    if nm == "donchian":
        length = int(p.get("len", 20))
        upper = high.rolling(length, min_periods=length).max().shift(1)
        lower = low.rolling(length, min_periods=length).min().shift(1)
        pos = (close > upper).fillna(0).astype("int64")
        return _norm_signals(pos, n)

    # --- EMA + ADX gating ---
    if nm in ("ema_adx", "ema_adx_atr"):
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        adx_len = int(p.get("adx_len", 14))
        on = float(p.get("on", 25.0))
        off = float(p.get("off", 18.0))
        require_di = bool(p.get("require_di", True))
        f = _ema(close, fast)
        s = _ema(close, slow)
        trend = (f > s).astype(int)
        adx, di_plus, di_minus = _adx(high, low, close, adx_len)

        pos = pd.Series(0, index=close.index, dtype="int64")
        in_pos = False
        for i in range(n):
            # вход: тренд up и ADX >= on (+DI>-DI, если нужно)
            if (not in_pos) and trend.iat[i] > 0 and (adx.iat[i] >= on) and (not require_di or di_plus.iat[i] >= di_minus.iat[i]):
                in_pos = True
                pos.iat[i] = 1
            # выход: ADX <= off или тренд down
            elif in_pos and ((adx.iat[i] <= off) or trend.iat[i] <= 0):
                in_pos = False
                pos.iat[i] = 0
            else:
                pos.iat[i] = 1 if in_pos else 0

        # ema_adx_atr можно было бы дополнить стопами по ATR — для sweep достаточно pos
        return _norm_signals(pos, n)

    # (остальные — пропускаем, пусть идут через реестр)
    return None


def _call_signals(defn: Any, ohlc: pd.DataFrame, strategy_name: str, **params) -> pd.Series:
    """
    Пытаемся корректно вызвать генератор сигналов стратегии:
      1) signals(ohlc=..., **params)
      2) signals(open=..., high=..., low=..., close=..., **params)
      3) signals(close=..., **params)
      4) generate_signals / generate / calc — те же варианты
      5) если всё не взлетело — ВСТРОЕННЫЙ fallback
    """
    close = _ensure_series(ohlc["close"], dtype="float64")
    o = _ensure_series(ohlc.get("open", close), dtype="float64")
    h = _ensure_series(ohlc.get("high", close), dtype="float64")
    l = _ensure_series(ohlc.get("low", close), dtype="float64")

    def _try_call(obj, fn_name: str):
        if not hasattr(obj, fn_name):
            return None
        fn = getattr(obj, fn_name)
        # 1) ohlc=...
        try:
            return fn(ohlc=ohlc, **params)
        except Exception:
            pass
        # 2) OHLC
        try:
            return fn(open=o, high=h, low=l, close=close, **params)
        except Exception:
            pass
        # 3) close
        try:
            return fn(close=close, **params)
        except Exception:
            pass
        return None

    # через методы стратегии
    for name in ("signals", "generate_signals", "generate", "calc"):
        out = _try_call(defn, name)
        if out is not None:
            return _norm_signals(out, len(close))

    # встроенные (fallback) — дадут хоть какие-то сигналы
    fb = _builtin_signals(strategy_name, ohlc, **params)
    if fb is not None:
        return _norm_signals(fb, len(close))

    raise AttributeError(f"Strategy '{getattr(defn, 'name', strategy_name)}' has no usable signal generator")


def _param_grid(grid: Optional[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """
    grid может быть:
      - dict: {param: [values] | value}
      - list[dict]: уже готовые комбинации
    """
    if not grid:
        return []
    if isinstance(grid, list):
        for g in grid:
            yield dict(g)
        return
    keys = list(grid.keys())
    values = [v if isinstance(v, (list, tuple)) else [v] for v in (grid[k] for k in keys)]
    for combo in itertools.product(*values):
        yield {k: v for k, v in zip(keys, combo)}


def _default_grid_for_strategy(name: str) -> List[Dict[str, Any]]:
    """
    Консервативные дефолты, работающие на коротких выборках (5m:200).
    """
    n = name.lower()
    if n == "sma":          # кросс SMA fast/slow
        return [{"fast": f, "slow": s} for f, s in [(5, 10), (10, 20), (12, 26), (20, 50)] if f < s]
    if n == "ema":          # кросс EMA fast/slow
        return [{"fast": f, "slow": s} for f, s in [(5, 10), (10, 21), (12, 26), (20, 50)] if f < s]
    if n == "ema_adx":
        base = {
            "fast": [10, 12, 21],
            "slow": [21, 26],
            "adx_len": [14],
            "on": [22.0, 25.0],
            "off": [16.0, 18.0],
            "require_di": [True],
        }
        return list(_param_grid(base))
    if n == "ema_adx_atr":
        base = {
            "fast": [10, 12, 21],
            "slow": [21, 26],
            "adx_len": [14],
            "on": [22.0, 25.0],
            "off": [16.0, 18.0],
            "require_di": [True],
            "atr_len": [14],
            "atr_mult": [2.0, 2.5, 3.0],
        }
        return list(_param_grid(base))
    if n == "supertrend":
        return list(_param_grid({"len": [10, 14], "mult": [2.0, 3.0]}))
    if n == "keltner":
        return list(_param_grid({"len": [14, 20], "mult": [1.5, 2.0]}))
    if n == "adx":
        return list(_param_grid({"adx_len": [14], "on": [25.0], "off": [18.0, 20.0]}))
    if n == "sma_atr":
        return list(_param_grid({"fast": [10], "slow": [20, 50], "atr_len": [14], "atr_mult": [2.0, 3.0]}))
    if n == "rsi2":
        return list(_param_grid({"len": [2], "low": [10], "high": [90]}))
    if n == "donchian":
        return list(_param_grid({"len": [20, 55]}))
    if n == "bbands":
        return list(_param_grid({"len": [20], "mult": [2.0]}))
    if n == "roc":
        return list(_param_grid({"len": [9, 12, 14]}))
    if n == "macd":
        return list(_param_grid({"fast": [12], "slow": [26], "signal": [9]}))
    return [{}]


def _available_strategies_auto() -> List[str]:
    # стараемся брать реальные имена из реестра
    if registry and hasattr(registry, "names"):
        try:
            names = registry.names()  # type: ignore[attr-defined]
            if isinstance(names, (list, tuple)) and names:
                return [str(n).lower() for n in names]
        except Exception:
            pass
    # фолбэк-набор
    return [
        "sma", "ema", "ema_adx", "ema_adx_atr", "supertrend",
        "keltner", "adx", "sma_atr", "rsi2", "donchian", "bbands", "roc", "macd"
    ]


def _strategies_list(spec: str | Sequence[str]) -> List[str]:
    if isinstance(spec, str):
        s = spec.strip().lower()
        if s == "auto":
            return _available_strategies_auto()
        return [s]
    return [str(x).lower() for x in spec]


# ===========================
# БЭКТЕСТ long-only
# ===========================

def _backtest_long_only(
    prices: pd.Series | Sequence[float],
    ts: pd.Series | Sequence[int],
    signals: pd.Series | Sequence[int],
    fee_bps: int = 0,
    slip_bps: int = 0,
) -> Dict[str, Any]:
    prices = _ensure_series(prices, dtype="float64")
    ts = _ensure_series(ts)
    sig = _ensure_series(signals, dtype="int64")
    if len(sig) < len(prices):
        sig = sig.reindex(range(len(prices)), fill_value=0)
    elif len(sig) > len(prices):
        sig = sig.iloc[: len(prices)]

    n = len(prices)
    if n == 0:
        return {
            "n_trades": 0,
            "trades": 0,
            "winrate": 0.0,
            "win_pct": 0.0,
            "avg_pnl": 0.0,
            "total_pnl": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
            "equity_end": 1.0,
            "calmar": 0.0,
        }

    fee = float(fee_bps) / 10000.0
    slip = float(slip_bps) / 10000.0

    in_pos = False
    entry_px = 0.0
    trade_pnls: List[float] = []

    equity = [1.0]
    eq = 1.0

    for i in range(n):
        s = int(sig.iat[i])
        p = float(prices.iat[i])

        # вход по s>0
        if (not in_pos) and (s > 0):
            entry_px = p * (1.0 + slip)
            eq *= (1.0 - fee)  # комиссия на вход
            in_pos = True

        # выход по s<=0
        elif in_pos and (s <= 0):
            exit_px = p * (1.0 - slip)
            ret = (exit_px / entry_px) - 1.0
            ret -= fee
            trade_pnls.append(ret)
            eq *= (1.0 + ret)
            in_pos = False

        equity.append(eq)

    # закрываем хвост, если позиция осталась открытой
    if in_pos:
        p = float(prices.iat[-1])
        exit_px = p * (1.0 - slip)
        ret = (exit_px / entry_px) - 1.0
        ret -= fee
        trade_pnls.append(ret)
        eq *= (1.0 + ret)
        equity[-1] = eq

    equity_arr = np.asarray(equity, dtype=float)
    step_ret = np.diff(equity_arr) / (equity_arr[:-1] + 1e-12)

    n_trades = len(trade_pnls)
    wins = (np.array(trade_pnls) > 0.0) if n_trades else np.array([], dtype=bool)
    winrate = float(wins.mean()) if n_trades else 0.0
    avg_pnl = float(np.mean(trade_pnls)) if n_trades else 0.0
    total_pnl = float(np.sum(trade_pnls)) if n_trades else 0.0
    max_dd = _max_drawdown(equity_arr)
    shp = _sharpe(step_ret)
    eq_end = float(equity_arr[-1])
    calmar = _calmar(eq_end, max_dd)

    return {
        "n_trades": n_trades,
        "trades": n_trades,
        "winrate": winrate,
        "win_pct": winrate * 100.0,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "max_dd": max_dd,
        "sharpe": shp,
        "equity_end": eq_end,
        "calmar": calmar,
    }


def _row_from_stats(strategy_name: str, params: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        "strategy": strategy_name,
        "params": dict(params),
        "trades": int(stats.get("n_trades", stats.get("trades", 0))),
        "n_trades": int(stats.get("n_trades", stats.get("trades", 0))),
        "win%": float(stats.get("win_pct", stats.get("winrate", 0.0) * 100.0)),
        "avgPnL": float(stats.get("avg_pnl", 0.0)),
        "totalPnL": float(stats.get("total_pnl", 0.0)),
        "maxDD": float(stats.get("max_dd", 0.0)),
        "sharpe": float(stats.get("sharpe", 0.0)),
        "calmar": float(stats.get("calmar", 0.0)),
    }
    row["score"] = _score(stats)
    return row


def _select_metric_value(row: Dict[str, Any], metric: str) -> float:
    m = metric.lower()
    if m == "totalpnl":
        return float(row.get("totalPnL", 0.0))
    if m in ("sharpe", "score", "calmar"):
        return float(row.get(m, 0.0))
    if m == "win%":
        return float(row.get("win%", 0.0))
    if m == "trades":
        return float(row.get("trades", 0))
    return float(row.get("sharpe", 0.0))


# ===========================
# ПУБЛИЧНОЕ API
# ===========================

def sweep(
    ohlc: pd.DataFrame,
    strategies: str | Sequence[str],
    grid: Optional[Dict[str, Any]],
    fee_bps: int,
    slip_bps: int,
    *,
    metric: str = "sharpe",
    top_n: int = 8,
    min_trades: int = 5,
    weights: Optional[Dict[str, float]] = None,  # зарезервировано
) -> List[Dict[str, Any]]:
    close = _ensure_series(ohlc["close"], dtype="float64")
    _ = close  # чтобы линтер не ругался
    _ensure_series(ohlc["ts"])

    names = _strategies_list(strategies)
    rows: List[Dict[str, Any]] = []

    for name in names:
        # пытаемся взять из реестра (если он есть)
        defn = None
        if registry and hasattr(registry, "get"):
            try:
                defn = registry.get(name)  # type: ignore[attr-defined]
            except Exception:
                defn = None

        # сетка: если из CLI пришёл dict с ключом стратегии — берём его,
        # иначе — дефолтная для конкретной стратегии
        strat_grid = None
        if isinstance(grid, dict) and name in grid:
            strat_grid = grid[name]
        elif isinstance(grid, dict) and any(k in grid for k in ("fast", "slow", "len", "on", "off", "adx_len", "atr_len", "atr_mult", "signal", "low", "high")):
            # пользователь задал «плоскую» сетку — применяем её
            strat_grid = grid

        combos = list(_param_grid(strat_grid)) or _default_grid_for_strategy(name)

        for params in combos:
            try:
                if defn is not None:
                    sig = _call_signals(defn, ohlc, name, **params)
                else:
                    fb = _builtin_signals(name, ohlc, **params)
                    if fb is None:
                        continue
                    sig = _norm_signals(fb, len(close))

                stats = _backtest_long_only(ohlc["close"], ohlc["ts"], sig, fee_bps=fee_bps, slip_bps=slip_bps)
                if int(stats.get("n_trades", 0)) < int(min_trades):
                    continue
                rows.append(_row_from_stats(name, params, stats))
            except Exception:
                # невалидная комбинация — пропускаем
                continue

    if not rows:
        return []

    rows.sort(key=lambda r: _select_metric_value(r, metric), reverse=True)
    return rows[: int(top_n)]


def optimize(
    ohlc: pd.DataFrame,
    strategy: str,
    grid: Optional[Dict[str, Any]],
    fee_bps: int,
    slip_bps: int,
    *,
    metric: str = "sharpe",
    top_n: int = 10,
    min_trades: int = 5,
) -> List[Dict[str, Any]]:
    strat_grid = None
    if isinstance(grid, dict):
        if any(k in grid for k in ("fast", "slow", "len", "on", "off", "adx_len", "atr_len", "atr_mult", "signal", "low", "high")):
            strat_grid = grid
        else:
            strat_grid = grid.get(strategy)
    return sweep(
        ohlc=ohlc,
        strategies=[strategy],
        grid=strat_grid,
        fee_bps=fee_bps,
        slip_bps=slip_bps,
        metric=metric,
        top_n=top_n,
        min_trades=min_trades,
    )


def robustness(
    ohlc: pd.DataFrame,
    strategy: str,
    params: Dict[str, Any],
    fee_bps: int,
    slip_bps: int,
    *,
    level: float = 0.1,
    samples: int = 50,
) -> List[Dict[str, Any]]:
    # пытаемся взять из реестра, иначе fallback
    defn = None
    if registry and hasattr(registry, "get"):
        try:
            defn = registry.get(strategy)  # type: ignore[attr-defined]
        except Exception:
            defn = None

    close = _ensure_series(ohlc["close"], dtype="float64")
    _ensure_series(ohlc["ts"])

    def perturb(p: Dict[str, Any]) -> Dict[str, Any]:
        q: Dict[str, Any] = {}
        for k, v in p.items():
            if isinstance(v, (int, float)):
                dv = float(v) * float(level)
                new_v = float(v) + np.random.uniform(-dv, dv)
                if isinstance(v, int):
                    new_v = max(1, int(round(new_v)))
                q[k] = new_v
            else:
                q[k] = v
        return q

    rows: List[Dict[str, Any]] = []
    for _ in range(int(samples)):
        par = perturb(params)
        try:
            if defn is not None:
                sig = _call_signals(defn, ohlc, strategy, **par)
            else:
                fb = _builtin_signals(strategy, ohlc, **par)
                if fb is None:
                    continue
                sig = _norm_signals(fb, len(close))

            stats = _backtest_long_only(ohlc["close"], ohlc["ts"], sig, fee_bps=fee_bps, slip_bps=slip_bps)
            rows.append(_row_from_stats(strategy, par, stats))
        except Exception:
            continue
    return rows


def walk_forward(
    ohlc: pd.DataFrame,
    strategies: str | Sequence[str],
    grid: Optional[Dict[str, Any]],
    fee_bps: int,
    slip_bps: int,
    *,
    folds: int = 3,
    train_frac: float = 0.7,
    metric: str = "sharpe",
    min_trades: int = 5,
) -> Dict[str, Any]:
    n = len(ohlc)
    if n < 20 or folds < 1:
        return {"folds": [], "oos_sharpe_mean": 0.0, "oos_calmar_mean": 0.0, "oos_total_return_pct_mean": 0.0}

    fold_size = n // folds
    names = _strategies_list(strategies)

    fold_rows: List[Dict[str, Any]] = []
    oos_sharpes: List[float] = []
    oos_calmars: List[float] = []
    oos_total_returns: List[float] = []

    for i in range(folds):
        start = i * fold_size
        end = n if i == folds - 1 else (i + 1) * fold_size

        tr_end = start + max(1, int((end - start) * float(train_frac)))
        train = ohlc.iloc[start:tr_end]
        test = ohlc.iloc[tr_end:end]
        if len(train) < 10 or len(test) < 5:
            continue

        sw = sweep(
            ohlc=train,
            strategies=names,
            grid=grid,
            fee_bps=fee_bps,
            slip_bps=slip_bps,
            metric=metric,
            top_n=1,
            min_trades=min_trades,
        )
        if not sw:
            fold_rows.append(
                {
                    "fold": i + 1,
                    "train_range": (int(train["ts"].iloc[0]), int(train["ts"].iloc[-1])),
                    "test_range": (int(test["ts"].iloc[0]), int(test["ts"].iloc[-1])),
                    "best": None,
                    "oos": None,
                }
            )
            continue

        best = sw[0]
        best_name = str(best["strategy"])
        best_params = dict(best["params"])

        # берём из реестра (если есть) — иначе fallback
        defn = None
        if registry and hasattr(registry, "get"):
            try:
                defn = registry.get(best_name)  # type: ignore[attr-defined]
            except Exception:
                defn = None

        sig = None
        try:
            if defn is not None:
                sig = _call_signals(defn, test, best_name, **best_params)
            else:
                fb = _builtin_signals(best_name, test, **best_params)
                if fb is not None:
                    sig = _norm_signals(fb, len(test))
        except Exception:
            sig = None

        if sig is None:
            fold_rows.append(
                {
                    "fold": i + 1,
                    "train_range": (int(train["ts"].iloc[0]), int(train["ts"].iloc[-1])),
                    "test_range": (int(test["ts"].iloc[0]), int(test["ts"].iloc[-1])),
                    "best": best,
                    "oos": None,
                }
            )
            continue

        stats = _backtest_long_only(test["close"], test["ts"], sig, fee_bps=fee_bps, slip_bps=slip_bps)
        oos_row = _row_from_stats(best_name, best_params, stats)

        fold_rows.append(
            {
                "fold": i + 1,
                "train_range": (int(train["ts"].iloc[0]), int(train["ts"].iloc[-1])),
                "test_range": (int(test["ts"].iloc[0]), int(test["ts"].iloc[-1])),
                "best": best,
                "oos": oos_row,
            }
        )

        oos_sharpes.append(float(oos_row.get("sharpe", 0.0)))
        oos_calmars.append(float(oos_row.get("calmar", 0.0)))
        oos_total_returns.append(float(stats.get("equity_end", 1.0) - 1.0) * 100.0)

    return {
        "folds": fold_rows,
        "oos_sharpe_mean": float(np.mean(oos_sharpes)) if oos_sharpes else 0.0,
        "oos_calmar_mean": float(np.mean(oos_calmars)) if oos_calmars else 0.0,
        "oos_total_return_pct_mean": float(np.mean(oos_total_returns)) if oos_total_returns else 0.0,
    }
