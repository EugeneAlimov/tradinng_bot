# src/backtest/compat.py
from __future__ import annotations

import math
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import numpy as np
import pandas as pd


# =============== Resample rule utils ===============

def normalize_resample_rule(rule: str) -> str:
    """
    Convert common aliases like '5m' -> '5T', '15m' -> '15T', '1h' -> '1H'.
    Leaves proper pandas offsets ('5T','15T','1H','1D', etc.) unchanged.
    """
    if not isinstance(rule, str):
        raise TypeError("resample rule must be a string")

    r = rule.strip()
    # Already a pandas offset alias
    if r.endswith(("T", "H", "D", "S")):
        return r

    if r.lower().endswith("ms"):
        # pandas uses 'L' for milliseconds; but we don't support sub-minute here
        raise ValueError("Millisecond resample not supported")

    if r.lower().endswith("m"):
        return r[:-1] + "T"  # minutes -> T
    if r.lower().endswith("h"):
        return r[:-1] + "H"
    if r.lower().endswith("d"):
        return r[:-1] + "D"
    return r


def _bars_per_year_for_rule(rule: str) -> float:
    rr = normalize_resample_rule(rule)
    if rr.endswith("T"):  # minutes
        minutes = float(rr[:-1] or 1)
        return 365.0 * 24.0 * 60.0 / minutes
    if rr.endswith("H"):
        hours = float(rr[:-1] or 1)
        return 365.0 * 24.0 / hours
    if rr.endswith("D"):
        days = float(rr[:-1] or 1)
        return 365.0 / days
    # Fallback: assume minute bars
    return 365.0 * 24.0 * 60.0 / 5.0


# =============== EXMO candles fetch ===============

def fetch_exmo_candles(pair: str, span: str) -> pd.DataFrame:
    """
    Fetch raw candles (no resample). Delegates to vectorized_bt._fetch_exmo_candles if available.
    Returns DataFrame with columns: ts (datetime64[ns, UTC]), open, high, low, close, volume.
    """
    try:
        # Import lazily to avoid circular deps
        from .vectorized_bt import _fetch_exmo_candles as _raw_fetch  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "EXMO candles fetch is not available in current build "
            "(missing vectorized_bt._fetch_exmo_candles)"
        ) from e

    df = _raw_fetch(pair, span)  # expected to raise RuntimeError on empty
    if df is None or len(df) == 0:
        raise RuntimeError(f"Empty candles from EXMO for {pair} span={span}")

    # Normalize columns
    cols = {c.lower(): c for c in df.columns}
    for need in ("ts", "open", "high", "low", "close", "volume"):
        if need not in cols and need not in df.columns:
            # best effort rename common variants
            if need == "ts":
                for cand in ("date", "time", "timestamp"):
                    if cand in df.columns:
                        df = df.rename(columns={cand: "ts"})
                        break
            else:
                # leave as is; vectorized_bt already returns proper names
                pass

    if "ts" not in df.columns:
        raise RuntimeError("Fetched candles missing 'ts' column")
    # Ensure tz-aware UTC index
    if not np.issubdtype(df["ts"].dtype, np.datetime64):
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    else:
        # localize to UTC if naive
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
    return df[["ts", "open", "high", "low", "close", "volume"]].copy()


def fetch_exmo_candles_cached(pair: str, span: str, cache_dir: Optional[Path] = None) -> pd.DataFrame:
    """
    Thin cache wrapper (on-disk parquet). Cache key depends on (pair, span).
    If fetch fails, errors bubble up (callers can record 'error' in CSV).
    """
    cache_root = Path(cache_dir or "data/cache")
    cache_root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{pair}|{span}".encode("utf-8")).hexdigest()[:16]
    path = cache_root / f"exmo_{pair}_{span.replace(':','_')}_{key}.parquet"

    if path.exists():
        try:
            df = pd.read_parquet(path)
            # basic sanity
            if len(df) > 0 and {"ts", "open", "high", "low", "close", "volume"} <= set(df.columns):
                return df
        except Exception:
            # ignore cache errors -> refetch
            pass

    df = fetch_exmo_candles(pair, span)
    try:
        df.to_parquet(path, index=False)
    except Exception:
        pass
    return df


