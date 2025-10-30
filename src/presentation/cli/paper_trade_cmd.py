#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_trade_cmd: листовой и авто-режимы.

- Leaf: печатает JSON {"net","net_pnl","trades"} и (опционально) plain-строку "net=<..> trades=<..>" для свипера.
- Auto: запускает sweep_cli с явным --paper-cli "<python> -m src.presentation.cli.paper_trade_cmd --emit-plain"
        и затем ранкинг (rank_cli или надёжный inline fallback).

Зависимости: pandas, numpy.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import pandas as pd
import numpy as np

# ----------------------------- Индикаторы -----------------------------

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()

def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.rolling(window=length, min_periods=length).mean()

def _dm_pos_neg(high: pd.Series, low: pd.Series) -> Tuple[pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    return pd.Series(plus_dm, index=high.index), pd.Series(minus_dm, index=high.index)

def adx_di(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    tr = true_range(high, low, close)
    plus_dm, minus_dm = _dm_pos_neg(high, low)
    atr_s = tr.rolling(window=length, min_periods=length).mean()
    plus_di = 100.0 * (pd.Series(plus_dm, index=high.index).rolling(length, min_periods=length).mean() / atr_s)
    minus_di = 100.0 * (pd.Series(minus_dm, index=high.index).rolling(length, min_periods=length).mean() / atr_s)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_val = dx.rolling(window=length, min_periods=length).mean()
    return adx_val, plus_di, minus_di

# ----------------------------- Ресемплинг -----------------------------

_PANDAS_TF = {
    "1min": "1min", "3min": "3min", "5min": "5min", "15min": "15min", "30min": "30min",
    "1h": "1H", "2h": "2H", "4h": "4H",
    "1d": "1D",
}
def _to_pd_tf(tf: str) -> str:
    tf = tf.strip().lower()
    return _PANDAS_TF.get(tf, tf)

def resample_ohlcv(df: pd.DataFrame, tf: str, time_col: str = "time") -> pd.DataFrame:
    rule = _to_pd_tf(tf)
    ohlc = df.resample(rule, on=time_col).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    ohlc = ohlc.dropna().reset_index(names=[time_col])
    return ohlc

# ----------------------------- Бэктестер (лонг) -----------------------------

@dataclass
class Trade:
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    pnl_gross: float
    fees: float
    pnl_net: float

@dataclass
class Config:
    ohlcv: str; time_col: str; resample: str
    ema_fast: int; ema_slow: int
    adx_len: int; adx_on: float; adx_off: float; require_di: bool
    atr_len: int; stop_atr: float; take_atr: float; trail_atr: float
    breakeven_rr: float; trail_activate_rr: float
    entry_lag: int; cooldown_bars: int; min_hold_bars: int; fill_mode: str
    fee_bps: float; slip_bps: float; qty: float

def _price_with_slip(price: float, slip_bps: float, side: str) -> float:
    m = slip_bps / 10000.0
    return price * (1.0 + m) if side == "buy" else price * (1.0 - m)

def _fees_for_trade(entry_px_eff: float, exit_px_eff: float, qty: float, fee_bps: float) -> float:
    turn = (abs(entry_px_eff) + abs(exit_px_eff)) * abs(qty)
    return turn * (fee_bps / 10000.0)

def run_backtest(cfg: Config) -> Tuple[List[Trade], Dict[str, float]]:
    df = pd.read_csv(cfg.ohlcv)
    time_col = cfg.time_col if cfg.time_col else "timestamp"
    if time_col not in df.columns:
        for alt in ("time", "timestamp", "date"):
            if alt in df.columns:
                time_col = alt; break
    df = df.rename(columns={time_col: "time"})
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            if "price" in df.columns:
                df["open"] = df["high"] = df["low"] = df["close"] = df["price"]; break
            raise SystemExit(f"CSV missing columns: {c}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time")

    ohlc = resample_ohlcv(df, cfg.resample, time_col="time")
    if len(ohlc) < max(cfg.ema_fast, cfg.ema_slow, cfg.adx_len, cfg.atr_len) + 5:
        return [], {"net": 0.0, "net_pnl": 0.0, "trades": 0}

    ohlc["ema_fast"] = ema(ohlc["close"], cfg.ema_fast)
    ohlc["ema_slow"] = ema(ohlc["close"], cfg.ema_slow)
    ohlc["atr"] = atr(ohlc["high"], ohlc["low"], ohlc["close"], cfg.atr_len)
    ohlc["adx"], ohlc["+di"], ohlc["-di"] = adx_di(ohlc["high"], ohlc["low"], ohlc["close"], cfg.adx_len)

    cross_up = (ohlc["ema_fast"] > ohlc["ema_slow"]) & (ohlc["ema_fast"].shift(1) <= ohlc["ema_slow"].shift(1))
    adx_ok = ohlc["adx"] >= cfg.adx_on
    di_ok = (ohlc["+di"] > ohlc["-di"]) if cfg.require_di else pd.Series(True, index=ohlc.index)
    entries = cross_up & adx_ok & di_ok

    in_pos = False; entry_idx = -1; entry_price = 0.0; risk_atr = 0.0
    stop = np.nan; take = np.nan; trail_active = False; peak = -np.inf
    last_exit_idx = -10_000
    trades: List[Trade] = []

    for i in range(len(ohlc)):
        row = ohlc.iloc[i]
        if not in_pos:
            if (i - last_exit_idx) >= max(0, cfg.cooldown_bars) and entries.iloc[i]:
                j = i + max(0, cfg.entry_lag)
                if j < len(ohlc):
                    entry_idx = j
                    entry_price = float(ohlc["close"].iloc[entry_idx])
                    risk_atr = float(ohlc["atr"].iloc[entry_idx]) * max(1e-12, cfg.stop_atr)
                    stop = entry_price - cfg.stop_atr * float(ohlc["atr"].iloc[entry_idx])
                    take = np.nan if cfg.take_atr <= 0 else entry_price + cfg.take_atr * float(ohlc["atr"].iloc[entry_idx])
                    trail_active = False; peak = entry_price; in_pos = True
            continue

        c = float(row["close"]); h = float(row["high"]); l = float(row["low"])
        a = float(row["atr"]) if not math.isnan(row["atr"]) else risk_atr
        peak = max(peak, c)

        rr_now = (c - entry_price) / max(risk_atr, 1e-12)
        if not trail_active and cfg.trail_activate_rr > 0 and rr_now >= cfg.trail_activate_rr:
            trail_active = True
        if cfg.breakeven_rr > 0 and rr_now >= cfg.breakeven_rr:
            stop = max(stop, entry_price)
        if trail_active and cfg.trail_atr > 0:
            stop = max(stop, c - cfg.trail_atr * a)

        trend_exit = False
        if (i - entry_idx) >= max(0, cfg.min_hold_bars):
            cross_down = (ohlc["ema_fast"].iloc[i] < ohlc["ema_slow"].iloc[i]) and (
                ohlc["ema_fast"].iloc[i - 1] >= ohlc["ema_slow"].iloc[i - 1]
            )
            adx_off = ohlc["adx"].iloc[i] <= cfg.adx_off
            trend_exit = bool(cross_down or adx_off)

        exit_price: Optional[float] = None
        if not math.isnan(stop) and l <= stop:
            exit_price = stop
        elif not math.isnan(take) and h >= take:
            exit_price = take
        elif trend_exit:
            exit_price = c

        if exit_price is not None:
            entry_eff = _price_with_slip(entry_price, cfg.slip_bps, "buy")
            exit_eff = _price_with_slip(exit_price, cfg.slip_bps, "sell")
            pnl_gross = (exit_eff - entry_eff) * cfg.qty
            fees = _fees_for_trade(entry_eff, exit_eff, cfg.qty, cfg.fee_bps)
            pnl_net = pnl_gross - fees
            trades.append(Trade(entry_idx, i, entry_price, exit_price, pnl_gross, fees, pnl_net))
            in_pos = False; last_exit_idx = i
            entry_idx = -1; entry_price = 0.0; stop = np.nan; take = np.nan; trail_active = False; peak = -np.inf

    net = float(np.nansum([t.pnl_net for t in trades])) if trades else 0.0
    return trades, {"net": net, "net_pnl": net, "trades": len(trades)}

# ----------------------------- Inline ranking -----------------------------

def _rank_inline(sweep_csv: str, out_top: str, out_robust: str, objective: str = "net_pnl", top_k: int = 50) -> int:
    if not os.path.exists(sweep_csv):
        print(f"[paper-cmd][rank-inline] file not found: {sweep_csv}", file=sys.stderr)
        return 1
    df = pd.read_csv(sweep_csv).replace([np.inf, -np.inf], np.nan)
    if objective not in df.columns and "net" in df.columns:
        df["net_pnl"] = df["net"]; objective = "net_pnl"
    df = df.dropna(subset=[objective])
    if "trades" in df.columns:
        df = df[df["trades"] > 0]
    if df.empty:
        print("[paper-cmd][rank-inline] no champion candidate rows", file=sys.stderr)
        pd.DataFrame().to_csv(out_top, index=False)
        pd.DataFrame().to_csv(out_robust, index=False)
        return 1
    top = df.sort_values(objective, ascending=False).head(top_k)
    top.to_csv(out_top, index=False)
    thr = top[objective].median()
    if "trades" in top.columns:
        min_trades = max(1, int(top["trades"].median()))
        robust = top[(top[objective] >= thr) & (top["trades"] >= min_trades)]
    else:
        robust = top
    robust.to_csv(out_robust, index=False)
    print(f"[paper-cmd][rank-inline] saved: {out_top} ({len(top)} rows)")
    print(f"[paper-cmd][rank-inline] saved: {out_robust} ({len(robust)} rows)")
    return 0

def _parse_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "t", "yes", "y")

# ----------------------------- CLI -----------------------------

def build_leaf_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paper-trade", add_help=True)
    add = p.add_argument
    add("--ohlcv", required=True)
    add("--time-col", default="timestamp")
    add("--resample", required=True)
    add("--ema-fast", type=int, required=True)
    add("--ema-slow", type=int, required=True)
    add("--adx-len", type=int, required=True)
    add("--adx-on", type=float, required=True)
    add("--adx-off", type=float, required=True)
    add("--require-di", type=str, required=True)
    add("--htf-tf", default="")
    add("--htf-ema-fast", type=int, default=0)
    add("--htf-ema-slow", type=int, default=0)
    add("--atr-len", type=int, default=14)
    add("--stop-atr", type=float, required=True)
    add("--take-atr", type=float, default=0.0)
    add("--trail-atr", type=float, default=0.0)
    add("--breakeven-rr", type=float, default=0.0)
    add("--trail-activate-rr", type=float, default=0.0)
    add("--entry-lag", type=int, default=0)
    add("--cooldown-bars", type=int, required=True)
    add("--min-hold-bars", type=int, default=0)
    add("--fill-mode", default="close")
    add("--fee-bps", type=float, required=True)
    add("--slip-bps", type=float, required=True)
    add("--qty", type=float, required=True)
    # совместимость со свипером
    add("--emit-plain", action="store_true", help="в конце stdout напечатать 'net=<..> trades=<..>'")
    return p

def build_auto_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="paper_trade_cmd", add_help=True)
    ap.add_argument("--sweep-args", help="строка аргументов для sweep_cli")
    ap.add_argument("--rank-args", help="строка аргументов для rank_cli", default="")
    ap.add_argument("--wf-splits", type=int, default=0)
    ap.add_argument("--wf-min-trades", type=int, default=0)
    ap.add_argument("--cache-all", action="store_true")
    return ap

