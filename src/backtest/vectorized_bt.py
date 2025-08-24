from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

import numpy as np
import pandas as pd

# ==============================
# Config & Public API
# ==============================

@dataclass
class BtConfig:
    pair: str                      # EXMO pair, e.g. "DOGE_EUR"
    span: str                      # e.g. "1m:5000"
    fast: int                      # fast SMA window (bars)
    slow: int                      # slow SMA window (bars)
    hysteresis_bps: int = 0        # entry/exit hysteresis in basis points
    cooldown_bars: int = 0         # bars to wait after exit before new entry
    enter_on_start: bool = False   # if True and long condition true at start, enter immediately
    fee_bps: int = 0               # per-side fee in bps
    slip_bps: int = 0              # slippage in bps (applied adversarially on fills)
    qty_eur: float = 100.0         # notional per trade in quote currency (EUR)
    max_daily_loss_bps: int = 0    # optional daily stop in bps of start_equity (0=off)
    resample: Optional[str] = None # e.g. "5m" (minutes); None -> do not resample

# ==============================
# Helpers
# ==============================

def _now_utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

def _parse_span(span: str) -> Tuple[str, int]:
    """
    Parse span like "1m:5000" -> ("1m", 5000).
    """
    if ":" not in span:
        raise ValueError(f"Invalid span '{span}'. Expected format '<tf>:<limit>' e.g. '1m:5000'")
    tf, lim = span.split(":", 1)
    lim_int = int(lim)
    if lim_int <= 0:
        raise ValueError("limit in span must be > 0")
    return tf.strip(), lim_int

def _minutes_from_tf(tf: str) -> int:
    """
    Convert EXMO time frame string to minutes.
    Supports '1m','3m','5m','15m','30m','1h','4h','1d' etc.
    """
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    raise ValueError(f"Unsupported timeframe '{tf}'")

def _normalize_resample(rule: str) -> str:
    """
    Pandas recommends 'T' or 'min' for minutes; 'm' is month-end (deprecated shorthand).
    Convert '5m' -> '5T'
    """
    rule = rule.strip()
    if rule.lower().endswith("m"):
        # Minute
        num = rule[:-1]
        if not num.isdigit():
            raise ValueError(f"Invalid minute resample rule '{rule}'")
        return f"{int(num)}T"
    return rule

def _bars_per_year_from_rule(rule: Optional[str]) -> float:
    """
    Estimate bars per (365-day) year for given resample or base tf.
    """
    minutes = 1
    if rule:
        if rule.lower().endswith("m"):
            minutes = int(rule[:-1])
        elif rule.upper().endswith("T"):
            minutes = int(rule[:-1])
        elif rule.lower().endswith("h"):
            minutes = int(rule[:-1]) * 60
        elif rule.lower().endswith("d"):
            minutes = int(rule[:-1]) * 60 * 24
        else:
            # Fallback to 1 minute
            minutes = 1
    return (365 * 24 * 60) / minutes

def _apply_bps(price: float, bps: int, adverse: bool) -> float:
    """
    Apply slippage in bps to price. If adverse=True, move price against us.
    """
    if bps == 0:
        return price
    factor = (1.0 + (bps / 1e4))
    return price * (factor if adverse else (1.0 / factor))

def _fee_multiplier(bps: int) -> float:
    """
    Convert per-side fee in bps into multiplier on notional.
    """
    if bps == 0:
        return 1.0
    return 1.0 - (bps / 1e4)

# ==============================
# Data Fetch (EXMO)
# ==============================

