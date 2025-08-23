# src/backtest/vectorized_bt.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import re

import math
import os
import time
import json
import requests
import numpy as np
import pandas as pd


# ----------------------------- #
# ---------- Config ----------- #
# ----------------------------- #

@dataclass
class BtConfig:
    # Data
    pair: str                       # e.g. "DOGE_EUR"
    span: str                       # e.g. "1m:2000", "5m:5000", "1h:1500", "D:800"
    resample_rule: Optional[str]    # e.g. "5m", "15m", "1h", None

    # Strategy (SMA crossover + hysteresis)
    fast: int = 6
    slow: int = 25
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    enter_on_start: bool = False

    # Trading frictions
    fee_bps: int = 10
    slip_bps: int = 0

    # Sizing
    qty_eur: float = 50.0

    # Risk
    max_daily_loss_bps: int = 0

    # Outputs
    out_trades_csv: Optional[Path] = None
    out_equity_csv: Optional[Path] = None
    out_metrics_json: Optional[Path] = None

    # Behavior
    print_summary: bool = True


# ----------------------------- #
# --------- Utilities --------- #
# ----------------------------- #

BPS = 1e-4
_SECONDS_IN_YEAR = 365.25 * 24 * 3600


def _parse_span(span: str) -> Tuple[str, int, int]:
    """
    Parse span like "1m:2000", "5m:5000", "1h:1000", "D:800"
    Returns: (resolution_param_for_api, approx_seconds_per_candle, limit)
    """
    try:
        tf, limit_s = span.split(":")
        limit = int(limit_s)
    except Exception:
        raise ValueError(f"Bad span format '{span}'. Expected like '1m:2000' or 'D:800'.")

    tf = tf.strip().lower()
    if tf.endswith("m"):  # minutes
        minutes = int(tf[:-1])
        return str(minutes), minutes * 60, limit
    if tf.endswith("h"):  # hours
        hours = int(tf[:-1])
        return str(hours * 60), hours * 3600, limit
    if tf in ("d", "w", "m"):  # day/week/month (EXMO accepts D/W/M)
        sec_map = {"d": 86400, "w": 7 * 86400, "m": 30 * 86400}
        return tf.upper(), sec_map[tf], limit

    raise ValueError(f"Unsupported timeframe '{tf}' in span '{span}'.")


def _detect_ts_unit(t_raw: Any) -> str:
    t_int = int(float(t_raw))
    if t_int >= 1_000_000_000_000_000:  # 1e15
        return "us"
    if t_int >= 100_000_000_000:        # 1e11
        return "ms"
    return "s"