def run_leaf(ns: argparse.Namespace) -> int:
    cfg = Config(
        ohlcv=ns.ohlcv, time_col=ns.time_col, resample=ns.resample,
        ema_fast=ns.ema_fast, ema_slow=ns.ema_slow,
        adx_len=ns.adx_len, adx_on=ns.adx_on, adx_off=ns.adx_off, require_di=_parse_bool(ns.require_di),
        atr_len=ns.atr_len, stop_atr=ns.stop_atr, take_atr=ns.take_atr, trail_atr=ns.trail_atr,
        breakeven_rr=ns.breakeven_rr, trail_activate_rr=ns.trail_activate_rr,
        entry_lag=ns.entry_lag, cooldown_bars=ns.cooldown_bars, min_hold_bars=ns.min_hold_bars, fill_mode=ns.fill_mode,
        fee_bps=ns.fee_bps, slip_bps=ns.slip_bps, qty=ns.qty,
    )
    _, summary = run_backtest(cfg)
    # 1) JSON — удобно людям и интеграциям
    print(json.dumps(summary, ensure_ascii=False))
    # 2) Совместимость со свипером — последняя строка простая
    if getattr(ns, "emit-plain", False):
        net = summary.get("net")
        trades = summary.get("trades")
        # последняя строка stdout:
        print(f"net={net} trades={trades}")
    return 0

