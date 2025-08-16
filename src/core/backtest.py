# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, Tuple, List
import math
import numpy as np
import pandas as pd

from src.core.metrics import _compute_metrics_from_equity as compute_metrics
from src.core.metrics import risk_based_qty


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev).abs(),
                    (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()


def run_backtest_sma(
        df: pd.DataFrame,
        fast: int, slow: int,
        *,
        start_eur: float, qty_eur: float,
        fee_bps: float, slip_bps: float,
        position_pct: float = 0.0,
        price_tick: float = 0.0,
        qty_step: float = 0.0,
        min_quote: float = 0.0,
        atr_period: int = 14,
        atr_mult: float = 0.0,
        tp_bps: int = 0,
        risk_pct: float = 0.0,
        atr_pctl_min: float | None = None,
        atr_pctl_max: float | None = None,
        collect_trades: bool = True,
        collect_equity: bool = True,
        warmup_bars: int = 0,
        inventory_method: str = "FIFO",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    d = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True).copy()
    if "time" not in d.columns:
        raise ValueError("df must have 'time' column")

    # индикаторы
    d["sma_fast"] = d["close"].rolling(fast, min_periods=fast).mean()
    d["sma_slow"] = d["close"].rolling(slow, min_periods=slow).mean()
    tr = pd.concat([
        (d["high"] - d["low"]).abs(),
        (d["high"] - d["close"].shift(1)).abs(),
        (d["low"] - d["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    d["atr"] = tr.rolling(atr_period, min_periods=atr_period).mean()

    if atr_pctl_min is not None or atr_pctl_max is not None:
        atr_vals = d["atr"].dropna()
        lo = np.percentile(atr_vals, atr_pctl_min if atr_pctl_min is not None else 0.0) if len(atr_vals) else np.nan
        hi = np.percentile(atr_vals, atr_pctl_max if atr_pctl_max is not None else 100.0) if len(atr_vals) else np.nan
        d["atr_ok"] = (d["atr"] >= lo) & (d["atr"] <= hi) if np.isfinite(lo) and np.isfinite(hi) else False
    else:
        d["atr_ok"] = True

    d["cross_up"] = (d["sma_fast"] > d["sma_slow"]) & (d["sma_fast"].shift(1) <= d["sma_slow"].shift(1))
    d["cross_dn"] = (d["sma_fast"] < d["sma_slow"]) & (d["sma_fast"].shift(1) >= d["sma_slow"].shift(1))

    equity = float(start_eur)
    pos_qty = 0.0
    pos_entry = 0.0
    fifo: List[List[float]] = []  # [[qty, price], ...]

    trades: List[Dict[str, Any]] = []
    eq: List[Dict[str, Any]] = []

    def _enter(qty: float, px: float, t):
        nonlocal equity, pos_qty, pos_entry
        if qty <= 0: return
        cost = qty * px
        fee = cost * (fee_bps / 1e4)
        slip = cost * (slip_bps / 1e4)
        total = cost + fee + slip
        if total > equity + 1e-9:
            return
        equity -= total
        fifo.append([qty, px])
        pos_qty += qty
        pos_entry = px
        if collect_trades:
            trades.append({"time": t, "side": "buy", "qty": qty, "price": px, "fee": fee, "slip": slip})

    def _exit(qty: float, px: float, t):
        nonlocal equity, pos_qty, pos_entry
        if qty <= 0 or pos_qty <= 0: return
        qty = min(qty, pos_qty)
        realised = 0.0
        qleft = qty
        while qleft > 1e-12 and fifo:
            lot_q, lot_px = fifo[0]
            take = min(qleft, lot_q)
            realised += (px - lot_px) * take
            lot_q -= take
            qleft -= take
            if lot_q <= 1e-12:
                fifo.pop(0)
            else:
                fifo[0][0] = lot_q
        revenue = qty * px
        fee = revenue * (fee_bps / 1e4)
        slip = revenue * (slip_bps / 1e4)
        equity += (revenue - fee - slip)
        pos_qty -= qty
        if pos_qty <= 1e-12:
            pos_qty = 0.0
            pos_entry = 0.0
        if collect_trades:
            trades.append(
                {"time": t, "side": "sell", "qty": qty, "price": px, "fee": fee, "slip": slip, "pnl": realised})

    tp_mult = (tp_bps / 1e4) if tp_bps and tp_bps > 0 else 0.0
    start_i = max(fast, slow, atr_period, warmup_bars)

    for i in range(start_i, len(d)):
        row = d.iloc[i]
        t = row["time"]
        c = float(row["close"])
        h = float(row["high"])
        l = float(row["low"])
        atr = float(row["atr"]) if np.isfinite(row["atr"]) else np.nan

        if collect_equity:
            eq.append({"time": t, "equity": equity + pos_qty * c})

        # стоп/тейк по позиции
        if pos_qty > 0:
            stop_px = pos_entry - (atr_mult * atr) if (atr_mult and np.isfinite(atr)) else -np.inf
            tp_px = pos_entry * (1.0 + tp_mult) if tp_mult > 0 else np.inf
            done = False
            if l <= stop_px:
                _exit(pos_qty, stop_px, t)
                done = True
            elif h >= tp_px:
                _exit(pos_qty, tp_px, t)
                done = True
            if not done and bool(row["cross_dn"]):
                _exit(pos_qty, c, t)

        # вход
        if pos_qty == 0 and bool(row["cross_up"]) and bool(row["atr_ok"]):
            entry = c
            stop_for_risk = entry - (atr_mult * atr) if (atr_mult and np.isfinite(atr)) else (entry * 0.995)
            qty = 0.0
            if risk_pct and risk_pct > 0.0:
                qty = risk_based_qty(equity, entry, stop_for_risk, risk_pct, price_tick, qty_step, min_quote)
            elif position_pct and position_pct > 0.0:
                budget = equity * (position_pct / 100.0)
                px = max(entry, price_tick or entry)
                qty = budget / px
                if qty_step and qty_step > 0:
                    qty = math.floor(qty / qty_step) * qty_step
            else:
                px = max(entry, price_tick or entry)
                qty = (qty_eur / px)
                if qty_step and qty_step > 0:
                    qty = math.floor(qty / qty_step) * qty_step
            if qty > 0:
                _enter(qty, entry, t)

    if pos_qty > 0:
        last_c = float(d["close"].iloc[-1])
        _exit(pos_qty, last_c, d["time"].iloc[-1])

    equity_df = pd.DataFrame(eq) if collect_equity else pd.DataFrame(columns=["time", "equity"])
    trades_df = pd.DataFrame(trades) if collect_trades else pd.DataFrame(columns=["time", "side", "qty", "price"])
    report = {"metrics": compute_metrics(equity_df if collect_equity else None, trades, start_eur),
              "fast": fast, "slow": slow}
    return trades_df, equity_df, report