def _fetch_exmo_candles(pair: str, span: str) -> pd.DataFrame:
    """
    Fetch candles from EXMO public API 'candles_history' (GET).
    Falls back to local provider if project defines one.

    Returns DataFrame with UTC index and columns: open, high, low, close, volume (float).
    """
    # 1) Try a local provider hook if user has it in the project (keeps backwards compatibility).
    # e.g., src/infra/exmo_env_support.py: def fetch_exmo_candles(pair, span) -> DataFrame
    try:
        from src.infra.exmo_env_support import fetch_exmo_candles as _local_fetch  # type: ignore
        df_local = _local_fetch(pair, span)
        if not isinstance(df_local, pd.DataFrame) or df_local.empty:
            raise RuntimeError("Local EXMO provider returned empty or invalid DataFrame.")
        return _ensure_ohlc_df(df_local)
    except Exception:
        pass  # fall back to HTTP

    tf, limit = _parse_span(span)
    resolution_min = _minutes_from_tf(tf)

    import requests  # local import to avoid hard dependency at import time

    url = "https://api.exmo.com/v1.1/candles_history"
    params = {
        "symbol": pair,
        "resolution": resolution_min,  # minutes
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    # API variants: some versions return {"s":"ok","t":[...], "o":[...], "h":[...],"l":[...],"c":[...],"v":[...]}
    # другие — {"candles": [{"t": 1690000000, "o":..., "c":..., "h":..., "l":..., "v":...}, ...]}
    # Обработаем оба варианта:
    if isinstance(data, dict) and "candles" in data:
        candles = data["candles"]
        if not candles:
            raise RuntimeError(f"Empty candles from EXMO for {pair} span={span}")
        rows = []
        for c in candles:
            t = c.get("t")
            ts = _safe_to_utc_ts(t)
            rows.append(
                (ts, float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c.get("v", 0.0)))
            )
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
        df.index = pd.to_datetime(df.index, unit="s", utc=True)
        return df.sort_index()
    else:
        # arrays variant
        t = data.get("t") or data.get("T") or []
        o = data.get("o") or data.get("O") or []
        h = data.get("h") or data.get("H") or []
        l = data.get("l") or data.get("L") or []
        c = data.get("c") or data.get("C") or []
        v = data.get("v") or data.get("V") or []
        if not t:
            raise RuntimeError(f"Empty candles from EXMO for {pair} span={span}")
        ts = [_safe_to_utc_ts(x) for x in t]
        # ts already in seconds
        idx = pd.to_datetime(ts, unit="s", utc=True)
        df = pd.DataFrame(
            {"open": o, "high": h, "low": l, "close": c, "volume": v},
            index=idx,
            dtype=float,
        )
        return df.sort_index()

def _safe_to_utc_ts(x: Any) -> int:
    """
    Make a safe (seconds-based) UTC timestamp from INT or STR that may be in ms.
    """
    # Some APIs return ms since epoch, others seconds. Detect by magnitude / length.
    try:
        val = int(x)
    except Exception:
        # e.g. "1692829200.0" -> 1692829200
        val = int(float(x))
    # If ts is too large for seconds (e.g. > 10^12), treat as milliseconds
    if val > 10_000_000_000:  # ~Sat Nov 20 2286 for seconds; larger likely ms
        val = val // 1000
    return val

def _ensure_ohlc_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure DataFrame has expected columns and UTC index.
    """
    cols = {c.lower(): c for c in df.columns}
    ren = {}
    for need in ["open", "high", "low", "close", "volume"]:
        if need in cols:
            ren[cols[need]] = need
    out = df.rename(columns=ren).copy()
    if not {"open", "high", "low", "close"}.issubset(out.columns):
        raise ValueError("Input candles DataFrame must contain open, high, low, close")
    if not isinstance(out.index, pd.DatetimeIndex):
        if "ts" in out.columns:
            out = out.set_index("ts")
        else:
            raise ValueError("Candles DataFrame must have DatetimeIndex or 'ts' column")
    out.index = pd.to_datetime(out.index, utc=True)
    out.sort_index(inplace=True)
    if "volume" not in out.columns:
        out["volume"] = 0.0
    return out[["open", "high", "low", "close", "volume"]]

# ==============================
# Resample
# ==============================

def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample minute/hours candles to a coarser rule (e.g., '5m' -> '5T').
    Right-closed / right-labeled to align with "close" as execution price.
    """
    if not rule:
        return df.copy()
    norm = _normalize_resample(rule)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = df.resample(norm, label="right", closed="right").agg(agg).dropna()
    return out

