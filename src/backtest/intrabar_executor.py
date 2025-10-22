# src/backtest/intrabar_executor.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional, Tuple, List

import numpy as np
import pandas as pd

Side = Literal["LONG", "SHORT", "FLAT"]
FillMode = Literal["signal", "next_open"]
PriorityPolicy = Literal["worst", "HL", "LH"]  # HL = High then Low, LH = Low then High


def _to_utc(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _rma(x: pd.Series, n: int) -> pd.Series:
    """Wilder's RMA (SMMA)."""
    x = x.astype(float)
    out = np.empty_like(x, dtype=float)
    out[:] = np.nan
    if len(x) == 0:
        return pd.Series(out, index=x.index)

    alpha = 1.0 / float(n)
    acc = np.nan
    for i, val in enumerate(x.values):
        if math.isnan(val):
            out[i] = acc
            continue
        if math.isnan(acc):
            window = x.values[max(0, i - n + 1): i + 1]
            if np.isfinite(window).sum() == n:
                acc = np.nanmean(window)
            else:
                acc = val
        else:
            acc = (1 - alpha) * acc + alpha * val
        out[i] = acc
    return pd.Series(out, index=x.index)


def compute_atr(ohlc: pd.DataFrame, length: int = 14) -> pd.Series:
    """ATR (Wilder). Requires ohlc with columns: open, high, low, close."""
    high = ohlc["high"].astype(float)
    low = ohlc["low"].astype(float)
    close = ohlc["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return _rma(tr, length)


@dataclass
class IntrabarExecutorConfig:
    # execution
    fill_mode: FillMode = "signal"
    entry_lag: int = 0

    # costs
    fee_bps: float = 10.0
    slip_bps: float = 0.0
    qty: float = 1.0

    # risk in BPS
    stop_bps: Optional[float] = None
    take_bps: Optional[float] = None
    trail_bps: Optional[float] = None

    # risk in ATR multiples (priority over *_bps)
    stop_n_atr: Optional[float] = None
    take_n_atr: Optional[float] = None
    trail_n_atr: Optional[float] = None
    atr_len: int = 14

    # conflict policy
    priority: PriorityPolicy = "worst"

    # trade management
    cooldown_bars: int = 0  # запрещаем новые входы N базовых баров после выхода
    min_hold_bars: int = 0  # запрещаем закрытие по signal_flip, пока не выдержим N баров
    breakeven_rr: Optional[float] = None  # при достижении RR подтянуть стоп в entry
    trail_activate_rr: Optional[float] = None  # трейл включать только после RR


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: Side
    entry_price: float
    exit_price: float
    pnl: float
    bars: int
    reason: str


EMPTY_TRADES_COLUMNS = ["entry_time", "exit_time", "side", "entry", "exit", "pnl", "bars", "reason"]


def _bps_to_mult(bps: float) -> float:
    return bps / 10_000.0


def _apply_slip(price: float, slip_bps: float, is_buy: bool) -> float:
    s = _bps_to_mult(slip_bps)
    return price * (1 + s if is_buy else 1 - s)


def _fee(notional: float, fee_bps: float) -> float:
    return abs(notional) * _bps_to_mult(fee_bps)


def _bar_hit_levels_for_long(high: float, low: float, stop: Optional[float], take: Optional[float],
                             policy: PriorityPolicy) -> Optional[Tuple[str, float]]:
    hit_stop = stop is not None and low <= stop
    hit_take = take is not None and high >= take
    if not hit_stop and not hit_take:
        return None
    if hit_stop and hit_take:
        if policy == "worst":
            return "stop", stop
        elif policy == "HL":
            return ("take", take)
        else:  # 'LH'
            return ("stop", stop)
    return ("stop", stop) if hit_stop else ("take", take)


def _bar_hit_levels_for_short(high: float, low: float, stop: Optional[float], take: Optional[float],
                              policy: PriorityPolicy) -> Optional[Tuple[str, float]]:
    hit_stop = stop is not None and high >= stop
    hit_take = take is not None and low <= take
    if not hit_stop and not hit_take:
        return None
    if hit_stop and hit_take:
        if policy == "worst":
            return "stop", stop
        elif policy == "HL":
            return ("stop", stop)
        else:  # 'LH'
            return ("take", take)
    return ("stop", stop) if hit_stop else ("take", take)


def _make_levels(side: Side, entry: float, atr_val: Optional[float],
                 cfg: IntrabarExecutorConfig) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    stop = take = None
    trail_dist = None

    if cfg.stop_n_atr is not None:
        if atr_val is None or not np.isfinite(atr_val):
            raise ValueError("ATR is required for stop_n_atr but atr_val is NaN.")
        dist = cfg.stop_n_atr * atr_val
        stop = entry - dist if side == "LONG" else entry + dist
    elif cfg.stop_bps is not None:
        p = entry * _bps_to_mult(cfg.stop_bps)
        stop = entry - p if side == "LONG" else entry + p

    if cfg.take_n_atr is not None:
        if atr_val is None or not np.isfinite(atr_val):
            raise ValueError("ATR is required for take_n_atr but atr_val is NaN.")
        dist = cfg.take_n_atr * atr_val
        take = entry + dist if side == "LONG" else entry - dist
    elif cfg.take_bps is not None:
        p = entry * _bps_to_mult(cfg.take_bps)
        take = entry + p if side == "LONG" else entry - p

    if cfg.trail_n_atr is not None:
        if atr_val is None or not np.isfinite(atr_val):
            raise ValueError("ATR is required for trail_n_atr but atr_val is NaN.")
        trail_dist = cfg.trail_n_atr * atr_val
    elif cfg.trail_bps is not None:
        trail_dist = entry * _bps_to_mult(cfg.trail_bps)

    return stop, take, trail_dist


def simulate_trades_intrabar(
        ohlc_base: pd.DataFrame,
        signals: pd.DataFrame,
        cfg: IntrabarExecutorConfig,
        base_time_col: str = "time",
        signal_time_col: str = "time",
        price_col: str = "price",
) -> pd.DataFrame:
    # нормализуем
    ohlc = ohlc_base.copy()
    ohlc[base_time_col] = pd.to_datetime(ohlc[base_time_col], utc=True)
    ohlc = ohlc.sort_values(base_time_col).reset_index(drop=True)

    sig = signals.copy()
    sig[signal_time_col] = pd.to_datetime(sig[signal_time_col], utc=True)
    sig = sig.sort_values(signal_time_col).reset_index(drop=True)

    if not {"open", "high", "low", "close"}.issubset(ohlc.columns):
        return pd.DataFrame(columns=EMPTY_TRADES_COLUMNS)
    if sig.empty or not {"side", price_col}.issubset(sig.columns):
        return pd.DataFrame(columns=EMPTY_TRADES_COLUMNS)

    # ATR
    atr = None
    if any(v is not None for v in (cfg.stop_n_atr, cfg.take_n_atr, cfg.trail_n_atr)):
        atr = compute_atr(ohlc, cfg.atr_len).rename("atr")

    # быстрый индекс времени (tz-aware)
    base_dtindex = pd.DatetimeIndex(ohlc[base_time_col])

    def loc_base_index_at_or_after(t: pd.Timestamp) -> int:
        i = int(base_dtindex.searchsorted(t, side="left"))
        if i < 0:
            i = 0
        if i > len(ohlc):
            i = len(ohlc)
        return i

    trades: List[Trade] = []
    pos_side: Side = "FLAT"
    entry_px = np.nan
    entry_idx = -1
    entry_time = None
    trail_stop: Optional[float] = None
    high_mark = -np.inf
    low_mark = np.inf

    last_exit_idx: Optional[int] = None  # для cooldown
    allow_trail: bool = True  # включится позже, если задан trail_activate_rr
    risk_dist: Optional[float] = None  # дистанция до стартового стопа (для RR-триггеров)
    be_active: bool = False  # стоп подтянут в безубыток?

    for i in range(len(sig)):
        t_sig = sig.at[i, signal_time_col]
        desired_side: Side = sig.at[i, "side"]
        sig_price: float = float(sig.at[i, price_col])

        base_i = loc_base_index_at_or_after(t_sig)
        if base_i >= len(ohlc):
            break

        # COOLDOWN
        if pos_side == "FLAT" and desired_side in ("LONG", "SHORT"):
            if last_exit_idx is not None and cfg.cooldown_bars > 0:
                if base_i < last_exit_idx + cfg.cooldown_bars:
                    desired_side = "FLAT"

        # вход
        if cfg.fill_mode == "signal":
            entry_candidate_px = sig_price
            entry_base_i = base_i + max(0, cfg.entry_lag)
            if entry_base_i >= len(ohlc):
                break
        else:
            entry_base_i = base_i + 1 + max(0, cfg.entry_lag)
            if entry_base_i >= len(ohlc):
                break
            entry_candidate_px = float(ohlc.at[entry_base_i, "open"])

        if pos_side == "FLAT" and desired_side in ("LONG", "SHORT"):
            is_buy = desired_side == "LONG"
            px = _apply_slip(entry_candidate_px, cfg.slip_bps, is_buy=is_buy)
            pos_side = desired_side
            entry_px = px
            entry_idx = entry_base_i
            entry_time = ohlc.at[entry_idx, base_time_col]
            trail_stop = None
            high_mark = entry_px
            low_mark = entry_px
            allow_trail = cfg.trail_activate_rr is None
            risk_dist = None
            be_active = False

        next_t = sig.at[i + 1, signal_time_col] if i + 1 < len(sig) else None
        end_base = len(ohlc) if next_t is None else loc_base_index_at_or_after(next_t)

        if pos_side in ("LONG", "SHORT") and entry_idx >= 0:
            atr_val = float(atr.iat[entry_idx]) if atr is not None else None
            stop_lvl, take_lvl, trail_dist = _make_levels(pos_side, entry_px, atr_val, cfg)

            # стартовая дистанция риска
            if risk_dist is None:
                if stop_lvl is not None:
                    risk_dist = abs(entry_px - stop_lvl)

            exit_px = None
            exit_reason = ""
            exit_i = None

            scan_start = max(entry_idx + 1, base_i)
            for j in range(scan_start, end_base):
                hi = float(ohlc.at[j, "high"])
                lo = float(ohlc.at[j, "low"])

                # RR-триггеры
                if risk_dist and risk_dist > 0:
                    if pos_side == "LONG":
                        fmove = max(0.0, hi - entry_px)
                    else:
                        fmove = max(0.0, entry_px - lo)
                    rr = fmove / risk_dist if risk_dist > 0 else 0.0

                    if (cfg.trail_activate_rr is not None) and (not allow_trail) and rr >= cfg.trail_activate_rr:
                        allow_trail = True

                    if cfg.breakeven_rr is not None and rr >= cfg.breakeven_rr:
                        if pos_side == "LONG":
                            stop_lvl = max(stop_lvl or -np.inf, entry_px)
                        else:
                            stop_lvl = min(stop_lvl or np.inf, entry_px)
                        be_active = True

                # трейлинг
                if allow_trail and trail_dist is not None:
                    if pos_side == "LONG":
                        if hi > high_mark:
                            high_mark = hi
                        trail_stop = max((trail_stop or (entry_px - trail_dist)), high_mark - trail_dist)
                    else:
                        if lo < low_mark:
                            low_mark = lo
                        trail_stop = min((trail_stop or (entry_px + trail_dist)), low_mark + trail_dist)

                # проверка уровней
                if pos_side == "LONG":
                    stop_eff = min(stop_lvl, trail_stop) if (stop_lvl is not None and trail_stop is not None) else (
                                stop_lvl or trail_stop)
                    hit = _bar_hit_levels_for_long(hi, lo, stop_eff, take_lvl, cfg.priority)
                    if hit is not None:
                        kind, level = hit
                        px = _apply_slip(level, cfg.slip_bps, is_buy=False)
                        exit_px = px
                        exit_reason = "breakeven" if (kind == "stop" and be_active and level >= entry_px) else (
                            "stop" if kind == "stop" else "take")
                        exit_i = j
                        break
                else:
                    stop_eff = max(stop_lvl, trail_stop) if (stop_lvl is not None and trail_stop is not None) else (
                                stop_lvl or trail_stop)
                    hit = _bar_hit_levels_for_short(hi, lo, stop_eff, take_lvl, cfg.priority)
                    if hit is not None:
                        kind, level = hit
                        px = _apply_slip(level, cfg.slip_bps, is_buy=True)
                        exit_px = px
                        exit_reason = "breakeven" if (kind == "stop" and be_active and level <= entry_px) else (
                            "stop" if kind == "stop" else "take")
                        exit_i = j
                        break

            # закрытие по flip (с учётом min_hold_bars)
            if exit_px is None and i + 1 < len(sig):
                next_side = sig.at[i + 1, "side"]
                if next_side != pos_side and next_side != "FLAT":
                    if cfg.min_hold_bars <= (base_i - entry_idx):
                        if cfg.fill_mode == "signal":
                            px_raw = float(sig.at[i + 1, price_col])
                            is_buy = pos_side == "SHORT"
                            exit_px = _apply_slip(px_raw, cfg.slip_bps, is_buy=is_buy)
                            exit_reason = "signal_flip"
                            exit_i = loc_base_index_at_or_after(sig.at[i + 1, signal_time_col])
                        else:
                            i_open = loc_base_index_at_or_after(sig.at[i + 1, signal_time_col]) + 1
                            if i_open >= len(ohlc):
                                i_open = len(ohlc) - 1
                            px_raw = float(ohlc.at[i_open, "open"])
                            is_buy = pos_side == "SHORT"
                            exit_px = _apply_slip(px_raw, cfg.slip_bps, is_buy=is_buy)
                            exit_reason = "signal_flip"
                            exit_i = i_open

            # конец данных
            if exit_px is None and (i + 1 == len(sig)):
                j = len(ohlc) - 1
                px_raw = float(ohlc.at[j, "close"])
                is_buy = pos_side == "SHORT"
                exit_px = _apply_slip(px_raw, cfg.slip_bps, is_buy=is_buy)
                exit_reason = "eod"
                exit_i = j

            # финализация
            if exit_px is not None and exit_i is not None:
                gross = (exit_px - entry_px) * cfg.qty if pos_side == "LONG" else (entry_px - exit_px) * cfg.qty
                fees = _fee(entry_px * cfg.qty, cfg.fee_bps) + _fee(exit_px * cfg.qty, cfg.fee_bps)
                pnl = gross - fees

                trades.append(Trade(
                    entry_time=_to_utc(entry_time),
                    exit_time=_to_utc(ohlc.at[exit_i, base_time_col]),
                    side=pos_side,
                    entry_price=entry_px,
                    exit_price=exit_px,
                    pnl=float(pnl),
                    bars=int(max(0, exit_i - entry_idx)),
                    reason=exit_reason,
                ))

                last_exit_idx = exit_i
                pos_side = "FLAT"
                entry_px = np.nan
                entry_idx = -1
                entry_time = None
                trail_stop = None
                high_mark = -np.inf
                low_mark = np.inf
                allow_trail = True
                risk_dist = None
                be_active = False

    if not trades:
        return pd.DataFrame(columns=EMPTY_TRADES_COLUMNS)

    df = pd.DataFrame([{
        "entry_time": t.entry_time,
        "exit_time": t.exit_time,
        "side": t.side,
        "entry": t.entry_price,
        "exit": t.exit_price,
        "pnl": t.pnl,
        "bars": t.bars,
        "reason": t.reason,
    } for t in trades])
    return df