# =============== Resampling ===============

def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample OHLCV by given pandas rule ('5m'/'5T','1H',...).
    Input must contain columns: ts, open, high, low, close, volume.
    """
    rr = normalize_resample_rule(rule)
    w = df.copy()
    if "ts" not in w.columns:
        raise ValueError("resample_ohlc: expected 'ts' column")

    w = w.set_index(pd.DatetimeIndex(pd.to_datetime(w["ts"], utc=True)))
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = w.resample(rr, label="right", closed="right").agg(agg).dropna()
    out.reset_index(inplace=True)
    out = out.rename(columns={"index": "ts"})
    return out[["ts", "open", "high", "low", "close", "volume"]]


# =============== Simple SMA-cross simulator ===============

@dataclass
class SimConfig:
    fast: int
    slow: int
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    fee_bps: int = 0
    slip_bps: int = 0
    qty_eur: float = 100.0
    enter_on_start: bool = False
    max_daily_loss_bps: int = 0  # not enforced in this lightweight sim
    resample: str = "5T"


def _calc_drawdown(equity: pd.Series) -> Tuple[float, pd.Series]:
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    max_dd = float(dd.min()) if len(dd) else 0.0
    return max_dd, dd


def _profit_factor(pnls: np.ndarray) -> float:
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 1.0
    return float(gains / losses)


def simulate_on_df(df: pd.DataFrame, cfg: SimConfig) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Long/flat SMA(fast)/SMA(slow) with hysteresis band and cooldown after exit.
    Trades executed at next-bar close with slippage and fees.
    Returns (trades_df, equity_df, metrics_dict).
    """
    if cfg.fast <= 0 or cfg.slow <= 0:
        raise ValueError("fast/slow must be positive")
    if cfg.fast >= cfg.slow:
        # still allow, but classic cross assumes fast < slow
        pass

    w = df.copy()
    closes = w["close"].astype(float).values
    n = len(w)
    if n < max(cfg.fast, cfg.slow) + 5:
        raise RuntimeError("Not enough bars for simulation")

    # Moving averages
    s_fast = pd.Series(closes).rolling(cfg.fast, min_periods=cfg.fast).mean().values
    s_slow = pd.Series(closes).rolling(cfg.slow, min_periods=cfg.slow).mean().values
    band = cfg.hysteresis_bps / 10000.0

    # State
    in_pos = False
    cooldown = 0
    entry_idx = -1
    entry_px = 0.0
    qty = 0.0
    trades = []

    # Equity curve (mark-to-market at close)
    start_eq = 1000.0
    eq = np.full(n, np.nan, dtype=float)
    cash = start_eq
    position_value = 0.0

    for i in range(n):
        px = closes[i]
        fast_ma = s_fast[i]
        slow_ma = s_slow[i]

        # Update equity (mark-to-market)
        if in_pos:
            position_value = qty * px
            eq[i] = cash + position_value
        else:
            eq[i] = cash

        if math.isnan(fast_ma) or math.isnan(slow_ma):
            continue

        if in_pos:
            # Exit condition: fast < slow*(1 - band)
            if fast_ma < slow_ma * (1.0 - band):
                # Execute exit at next bar (if exists)
                if i + 1 < n:
                    exit_px_raw = closes[i + 1]
                else:
                    exit_px_raw = px
                exit_px = exit_px_raw * (1.0 - cfg.slip_bps / 10000.0)
                entry_notional = qty * entry_px
                exit_notional = qty * exit_px
                fees = (abs(entry_notional) + abs(exit_notional)) * cfg.fee_bps / 10000.0
                pnl = exit_notional - entry_notional - fees

                cash += pnl
                position_value = 0.0
                eq[i] = cash
                trades.append(
                    {
                        "entry_ts": w["ts"].iloc[entry_idx],
                        "entry_px": float(entry_px),
                        "exit_ts": w["ts"].iloc[min(i + 1, n - 1)],
                        "exit_px": float(exit_px),
                        "qty": float(qty),
                        "pnl_eur": float(pnl),
                    }
                )
                in_pos = False
                cooldown = cfg.cooldown_bars
                qty = 0.0
        else:
            # Entry condition: fast > slow*(1 + band) and cooldown finished
            if cooldown > 0:
                cooldown -= 1
            elif fast_ma > slow_ma * (1.0 + band):
                # Execute entry at next bar (if exists)
                if i + 1 < n:
                    entry_px_raw = closes[i + 1]
                else:
                    entry_px_raw = px
                entry_px_exec = entry_px_raw * (1.0 + cfg.slip_bps / 10000.0)
                # fees are taken on notional; we keep qty in base asset
                qty = cfg.qty_eur / entry_px_exec
                entry_px = entry_px_exec
                entry_idx = i
                in_pos = True
                # cash unchanged (we consider qty funded by 'qty_eur' pocket and PnL realized on exit)

    # Finalize equity (mark-to-market last point)
    if in_pos:
        position_value = qty * closes[-1]
        eq[-1] = cash + position_value

    equity = pd.DataFrame(
        {
            "ts": w["ts"].values,
            "equity": eq,
        }
    ).dropna()

    # Metrics
    bars = int(n)
    trades_df = pd.DataFrame(trades)
    trades_cnt = int(len(trades_df))
    winrate = float((trades_df["pnl_eur"] > 0).mean() * 100.0) if trades_cnt else 0.0
    total_ret = float((equity["equity"].iloc[-1] / equity["equity"].iloc[0]) - 1.0) if len(equity) else 0.0
    max_dd, _ = _calc_drawdown(equity["equity"])
    pnls = trades_df["pnl_eur"].values if trades_cnt else np.array([], dtype=float)
    pf = float(_profit_factor(pnls)) if trades_cnt else 1.0
    avg_trade = float(trades_df["pnl_eur"].mean()) if trades_cnt else 0.0
    exposure = float((equity["equity"] > equity["equity"].shift(1)).mean() * 100.0) if len(equity) > 1 else 0.0

    # Sharpe on per-bar returns annualized
    equity_rets = equity["equity"].pct_change().dropna()
    rets_mu = float(equity_rets.mean()) if len(equity_rets) else 0.0
    rets_sd = float(equity_rets.std(ddof=0)) if len(equity_rets) else 0.0
    bpy = _bars_per_year_for_rule(cfg.resample)
    sharpe = float((math.sqrt(bpy) * rets_mu / rets_sd)) if rets_sd > 0 else 0.0

    # CAGR & Calmar
    years = float(bars / bpy) if bpy > 0 else 1.0
    cagr = float((equity["equity"].iloc[-1] / equity["equity"].iloc[0]) ** (1.0 / max(years, 1e-9)) - 1.0) if len(equity) else 0.0
    calmar = float((cagr * 100.0) / abs(max_dd) if max_dd < 0 else math.inf)

    metrics = {
        "pair": "UNKNOWN",
        "bars": bars,
        "trades": trades_cnt,
        "winrate_pct": round(winrate, 6),
        "total_return_pct": round(total_ret * 100.0, 12),
        "max_drawdown_pct": round(max_dd * 100.0, 12),
        "final_equity_eur": round(float(equity["equity"].iloc[-1]), 12) if len(equity) else 1000.0,
        "start_equity_eur": round(float(equity["equity"].iloc[0]), 12) if len(equity) else 1000.0,
        "profit_factor": round(pf, 12),
        "avg_trade_eur": round(avg_trade, 12),
        "exposure_pct": round(exposure, 12),
        "sharpe": round(sharpe, 12),
        "cagr_pct": round(cagr * 100.0, 12),
        "calmar": round(calmar, 12),
        "bars_per_year": round(bpy, 6),
    }

    return trades_df, equity, metrics
