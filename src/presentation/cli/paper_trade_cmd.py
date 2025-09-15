# -*- coding: utf-8 -*-
"""
Paper trading over stored signals in SQLite.

Usage (examples):
  python -m src.presentation.cli.paper_trade_cmd --limit 200
  python -m src.presentation.cli.paper_trade_cmd \
    --db sqlite:///data/bot.db \
    --symbol DEMO --timeframe 5min --strategy ema_adx_atr --run-id e2e-demo-1 \
    --fill-mode next_open --entry-lag 0 \
    --atr-period 14 --atr-method sma \
    --atr-mult-stop 1.5 --atr-mult-take 3.0 \
    --risk-pct 0.01 --initial-cash 10000 \
    --fee-bps 5 --slip-bps 2 \
    --export-csv /tmp/trades.csv
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from typing import Optional, Tuple, List, Dict

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# DB I/O
# ─────────────────────────────────────────────────────────────────────────────
def _db_path_from_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return url


def _read_signals(
        db_url: str,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        strategy: Optional[str] = None,
        run_id: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = None,
) -> pd.DataFrame:
    path = _db_path_from_url(db_url)
    conn = sqlite3.connect(path)
    try:
        sql = (
            "SELECT time, symbol, timeframe, strategy, side, price, run_id "
            "FROM signals WHERE 1=1"
        )
        params: List = []
        if symbol:
            sql += " AND symbol=?"
            params.append(symbol)
        if timeframe:
            sql += " AND timeframe=?"
            params.append(timeframe)
        if strategy:
            sql += " AND strategy=?"
            params.append(strategy)
        if run_id:
            sql += " AND run_id=?"
            params.append(run_id)
        if start:
            sql += " AND time>=?"
            params.append(start)
        if end:
            sql += " AND time<=?"
            params.append(end)
        sql += " ORDER BY time ASC"
        if limit and limit > 0:
            sql += f" LIMIT {int(limit)}"

        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()

    return df


def _read_candles(
        db_url: str,
        symbol: Optional[str],
        timeframe: Optional[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
) -> pd.DataFrame:
    path = _db_path_from_url(db_url)
    conn = sqlite3.connect(path)
    try:
        sql = "SELECT time, symbol, timeframe, open, high, low, close, volume FROM candles WHERE 1=1"
        params: List = []
        if symbol:
            sql += " AND symbol=?"
            params.append(symbol)
        if timeframe:
            sql += " AND timeframe=?"
            params.append(timeframe)
        if start:
            sql += " AND time>=?"
            params.append(start)
        if end:
            sql += " AND time<=?"
            params.append(end)
        sql += " ORDER BY time ASC"
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
def _to_utc_ts(t) -> pd.Timestamp:
    ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _parse_tf_minutes(tf: str) -> Optional[int]:
    """Parse timeframe like '1min','5min','15min','1h' → minutes."""
    tf = (tf or "").lower()
    if tf.endswith("min"):
        try:
            return int(tf[:-3])
        except Exception:
            return None
    if tf.endswith("m"):
        try:
            return int(tf[:-1])
        except Exception:
            return None
    if tf.endswith("h"):
        try:
            return int(tf[:-1]) * 60
        except Exception:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# NextOpenLookup & ATR
# ─────────────────────────────────────────────────────────────────────────────
class NextOpenLookup:
    """
    Быстрый доступ к:
      • next_open(symbol,timeframe, t)  -> (open_price, open_timestamp) след. свечи строго после t
      • atr_at(symbol,timeframe, t, period, method) -> float ATR по последней закрытой свече ≤ t
    """

    def __init__(self, candles_df: pd.DataFrame):
        df = candles_df.copy()
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"])
        df = df.sort_values(["symbol", "timeframe", "time"])
        df = df.set_index("time")
        self.df = df
        self._atr_cache: Dict[Tuple[str, str, int, str], pd.Series] = {}

    @classmethod
    def from_db(
            cls,
            db_url_or_path: str,
            symbol: Optional[str] = None,
            timeframe: Optional[str] = None,
            start: Optional[str] = None,
            end: Optional[str] = None,
    ) -> "NextOpenLookup":
        df = _read_candles(db_url_or_path, symbol=symbol, timeframe=timeframe, start=start, end=end)
        if df.empty:
            raise RuntimeError("No candles found for NextOpenLookup")
        return cls(df)

    def _subset(self, symbol: str, timeframe: str) -> pd.DataFrame:
        sub = self.df[(self.df["symbol"] == symbol) & (self.df["timeframe"] == timeframe)]
        if sub.empty:
            raise RuntimeError(f"No candles for {symbol} {timeframe}")
        return sub

    def next_open(self, symbol: str, timeframe: str, t) -> Optional[Tuple[float, pd.Timestamp]]:
        """Цена открытия следующей свечи строго ПОСЛЕ t. Возвращает (open, ts) или None."""
        sub = self._subset(symbol, timeframe)
        ts = _to_utc_ts(t)
        idx = sub.index.searchsorted(ts, side="right")
        if idx >= len(sub):
            return None
        row = sub.iloc[idx]
        return float(row["open"]), sub.index[idx]

    def atr_at(self, symbol: str, timeframe: str, t, period: int = 14, method: str = "sma") -> Optional[float]:
        """ATR на момент t (по последней закрытой свече ≤ t)."""
        key = (symbol, timeframe, int(period), method.lower())
        if key not in self._atr_cache:
            sub = self._subset(symbol, timeframe)[["open", "high", "low", "close"]].copy()
            self._atr_cache[key] = _compute_atr(sub, period=period, method=method)
        s = self._atr_cache[key]
        ts = _to_utc_ts(t)
        pos = s.index.searchsorted(ts, side="right") - 1
        if pos < 0:
            return None
        v = float(s.iloc[pos])
        return None if np.isnan(v) else v


def _compute_atr(cdf: pd.DataFrame, period: int = 14, method: str = "sma") -> pd.Series:
    """Возвращает серию ATR (index=time, tz-aware UTC) поверх свечей cdf(open,high,low,close)."""
    if cdf.empty:
        return pd.Series(dtype=float)

    df = cdf.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"]).set_index("time")
    df = df.sort_index()

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    method = (method or "sma").lower()
    if method == "ema":
        atr = tr.ewm(span=int(period), adjust=False, min_periods=int(period)).mean()
    else:
        atr = tr.rolling(window=int(period), min_periods=int(period)).mean()

    return atr


# ─────────────────────────────────────────────────────────────────────────────
# Trading logic
# ─────────────────────────────────────────────────────────────────────────────
def _exec_price_with_slippage(side_from: str, side_to: str, px: float, slip_bps: float, is_entry: bool) -> float:
    """Хужее исполнение в пользу рынка (buy дороже, sell дешевле)."""
    slip = float(slip_bps or 0.0) / 10_000.0
    if side_from == "FLAT" and side_to == "LONG":  # buy
        return px * (1.0 + slip)
    if side_from == "FLAT" and side_to == "SHORT":  # sell
        return px * (1.0 - slip)
    if side_from == "LONG" and side_to in ("SHORT", "FLAT"):  # sell
        return px * (1.0 - slip)
    if side_from == "SHORT" and side_to in ("LONG", "FLAT"):  # buy
        return px * (1.0 + slip)
    return px


def _trade_fee(cost_bps: float, price: float, qty: float) -> float:
    return (float(cost_bps or 0.0) / 10_000.0) * float(price) * float(qty)


def _position_size_for_risk(equity: float, entry_px: float, stop_px: Optional[float],
                            risk_pct: Optional[float]) -> float:
    """Простой sizing: (equity * risk_pct) / расстояние до стопа. Без стопа → 1.0."""
    if not risk_pct or not stop_px or entry_px <= 0:
        return 1.0
    risk_cash = max(0.0, float(equity) * float(risk_pct))
    dist = abs(float(entry_px) - float(stop_px))
    if dist <= 0:
        return 1.0
    return max(0.0, risk_cash / dist)


def simulate_trades(
        df_signals: pd.DataFrame,
        *,
        fee_bps: float = 0.0,
        slip_bps: float = 0.0,
        fill_mode: str = "signal",  # 'signal' | 'next_open'
        entry_lag: int = 0,  # для next_open: сколько "следующих open" отмотать вперёд
        next_open_lookup: Optional[NextOpenLookup] = None,
        # ATR-based exits / sizing
        atr_period: int = 14,
        atr_method: str = "sma",
        atr_mult_stop: Optional[float] = None,
        atr_mult_take: Optional[float] = None,
        # fixed pct exits (альтернатива ATR), trailing (упрощённо по точкам сигналов)
        stop_pct: Optional[float] = None,
        take_pct: Optional[float] = None,
        trail_pct: Optional[float] = None,
        # money management
        risk_pct: Optional[float] = None,
        initial_cash: float = 0.0,
) -> pd.DataFrame:
    """
    Принимает df сигналов (time, symbol, timeframe, side, price[, run_id...]).
    Возвращает DataFrame trades: entry_time, exit_time, side, entry, exit, pnl, bars.
    """
    if df_signals.empty:
        return pd.DataFrame(columns=["entry_time", "exit_time", "side", "entry", "exit", "pnl", "bars"])

    df = df_signals.copy()
    # normalize time
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"]).sort_values("time")
    else:
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("signals must have 'time' column or DatetimeIndex")
        df = df.sort_index().reset_index().rename(columns={"index": "time"})

    # presence checks
    for col in ("symbol", "timeframe", "side"):
        if col not in df.columns:
            raise ValueError(f"signals are missing column '{col}'")

    fill_mode = (fill_mode or "signal").lower()
    if fill_mode not in ("signal", "next_open"):
        raise ValueError("fill_mode must be 'signal' or 'next_open'")

    # local helper: where do we fill & what price
    def _fill_price_for_signal(row) -> Optional[Tuple[float, pd.Timestamp]]:
        if fill_mode == "signal":
            return float(row["price"]), _to_utc_ts(row["time"])
        # next_open:
        if next_open_lookup is None:
            return None
        res = next_open_lookup.next_open(str(row["symbol"]), str(row["timeframe"]), row["time"])
        if res is None:
            return None
        px, ots = res
        if entry_lag and entry_lag > 0:
            sub = next_open_lookup._subset(str(row["symbol"]), str(row["timeframe"]))
            pos = sub.index.searchsorted(ots, side="left") + entry_lag - 1
            if pos >= len(sub):
                return None
            px = float(sub.iloc[pos]["open"])
            ots = sub.index[pos]
        return float(px), ots

    trades = []
    curr_side = "FLAT"
    entry_px: Optional[float] = None
    entry_ts: Optional[pd.Timestamp] = None
    entry_qty: float = 0.0
    # protective levels
    stop_px: Optional[float] = None
    take_px: Optional[float] = None
    best_px: Optional[float] = None  # для trail

    equity = float(initial_cash or 0.0)

    for _, row in df.iterrows():
        side = str(row["side"]).upper().strip()
        if side not in ("LONG", "SHORT", "FLAT"):
            continue

        # protective exit check (на уровне "точек сигналов" — без прокрутки внутри бара)
        if curr_side in ("LONG", "SHORT") and fill_mode in ("signal", "next_open"):
            maybe = _fill_price_for_signal(row)
            if maybe is None:
                continue
            px_raw, ts_used = maybe

            # обновим trailing экстремум (по точкам сигналов/входов)
            if trail_pct:
                if curr_side == "LONG":
                    best_px = max(best_px or px_raw, px_raw)
                    trail_stop = (1.0 - float(trail_pct)) * float(best_px)
                else:  # SHORT
                    best_px = min(best_px or px_raw, px_raw)
                    trail_stop = (1.0 + float(trail_pct)) * float(best_px)
            else:
                trail_stop = None

            # условие срабатывания защитных выходов
            exit_by_protect = False
            if curr_side == "LONG":
                if stop_px and px_raw <= stop_px:
                    exit_by_protect = True
                if take_px and px_raw >= take_px:
                    exit_by_protect = True
                if trail_stop and px_raw <= trail_stop:
                    exit_by_protect = True
            else:  # SHORT
                if stop_px and px_raw >= stop_px:
                    exit_by_protect = True
                if take_px and px_raw <= take_px:
                    exit_by_protect = True
                if trail_stop and px_raw >= trail_stop:
                    exit_by_protect = True

            if exit_by_protect:
                px_exit = _exec_price_with_slippage(curr_side, "FLAT", px_raw, slip_bps, is_entry=False)
                fee_exit = _trade_fee(fee_bps, px_exit, entry_qty)
                if curr_side == "LONG":
                    pnl = entry_qty * (px_exit - float(entry_px)) - fee_exit
                else:
                    pnl = entry_qty * (float(entry_px) - px_exit) - fee_exit
                equity += pnl

                # bars (примерная оценка по timeframe)
                bars_val = 0
                tf_min = _parse_tf_minutes(str(row["timeframe"]))
                if tf_min and entry_ts is not None:
                    bars_val = int((_to_utc_ts(ts_used) - _to_utc_ts(entry_ts)).total_seconds() // (tf_min * 60))

                trades.append(
                    {
                        "entry_time": _to_utc_ts(entry_ts).isoformat(),
                        "exit_time": _to_utc_ts(ts_used).isoformat(),
                        "side": curr_side,
                        "entry": float(entry_px),
                        "exit": float(px_exit),
                        "pnl": float(pnl),
                        "bars": int(bars_val),
                    }
                )
                # позиция закрыта
                curr_side = "FLAT"
                entry_px = None
                entry_ts = None
                entry_qty = 0.0
                stop_px = take_px = best_px = None
                # важно: после защитного выхода мы не обрабатываем смену сигнала в ту же точку —
                #       это упрощение. При желании можно добавить переворот.
                continue

        # далее — обработка обычного изменения сайда
        if side == curr_side:
            continue

        res = _fill_price_for_signal(row)
        if res is None:
            continue
        px_raw, ts_used = res

        # вход
        if curr_side == "FLAT" and side in ("LONG", "SHORT"):
            # рассчёт защитных уровней (ATR или fixed pct)
            # приоритет: fixed pct, затем ATR
            stop_px = take_px = None
            if stop_pct or take_pct:
                if side == "LONG":
                    if stop_pct:
                        stop_px = float(px_raw) * (1.0 - float(stop_pct))
                    if take_pct:
                        take_px = float(px_raw) * (1.0 + float(take_pct))
                else:  # SHORT
                    if stop_pct:
                        stop_px = float(px_raw) * (1.0 + float(stop_pct))
                    if take_pct:
                        take_px = float(px_raw) * (1.0 - float(take_pct))
            elif (atr_mult_stop or atr_mult_take) and (next_open_lookup is not None):
                atr = next_open_lookup.atr_at(str(row["symbol"]), str(row["timeframe"]), ts_used, atr_period,
                                              atr_method)
                if atr is not None and not np.isnan(atr):
                    if atr_mult_stop:
                        stop_px = float(px_raw) - float(atr_mult_stop) * float(atr) if side == "LONG" else float(
                            px_raw) + float(atr_mult_stop) * float(atr)
                    if atr_mult_take:
                        take_px = float(px_raw) + float(atr_mult_take) * float(atr) if side == "LONG" else float(
                            px_raw) - float(atr_mult_take) * float(atr)

            # размер позиции
            entry_qty = _position_size_for_risk(equity, float(px_raw), stop_px, risk_pct)
            # исполнение
            px_entry = _exec_price_with_slippage("FLAT", side, float(px_raw), slip_bps, is_entry=True)
            fee_entry = _trade_fee(fee_bps, px_entry, entry_qty)
            equity -= fee_entry

            curr_side = side
            entry_px = float(px_entry)
            entry_ts = _to_utc_ts(ts_used)
            # init trailing
            best_px = float(px_entry)
            continue

        # выход / переворот
        if curr_side in ("LONG", "SHORT") and side != curr_side:
            px_exit = _exec_price_with_slippage(curr_side, side, float(px_raw), slip_bps, is_entry=False)
            fee_exit = _trade_fee(fee_bps, px_exit, entry_qty)
            if curr_side == "LONG":
                pnl = entry_qty * (px_exit - float(entry_px)) - fee_exit
            else:
                pnl = entry_qty * (float(entry_px) - px_exit) - fee_exit
            equity += pnl

            # bars
            bars_val = 0
            tf_min = _parse_tf_minutes(str(row["timeframe"]))
            if tf_min and entry_ts is not None:
                bars_val = int((_to_utc_ts(ts_used) - _to_utc_ts(entry_ts)).total_seconds() // (tf_min * 60))

            trades.append(
                {
                    "entry_time": _to_utc_ts(entry_ts).isoformat(),
                    "exit_time": _to_utc_ts(ts_used).isoformat(),
                    "side": curr_side,
                    "entry": float(entry_px),
                    "exit": float(px_exit),
                    "pnl": float(pnl),
                    "bars": int(bars_val) if fill_mode == "next_open" else 0,
                }
            )

            # если переворот — открыть новую
            if side in ("LONG", "SHORT"):
                # обнулим и сразу войдём
                curr_side = "FLAT"
                entry_px = None
                entry_ts = None
                entry_qty = 0.0
                stop_px = take_px = best_px = None

                # вход после выхода
                # защитные уровни
                if stop_pct or take_pct:
                    if side == "LONG":
                        stop_px = float(px_raw) * (1.0 - float(stop_pct)) if stop_pct else None
                        take_px = float(px_raw) * (1.0 + float(take_pct)) if take_pct else None
                    else:
                        stop_px = float(px_raw) * (1.0 + float(stop_pct)) if stop_pct else None
                        take_px = float(px_raw) * (1.0 - float(take_pct)) if take_pct else None
                elif (atr_mult_stop or atr_mult_take) and (next_open_lookup is not None):
                    atr = next_open_lookup.atr_at(str(row["symbol"]), str(row["timeframe"]), ts_used, atr_period,
                                                  atr_method)
                    if atr is not None and not np.isnan(atr):
                        if atr_mult_stop:
                            stop_px = float(px_raw) - float(atr_mult_stop) * float(atr) if side == "LONG" else float(
                                px_raw) + float(atr_mult_stop) * float(atr)
                        if atr_mult_take:
                            take_px = float(px_raw) + float(atr_mult_take) * float(atr) if side == "LONG" else float(
                                px_raw) - float(atr_mult_take) * float(atr)

                entry_qty = _position_size_for_risk(equity, float(px_raw), stop_px, risk_pct)
                px_entry = _exec_price_with_slippage("FLAT", side, float(px_raw), slip_bps, is_entry=True)
                fee_entry = _trade_fee(fee_bps, px_entry, entry_qty)
                equity -= fee_entry

                curr_side = side
                entry_px = float(px_entry)
                entry_ts = _to_utc_ts(ts_used)
                best_px = float(px_entry)
            else:
                # ушли в FLAT
                curr_side = "FLAT"
                entry_px = None
                entry_ts = None
                entry_qty = 0.0
                stop_px = take_px = best_px = None

    return pd.DataFrame(trades, columns=["entry_time", "exit_time", "side", "entry", "exit", "pnl", "bars"])


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────
def _equity_curve(trades: pd.DataFrame, initial_cash: float = 0.0) -> pd.Series:
    """Equity = initial_cash + cumulative PnL по времени закрытий сделок.
    Важно: добавляем стартовую точку перед первым выходом, чтобы DD считался от initial_cash.
    """
    if trades.empty:
        # одна точка на таймлайне, чтобы не делить на ноль и корректно печатать
        return pd.Series([float(initial_cash)], index=[pd.Timestamp("1970-01-01T00:00:00Z")])

    exit_ts = pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
    pnl = trades["pnl"].astype(float)

    eq = pnl.cumsum() + float(initial_cash)
    eq.index = exit_ts

    # добавим стартовую точку ровно перед первой сделкой
    first_ts = exit_ts.iloc[0]
    start_ts = first_ts - pd.Timedelta(nanoseconds=1)
    eq = pd.concat([pd.Series([float(initial_cash)], index=[start_ts]), eq])

    return eq


def _print_report(trades: pd.DataFrame, fill_mode: str, initial_cash: float, used_rows: Optional[int] = None):
    rows = int(used_rows if used_rows is not None else len(trades))
    n_trades = len(trades)
    wins = int((trades["pnl"] > 0).sum()) if n_trades else 0
    win_rate = (wins / n_trades * 100.0) if n_trades else 0.0
    net_pnl = float(trades["pnl"].sum()) if n_trades else 0.0

    eq = _equity_curve(trades, initial_cash=initial_cash)
    final_eq = float(eq.iloc[-1]) if len(eq) else float(initial_cash)

    roll_max = eq.cummax()
    dd = eq - roll_max
    max_dd_abs = float(dd.min())  # отрицательное число
    max_dd_pct = (abs(max_dd_abs) / float(initial_cash) * 100.0) if initial_cash else 0.0

    print("\n=== PAPER TRADE REPORT ===")
    print(f"rows:\t\t  {rows}")
    print(f"trades:\t\t  {n_trades}")
    print(f"win rate:\t\t{win_rate:.1f}%")
    print(f"net PnL:\t\t{net_pnl:.6f}")
    print(f"final equity:{final_eq:.6f}")
    print(f"max DD:\t\t  {max_dd_pct:.2f}%   (abs {max_dd_abs:.6f})")
    print(f"fill mode:\t  {fill_mode}\n")

    if not trades.empty:
        out = trades.copy()
        for col in ("entry", "exit", "pnl"):
            out[col] = out[col].astype(float).round(6)
        print("trades:")
        print(out.to_string(index=False))


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tb-paper", description="Paper trade over signals in DB")
    p.add_argument("--db", default=os.getenv("TB_STORE_URL", "sqlite:///data/bot.db"), help="sqlite:///... path")
    p.add_argument("--symbol")
    p.add_argument("--timeframe")
    p.add_argument("--strategy")
    p.add_argument("--run-id", dest="run_id")

    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int)

    p.add_argument("--fee-bps", type=float, default=0.0)
    p.add_argument("--slip-bps", type=float, default=0.0)
    p.add_argument("--initial-cash", type=float, default=0.0)

    p.add_argument("--fill-mode", choices=["signal", "next_open"], default="signal")
    p.add_argument("--entry-lag", type=int, default=0)

    # ATR-based exits / sizing
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--atr-method", choices=["sma", "ema"], default="sma")
    p.add_argument("--atr-mult-stop", type=float)
    p.add_argument("--atr-mult-take", type=float)

    # Fixed pct exits (альтернатива ATR) + trailing
    p.add_argument("--stop-pct", type=float)
    p.add_argument("--take-pct", type=float)
    p.add_argument("--trail-pct", type=float)

    p.add_argument("--risk-pct", type=float)

    p.add_argument("--export-csv", help="Path to save trades CSV")

    return p


def main(argv: Optional[List[str]] = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # 1) Load signals
    df = _read_signals(
        args.db,
        symbol=args.symbol,
        timeframe=args.timeframe,
        strategy=args.strategy,
        run_id=args.run_id,
        start=args.start,
        end=args.end,
        limit=args.limit,
    )

    # rows here == count of signals used (как в твоих логах)
    used_rows = len(df)

    # 2) NextOpenLookup (если нужен)
    lookup: Optional[NextOpenLookup] = None
    if args.fill_mode == "next_open" or args.atr_mult_stop or args.atr_mult_take:
        # чтобы не тянуть все свечи мира — ограничим по тем же фильтрам
        lookup = NextOpenLookup.from_db(
            args.db,
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
        )

    # 3) Simulate
    trades = simulate_trades(
        df,
        fee_bps=args.fee_bps,
        slip_bps=args.slip_bps,
        fill_mode=args.fill_mode,
        entry_lag=int(args.entry_lag or 0),
        next_open_lookup=lookup,
        atr_period=int(args.atr_period or 14),
        atr_method=args.atr_method or "sma",
        atr_mult_stop=args.atr_mult_stop,
        atr_mult_take=args.atr_mult_take,
        stop_pct=args.stop_pct,
        take_pct=args.take_pct,
        trail_pct=args.trail_pct,
        risk_pct=args.risk_pct,
        initial_cash=float(args.initial_cash or 0.0),
    )

    # 4) Report
    _print_report(
        trades,
        fill_mode=args.fill_mode,
        initial_cash=float(args.initial_cash or 0.0),
        used_rows=used_rows,  # <-- теперь печатаем число использованных сигналов
    )

    # 5) Export
    if args.export_csv:
        trades.to_csv(args.export_csv, index=False)
        print(f"Saved CSV: {args.export_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