# ==============================
# Strategy & Backtest
# ==============================

def _sma(a: pd.Series, win: int) -> pd.Series:
    if win <= 0:
        raise ValueError("SMA window must be > 0")
    return a.rolling(win, min_periods=win).mean()

def _generate_positions(
    close: pd.Series, fast: pd.Series, slow: pd.Series,
    hysteresis_bps: int, cooldown_bars: int
) -> pd.Series:
    """
    Long/flat positions {0,1} with hysteresis (bps) and cooldown after exit.
    Entry: (fast - slow)/close > +hyst
    Exit:  (fast - slow)/close < -hyst
    """
    spread = (fast - slow) / close
    thr = hysteresis_bps / 1e4
    long_sig = spread > thr
    flat_sig = spread < -thr

    pos = np.zeros(len(close), dtype=np.int8)
    cd = 0  # cooldown counter

    for i in range(len(close)):
        if cd > 0:
            # Cooldown active: cannot open long
            if pos[i - 1] == 1:
                # shouldn't happen, but keep flat during cooldown if we just exited
                pos[i] = 0
            else:
                pos[i] = 0
            cd -= 1
            continue

        prev = pos[i - 1] if i > 0 else 0
        if prev == 0:
            # flat -> can enter only if long signal
            pos[i] = 1 if long_sig.iloc[i] else 0
        else:
            # long -> exit only if explicit flat_sig
            if flat_sig.iloc[i]:
                pos[i] = 0
                cd = max(cd, cooldown_bars)  # start cooldown
            else:
                pos[i] = 1

    return pd.Series(pos, index=close.index, dtype="int8")