def _to_utc_ts(t_raw: Any) -> pd.Timestamp:
    t_int = int(float(t_raw))
    unit = _detect_ts_unit(t_int)
    try:
        return pd.to_datetime(t_int, unit=unit, utc=True)
    except Exception:
        for unit_fallback in ("us", "ms", "s"):
            try:
                return pd.to_datetime(t_int, unit=unit_fallback, utc=True)
            except Exception:
                continue
        return pd.to_datetime(t_int // 1000, unit="s", utc=True)


def _request_exmo(symbol: str, resolution: str, ts_from: int, ts_to: int) -> List[tuple]:
    """Один запрос к EXMO. Возвращает список строк (ts,o,h,l,c,v)."""
    params = {"symbol": symbol, "resolution": resolution, "from": ts_from, "to": ts_to}
    urls = [
        "https://api.exmo.com/v1.1/candles_history",
        # запасной (иногда CDN/маршрутизация чудит; пусть будет в цикле)
        "https://api.exmo.com/v1/candles_history",
    ]
    last_exc: Exception | None = None
    for u in urls:
        try:
            if os.getenv("EXMO_DEBUG"):
                print(f"[EXMO] → GET {u} params={params}")
            r = requests.get(u, params=params, timeout=30)
            r.raise_for_status()
            j = r.json()
            candles = j.get("candles")
            if not isinstance(candles, list):
                continue
            rows = []
            for c in candles:
                t_raw = c.get("t", c.get("time", c.get("ts")))
                o = c.get("o"); h = c.get("h"); l = c.get("l"); cc = c.get("c"); v = c.get("v")
                if None in (t_raw, o, h, l, cc, v):
                    continue
                ts = _to_utc_ts(t_raw)
                rows.append((ts, float(o), float(h), float(l), float(cc), float(v)))
            return rows
        except Exception as e:
            last_exc = e
            continue
    if last_exc and os.getenv("EXMO_DEBUG"):
        print(f"[EXMO] last error: {last_exc}")
    return []


def _fetch_exmo_candles(pair: str, span: str) -> pd.DataFrame:
    """
    Downloads candles from EXMO public REST.
    Returns DataFrame with columns: ['open','high','low','close','volume'] and UTC DatetimeIndex.
    Делает один большой запрос; если пусто/мало — догружает чанками.
    """
    resolution, sec_per_bar, limit = _parse_span(span)
    now = int(time.time())
    target_secs = sec_per_bar * (limit + 5)
    start = now - target_secs

    # 1) пробуем одним куском
    rows = _request_exmo(pair, resolution, start, now)

    # 2) если пусто или подозрительно мало — чанкование
    if len(rows) < int(limit * 0.8):
        acc: List[tuple] = []
        to_ts = now
        # bars в одном запросе (без фанатизма, чтобы не упереться в лимиты)
        per_req_bars = max(800, min(2000, limit))  # 800..2000
        window = sec_per_bar * (per_req_bars + 5)

        hard_start = now - sec_per_bar * (limit * 2 + 500)  # не лезем слишком далеко
        attempts = 0

        while to_ts > start and to_ts > hard_start and len(acc) < limit + 1000:
            frm = max(start, to_ts - window)
            chunk = _request_exmo(pair, resolution, frm, to_ts)
            acc.extend(chunk)
            to_ts = frm - 1
            attempts += 1
            if os.getenv("EXMO_DEBUG"):
                print(f"[EXMO] chunk #{attempts}: got={len(chunk)}, acc={len(acc)}")

        rows = acc if acc else rows

    if not rows:
        raise RuntimeError(f"Empty candles from EXMO for {pair} span={span}")

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.sort_values("ts").drop_duplicates(subset=["ts"]).set_index("ts")

    # берём последние 'limit' баров (самые свежие)
    if len(df) > limit:
        df = df.iloc[-limit:]

    if os.getenv("EXMO_DEBUG"):
        print(f"[EXMO] parsed={len(df)}; head={df.index[:2].tolist()} tail={df.index[-2:].tolist()}")
    return df


# ---------- resample helpers ---------- #

_RESAMPLE_RE = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$", flags=re.IGNORECASE)

def _normalize_resample_rule(rule: str) -> str:
    """
    '5m' → '5min', '15m' → '15min'; '1h' → '1H'; '1d' → '1D'; '1w' → '1W'
    """
    m = _RESAMPLE_RE.match(rule)
    if not m:
        return rule
    n, unit = m.groups()
    unit = unit.lower()
    if unit == "m":
        return f"{n}min"
    mapping = {"h": "H", "d": "D", "w": "W"}
    return f"{n}{mapping[unit]}"


def _rule_to_seconds(rule_norm: str) -> Optional[float]:
    m = re.match(r"^\s*(\d+)\s*(min|H|D|W)\s*$", rule_norm)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    sec_map = {"min": 60, "H": 3600, "D": 86400, "W": 7 * 86400}
    return n * sec_map[unit]


def _resample_ohlcv(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    if not rule:
        return df
    rule_norm = _normalize_resample_rule(rule)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule_norm, label="right", closed="right").agg(agg).dropna()
    return out


def _make_signals_sma_hysteresis(close: pd.Series, fast: int, slow: int, hysteresis_bps: int) -> pd.Series:
    s_fast = close.rolling(fast, min_periods=fast).mean()
    s_slow = close.rolling(slow, min_periods=slow).mean()

    eps = hysteresis_bps * BPS
    upper = s_slow * (1.0 + eps)
    lower = s_slow * (1.0 - eps)

    state = np.zeros(len(close), dtype=np.int8)
    have_state = False
    for i in range(len(close)):
        f = s_fast.iat[i]
        s = s_slow.iat[i]
        if math.isnan(f) or math.isnan(s):
            continue
        if f > upper.iat[i]:
            state[i] = 1; have_state = True
        elif f < lower.iat[i]:
            state[i] = 0; have_state = True
        else:
            state[i] = state[i - 1] if have_state and i > 0 else 0

    trig = np.zeros(len(state), dtype=np.int8)
    prev = 0
    for i, st in enumerate(state):
        if st == 1 and prev == 0:
            trig[i] = 1
        elif st == 0 and prev == 1:
            trig[i] = -1
        prev = st
    return pd.Series(trig, index=close.index, name="trig")


def _max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = -np.inf
    max_dd = 0.0
    for x in equity:
        peak = max(peak, x)
        dd = (x / peak - 1.0) * 100.0
        max_dd = min(max_dd, dd)
    return max_dd


def _infer_bars_per_year(index: pd.DatetimeIndex, rule: Optional[str]) -> float:
    if rule:
        rn = _normalize_resample_rule(rule)
        sec = _rule_to_seconds(rn)
        if sec:
            return _SECONDS_IN_YEAR / sec
    if len(index) >= 3:
        deltas = (index[1:] - index[:-1]).to_series(index=index[1:])
        med = deltas.median().total_seconds()
        if med > 0:
            return _SECONDS_IN_YEAR / med
    return _SECONDS_IN_YEAR / 3600.0


# ----------------------------- #
# ---------- Engine ----------- #
# ----------------------------- #

def run_backtest_vectorized(cfg: BtConfig) -> Dict[str, Any]:
    # 1) Data
    ohlc = _fetch_exmo_candles(cfg.pair, cfg.span)
    if cfg.resample_rule:
        ohlc = _resample_ohlcv(ohlc, cfg.resample_rule)

    if len(ohlc) < max(cfg.fast, cfg.slow) + 5:
        raise RuntimeError("Not enough candles after resample for SMA windows.")

    # 2) Signals
    trig = _make_signals_sma_hysteresis(ohlc["close"], cfg.fast, cfg.slow, cfg.hysteresis_bps)

    # 3) Execution
    idx = ohlc.index.to_list()
    close = ohlc["close"].to_numpy()

    cash_eur = 1000.0
    pos_qty = 0.0
    cooldown_left = 0

    fee_mult = cfg.fee_bps * BPS
    slip_mult = cfg.slip_bps * BPS

    eq = np.zeros(len(close), dtype=np.float64)
    eq_day_start = cash_eur

    entry_cost_eur = 0.0
    closed_pnls: List[float] = []
    trades: List[Dict[str, Any]] = []
    in_pos_bars = 0

    last_day = None

    for i in range(len(close)):
        px = float(close[i])
        ts = idx[i]

        day = ts.date()
        if last_day is None:
            last_day = day
            eq_day_start = cash_eur + pos_qty * px
        elif day != last_day:
            eq_day_start = cash_eur + pos_qty * px
            last_day = day

        eq_i = cash_eur + pos_qty * px
        eq[i] = eq_i

        daily_bps = ((eq_i - eq_day_start) / max(1e-12, eq_day_start)) * 1e4

        if cooldown_left > 0 and pos_qty == 0.0:
            cooldown_left -= 1

        do_entry = trig.iat[i] == 1
        do_exit  = trig.iat[i] == -1

        if do_entry:
            if cooldown_left > 0:
                do_entry = False
            if cfg.max_daily_loss_bps and daily_bps <= -abs(float(cfg.max_daily_loss_bps)):
                do_entry = False
            if not cfg.enter_on_start and i < max(cfg.fast, cfg.slow):
                do_entry = False

        if do_entry and pos_qty <= 1e-12:
            buy_px = px * (1.0 + slip_mult)
            qty = cfg.qty_eur / max(1e-12, buy_px)
            notional = qty * buy_px
            fee_eur = notional * fee_mult

            cash_eur -= (notional + fee_eur)
            pos_qty += qty
            entry_cost_eur = notional + fee_eur

            trades.append({
                "time": ts.isoformat(), "side": "BUY", "price": round(buy_px, 10),
                "qty": round(qty, 10), "fee_eur": round(fee_eur, 10),
                "cash_eur": round(cash_eur, 10), "pos_qty": round(pos_qty, 10),
                "equity_eur": round(eq_i, 10), "pnl_eur": 0.0,
            })

        elif do_exit and pos_qty > 1e-12:
            sell_px = px * (1.0 - slip_mult)
            notional = pos_qty * sell_px
            fee_eur = notional * fee_mult

            cash_eur += (notional - fee_eur)
            closed = (notional - fee_eur) - entry_cost_eur
            closed_pnls.append(closed)

            trades.append({
                "time": ts.isoformat(), "side": "SELL", "price": round(sell_px, 10),
                "qty": round(pos_qty, 10), "fee_eur": round(fee_eur, 10),
                "cash_eur": round(cash_eur, 10), "pos_qty": 0.0,
                "equity_eur": round(cash_eur, 10), "pnl_eur": round(closed, 10),
            })

            pos_qty = 0.0
            entry_cost_eur = 0.0
            cooldown_left = max(cooldown_left, cfg.cooldown_bars)

        if pos_qty > 0:
            in_pos_bars += 1

    # 4) Results
    eq0 = eq[0] if len(eq) > 0 else 1.0
    eqN = eq[-1] if len(eq) > 0 else eq0
    total_return_pct = (eqN / max(1e-12, eq0) - 1.0) * 100.0
    max_dd_pct = _max_drawdown(eq)

    wins = sum(1 for x in closed_pnls if x > 0)
    losses = sum(1 for x in closed_pnls if x <= 0)
    winrate = (wins / max(1, wins + losses)) * 100.0
    profit_sum = float(sum(x for x in closed_pnls if x > 0))
    loss_sum = float(sum(-x for x in closed_pnls if x < 0))
    profit_factor = (profit_sum / loss_sum) if loss_sum > 0 else float("inf")
    avg_trade_eur = (profit_sum - loss_sum) / max(1, (wins + losses))

    eq_series = pd.Series(eq, index=ohlc.index, name="equity_eur")
    rolling_peak = eq_series.cummax()
    dd_pct_series = (eq_series / rolling_peak - 1.0) * 100.0
    equity_df = pd.DataFrame({"equity_eur": eq_series, "drawdown_pct": dd_pct_series})

    bars_per_year = _infer_bars_per_year(ohlc.index, cfg.resample_rule)
    rets = eq_series.pct_change().fillna(0.0).to_numpy()
    ret_mean = float(np.mean(rets))
    ret_std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (ret_mean / ret_std * math.sqrt(bars_per_year)) if ret_std > 0 else 0.0

    if len(ohlc.index) >= 2:
        days = (ohlc.index[-1] - ohlc.index[0]).total_seconds() / 86400.0
        years = max(1e-9, days / 365.25)
        cagr = (eqN / max(1e-12, eq0)) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0
    calmar = (cagr / abs(max_dd_pct / 100.0)) if abs(max_dd_pct) > 1e-12 else float("inf")

    exposure_pct = in_pos_bars / max(1, len(eq)) * 100.0

    trades_df = pd.DataFrame(trades, columns=[
        "time", "side", "price", "qty", "fee_eur",
        "cash_eur", "pos_qty", "equity_eur", "pnl_eur"
    ])

    if cfg.out_trades_csv:
        Path(cfg.out_trades_csv).parent.mkdir(parents=True, exist_ok=True)
        trades_df.to_csv(cfg.out_trades_csv, index=False)

    if cfg.out_equity_csv:
        Path(cfg.out_equity_csv).parent.mkdir(parents=True, exist_ok=True)
        equity_df.to_csv(cfg.out_equity_csv)

    metrics = {
        "pair": cfg.pair,
        "bars": int(len(ohlc)),
        "trades": int(len([t for t in trades if t["side"] == "SELL"])),
        "winrate_pct": winrate,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_dd_pct,
        "final_equity_eur": float(eqN),
        "start_equity_eur": float(eq0),
        "profit_factor": profit_factor,
        "avg_trade_eur": avg_trade_eur,
        "exposure_pct": exposure_pct,
        "sharpe": sharpe,
        "cagr_pct": cagr * 100.0,
        "calmar": calmar,
        "bars_per_year": bars_per_year,
    }

    pretty = {
        "pair": cfg.pair,
        "bars": metrics["bars"],
        "trades": metrics["trades"],
        "winrate_pct": round(metrics["winrate_pct"], 2),
        "total_return_pct": round(metrics["total_return_pct"], 2),
        "max_drawdown_pct": round(metrics["max_drawdown_pct"], 2),
        "final_equity_eur": round(metrics["final_equity_eur"], 2),
        "start_equity_eur": round(metrics["start_equity_eur"], 2),
        "profit_factor": (None if math.isinf(metrics["profit_factor"]) else round(metrics["profit_factor"], 3)),
        "avg_trade_eur": round(metrics["avg_trade_eur"], 4),
        "exposure_pct": round(metrics["exposure_pct"], 2),
        "sharpe": round(metrics["sharpe"], 3),
        "cagr_pct": round(metrics["cagr_pct"], 2),
        "calmar": (None if math.isinf(metrics["calmar"]) else round(metrics["calmar"], 3)),
        "trades_csv": str(cfg.out_trades_csv) if cfg.out_trades_csv else None,
        "equity_csv": str(cfg.out_equity_csv) if cfg.out_equity_csv else None,
    }
    if cfg.print_summary:
        print(json.dumps(pretty, ensure_ascii=False, indent=2))

    if cfg.out_metrics_json:
        Path(cfg.out_metrics_json).parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.out_metrics_json, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)

    return {"metrics": metrics, "trades_df": trades_df, "equity_df": equity_df}