def run_auto(ns: argparse.Namespace) -> int:
    # 1) sweep с ЯВНЫМ paper-cli: "<python> -m src.presentation.cli.paper_trade_cmd --emit-plain"
    py = shlex.quote(sys.executable)
    paper_cli_str = f"{py} -m src.presentation.cli.paper_trade_cmd --emit-plain"

    sweep_cmd = [sys.executable, "-m", "src.presentation.cli.sweep_cli"]
    if ns.sweep_args:
        sweep_cmd += shlex.split(ns.sweep_args)
    sweep_cmd += ["--paper-cli", paper_cli_str]

    print(f"[paper-cmd] exec:", " ".join(sweep_cmd), flush=True)
    rc = subprocess.run(sweep_cmd).returncode
    if rc != 0:
        print(f"[paper-cmd] ERROR: sweep step failed with rc={rc}", file=sys.stderr)
        return rc

    # 2) ранкинг (попытка модулем, затем inline fallback)
    rank_cmd = [sys.executable, "-m", "src.presentation.cli.rank_cli"]
    if ns.rank_args:
        rank_cmd += shlex.split(ns.rank_args)
    try:
        print(f"[paper-cmd] exec:", " ".join(rank_cmd), flush=True)
        rc_rank = subprocess.run(rank_cmd).returncode
        if rc_rank == 0:
            return 0
        else:
            print(f"[paper-cmd] WARN: rank_cli returned rc={rc_rank} — using inline ranking", file=sys.stderr)
    except Exception:
        print(f"[paper-cmd] WARN: rank_cli not found — using inline ranking", file=sys.stderr)

    # inline fallback — параметры вытащим из rank_args, если были
    sweep_csv = "reports/sweep_full.csv"; out_top = "reports/top_ranked.csv"; out_robust = "reports/top_robust.csv"
    objective = "net_pnl"; top_k = 50
    toks = shlex.split(ns.rank_args or "")
    it = iter(toks)
    for t in it:
        if t == "--in":            sweep_csv = next(it, sweep_csv)
        elif t == "--out-top":     out_top = next(it, out_top)
        elif t == "--out-robust":  out_robust = next(it, out_robust)
        elif t == "--objective":   objective = next(it, objective)
        elif t == "--top-k":
            try: top_k = int(next(it, str(top_k)))
            except Exception: pass

    return _rank_inline(sweep_csv, out_top, out_robust, objective, top_k)

def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    leaf_flags = {"--ohlcv","--resample","--ema-fast","--ema-slow","--adx-len","--adx-on","--adx-off",
                  "--require-di","--stop-atr","--cooldown-bars","--fee-bps","--slip-bps","--qty","--emit-plain"}
    if any(f in argv for f in leaf_flags):
        parser_leaf = build_leaf_parser()
        ns = parser_leaf.parse_args(argv)
        return run_leaf(ns)
    parser_auto = build_auto_parser()
    ns = parser_auto.parse_args(argv)
    if not ns.sweep_args:
        build_leaf_parser().print_help(sys.stderr)
        return 2
    return run_auto(ns)

if __name__ == "__main__":
    sys.exit(main())