def _simulate_on_df(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    hysteresis_bps: int,
    cooldown_bars: int,
    fee_bps: int,
    slip_bps: int,
    qty_eur: float,
    enter_on_start: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Simulate trades on DF with columns: open, high, low, close, volume.
    Returns (equity_df, trades_df).
    """
    close = df["close"]
    sma_fast = _sma(close, fast)
    sma_slow = _sma(close, slow)

    mask_valid = (~sma_fast.isna()) & (~sma_slow.isna())
    if mask_valid.sum() < max(fast, slow) + 2:
        raise RuntimeError("Not enough candles for SMA windows.")

    pos = _generate_positions(close, sma_fast, sma_slow, hysteresis_bps, cooldown_bars).astype(int)

    # Ensure we don't start in-the-middle unless allowed
    if not enter_on_start and pos.iloc[mask_valid.idxmax()] == 1:
        # first valid bar has long, but we disallow immediate enter: shift entry until next 'enter' edge
        # Convert pos to edges to enforce "enter only on rising edge"
        p = pos.values
        for i in range(1, len(p)):
            if p[i - 1] == 0 and p[i] == 1:
                # first real enter
                start_enter = i
                p[:start_enter] = 0
                break
        pos = pd.Series(p, index=pos.index, dtype=int)

    # Build trades on rising/falling edges
    p = pos.values
    entries: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []

    fee_mult = _fee_multiplier(fee_bps)

    for i in range(1, len(p)):
        # entry edge
        if p[i - 1] == 0 and p[i] == 1:
            px = float(df["close"].iloc[i])
            px_fill = _apply_bps(px, slip_bps, adverse=True)
            notional = qty_eur
            # apply fee on buy notional (reduce effective units)
            units = (notional * fee_mult) / px_fill
            entries.append({
                "ts": df.index[i],
                "price": px_fill,
                "units": units,
                "notional_eur": notional,
            })
        # exit edge
        elif p[i - 1] == 1 and p[i] == 0:
            if not entries:
                continue
            entry = entries.pop(0)  # FIFO (should be only one open position)
            px = float(df["close"].iloc[i])
            px_fill = _apply_bps(px, slip_bps, adverse=True)
            # apply fee on sell: reduce proceeds
            proceeds = entry["units"] * px_fill * fee_mult
            pnl = proceeds - entry["notional_eur"]
            trades.append({
                "entry_ts": entry["ts"],
                "entry_px": entry["price"],
                "exit_ts": df.index[i],
                "exit_px": px_fill,
                "qty_eur": entry["notional_eur"],
                "pnl_eur": pnl,
            })

    # If last bar ends long, close at last price (for backtest completeness)
    if entries:
        entry = entries.pop(0)
        px = float(df["close"].iloc[-1])
        px_fill = _apply_bps(px, slip_bps, adverse=True)
        proceeds = entry["units"] * px_fill * fee_mult
        pnl = proceeds - entry["notional_eur"]
        trades.append({
            "entry_ts": entry["ts"],
            "entry_px": entry["price"],
            "exit_ts": df.index[-1],
            "exit_px": px_fill,
            "qty_eur": entry["notional_eur"],
            "pnl_eur": pnl,
        })

    trades_df = pd.DataFrame(trades)
    start_equity = 1000.0
    eq_ts = []
    eq = start_equity
    ti = 0
    # Build equity curve step-wise at bar closes using position PnL drift from previous fill price
    last_fill_px = None
    last_units = 0.0

    # We'll mark exposure by pos
    for i, (ts, row) in enumerate(df.iterrows()):
        px = float(row["close"])
        if i > 0:
            # drift only if we have open position
            if last_units and last_fill_px is not None:
                # Mark-to-market units at current px (no fees in MTM)
                # delta from previous bar:
                pass  # equity updates only on fills below to keep it simple/robust

        # Handle edges for equity updates using trades table
        while ti < len(trades_df) and trades_df["entry_ts"].iloc[ti] == ts:
            # On entry, we just lock notional; equity does not change at entry (fees embedded in units)
            last_fill_px = float(trades_df["entry_px"].iloc[ti])
            last_units = (qty_eur * fee_mult) / last_fill_px
            ti += 1
        # Check if any trade exits at this ts
        exits_here = trades_df.index[trades_df["exit_ts"] == ts].tolist()
        if exits_here:
            # Recompute equity by adding realized pnl
            for idx in exits_here:
                eq += float(trades_df.loc[idx, "pnl_eur"])
                last_fill_px = None
                last_units = 0.0

        eq_ts.append((ts, eq))

    equity_df = pd.DataFrame(eq_ts, columns=["ts", "equity"]).set_index("ts")
    return equity_df, trades_df

def _metrics_from_equity_and_trades(
    equity_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    exposure_pct: float,
    bars_per_year: float,
) -> Dict[str, Any]:
    start_equity = 1000.0
    final_equity = float(equity_df["equity"].iloc[-1]) if not equity_df.empty else start_equity
    total_return = (final_equity / start_equity) - 1.0  # fraction
    total_return_pct = 100.0 * total_return

    # Max drawdown (on equity curve)
    cummax = equity_df["equity"].cummax()
    drawdown = equity_df["equity"] / cummax - 1.0
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
    max_dd_pct = 100.0 * max_dd  # negative

    # Profit factor
    wins = trades_df["pnl_eur"][trades_df["pnl_eur"] > 0].sum() if not trades_df.empty else 0.0
    losses = -trades_df["pnl_eur"][trades_df["pnl_eur"] < 0].sum() if not trades_df.empty else 0.0
    profit_factor = (wins / losses) if losses > 1e-12 else (math.inf if wins > 0 else 0.0)

    # Sharpe (very rough: per-bar returns variance -> annualize by bars_per_year)
    # here returns only change on fills; to keep consistent, use end-point return:
    # Avoid division by zero
    sharpe = 0.0
    if len(equity_df) > 2:
        rets = equity_df["equity"].pct_change().dropna()
        if rets.std(ddof=0) > 1e-12:
            sharpe = (rets.mean() / rets.std(ddof=0)) * math.sqrt(bars_per_year)

    # CAGR% (using bars_per_year)
    years = max(1e-9, len(equity_df) / bars_per_year)
    cagr = (final_equity / start_equity) ** (1.0 / years) - 1.0
    cagr_pct = 100.0 * cagr

    # Calmar = CAGR% / |MaxDD%|
    calmar = (cagr_pct / abs(max_dd_pct)) if abs(max_dd_pct) > 1e-9 else math.inf

    winrate = 100.0 * ( (trades_df["pnl_eur"] > 0).sum() / len(trades_df) ) if not trades_df.empty else 0.0
    avg_trade = trades_df["pnl_eur"].mean() if not trades_df.empty else 0.0

    out = {
        "bars": int(len(equity_df)),
        "trades": int(len(trades_df)),
        "winrate_pct": round(winrate, 2),
        "total_return_pct": round(total_return_pct, 3),
        "max_drawdown_pct": round(max_dd_pct, 3),
        "final_equity_eur": round(final_equity, 2),
        "start_equity_eur": start_equity,
        "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else float("inf"),
        "avg_trade_eur": round(float(avg_trade), 4),
        "exposure_pct": round(exposure_pct, 2),
        "sharpe": round(sharpe, 3),
        "cagr_pct": round(cagr_pct, 3),
        "calmar": round(calmar, 3) if math.isfinite(calmar) else float("inf"),
    }
    return out

def run_backtest_vectorized(
    cfg: BtConfig,
    *,
    write_artifacts: bool = False,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Main entry point used by CLI/sweep/optimize.
    Returns metrics dict with optional 'trades_csv'/'equity_csv' (or None).
    """
    base = _fetch_exmo_candles(cfg.pair, cfg.span)
    if base.empty:
        raise RuntimeError(f"Empty candles from EXMO for {cfg.pair} span={cfg.span}")

    data = base
    if cfg.resample:
        data = _resample_ohlc(base, cfg.resample)

    # Sanity for SMA windows
    if len(data) < max(cfg.fast, cfg.slow) + 5:
        raise RuntimeError("Not enough candles after resample for SMA windows.")

    equity_df, trades_df = _simulate_on_df(
        data,
        fast=cfg.fast,
        slow=cfg.slow,
        hysteresis_bps=cfg.hysteresis_bps,
        cooldown_bars=cfg.cooldown_bars,
        fee_bps=cfg.fee_bps,
        slip_bps=cfg.slip_bps,
        qty_eur=cfg.qty_eur,
        enter_on_start=cfg.enter_on_start,
    )

    exposure_pct = 100.0 * ( (data.index.to_series().map(lambda x: 1).values * 0 + 1) * 0 ).sum()  # placeholder
    # More accurate exposure from pos series in simulator:
    # We'll recompute quickly:
    close = data["close"]
    sma_fast = _sma(close, cfg.fast)
    sma_slow = _sma(close, cfg.slow)
    pos = _generate_positions(close, sma_fast, sma_slow, cfg.hysteresis_bps, cfg.cooldown_bars)
    exposure_pct = round(100.0 * float(pos.sum()) / float(len(pos)), 2)

    # bars/year based on final rule (resample if provided, else base tf)
    tf, _ = _parse_span(cfg.span)
    rule_for_year = cfg.resample or tf
    bars_per_year = _bars_per_year_from_rule(rule_for_year)

    metrics = _metrics_from_equity_and_trades(equity_df, trades_df, exposure_pct, bars_per_year)
    metrics["pair"] = cfg.pair
    metrics["bars_per_year"] = bars_per_year

    trades_csv = None
    equity_csv = None

    if write_artifacts:
        target_dir = Path(out_dir) if out_dir else Path("data/backtests")
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now_utc_stamp()
        tag = f"{cfg.pair}_{(cfg.resample or tf)}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}_q{int(cfg.qty_eur)}"
        trades_csv = target_dir / f"{tag}_{stamp}_trades.csv"
        equity_csv = target_dir / f"{tag}_{stamp}_equity.csv"
        trades_df.to_csv(trades_csv, index=False)
        equity_df.to_csv(equity_csv)
    metrics["trades_csv"] = str(trades_csv) if trades_csv else None
    metrics["equity_csv"] = str(equity_csv) if equity_csv else None

    return metrics
