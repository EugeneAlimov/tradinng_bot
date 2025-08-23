# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd

from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv


@dataclass
class BtConfig:
    pair: str
    span: str                 # пример: "1m:2000"
    resample_rule: str        # пример: "5m" или "" (без ресемпла)
    fast: int
    slow: int
    hysteresis_bps: float = 0.0
    start_eur: float = 1_000.0
    qty_eur: float = 0.0          # фикс. EUR на сделку; 0 -> использовать position_pct
    position_pct: float = 100.0   # % от equity (если qty_eur == 0)
    fee_bps: float = 10.0
    slip_bps: float = 2.0
    cooldown_bars: int = 0
    max_daily_loss_bps: float = 0.0
    enter_on_start: bool = False

    out_dir: Path = Path("data")
    out_trades_csv: Path = Path("data/backtest_trades.csv")
    out_equity_csv: Path = Path("data/backtest_equity.csv")


@dataclass
class BtResult:
    metrics: Dict[str, Any]
    trades: pd.DataFrame
    equity: pd.DataFrame


# ---------- utils ----------

def _to_df(candles: Any) -> pd.DataFrame:
    """Normalize to DataFrame with columns: time, open, high, low, close, volume."""
    if candles is None:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    if isinstance(candles, pd.DataFrame):
        df = candles.copy()
        lower = {c: str(c).lower() for c in df.columns}
        inv = {v: k for k, v in lower.items()}
        need = ["time", "open", "high", "low", "close", "volume"]
        mapping = {}
        for want in need:
            if want in lower.values():
                mapping[inv[want]] = want
        df = df.rename(columns=mapping)
        if "volume" not in df.columns:
            df["volume"] = 0.0
        for c in ["time", "open", "high", "low", "close", "volume"]:
            if c not in df.columns:
                df[c] = np.nan
        return df[["time", "open", "high", "low", "close", "volume"]].copy()

    rows = []
    for r in candles:
        if not isinstance(r, (list, tuple)) or len(r) < 5:
            continue
        if len(r) >= 6:
            t, o, h, l, c, v = r[:6]
        else:
            t, o, h, l, c = r[:5]
            v = 0.0
        rows.append([t, o, h, l, c, v])
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])


def _ensure_paths(cfg: BtConfig) -> None:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.out_trades_csv.parent.mkdir(parents=True, exist_ok=True)
    cfg.out_equity_csv.parent.mkdir(parents=True, exist_ok=True)


def _ensure_time_column(df: pd.DataFrame) -> pd.DataFrame:
    """Снимаем двусмысленность: индекс/колонка time, переносим индекс в 'time' при необходимости."""
    df = df.copy()
    if "time" in df.columns:
        if df.index.name == "time":
            df.index = df.index.rename(None)
        return df
    if isinstance(df.index, pd.DatetimeIndex):
        name = df.index.name or "time"
        df = df.reset_index().rename(columns={name: "time"})
        return df
    if df.index.name:
        name = df.index.name
        df = df.reset_index().rename(columns={name: "time"})
        return df
    raise RuntimeError("No 'time' column and unnamed index; cannot normalize time.")


def _parse_span(span: str) -> Tuple[str, int]:
    """
    '1m:2000' -> ('1m', 2000). Если нет количества, вернём 0.
    """
    if ":" in span:
        b, n = span.split(":", 1)
        try:
            return b, int(n)
        except Exception:
            return b, 0
    return span, 0


def _resample_factor(base: str, rule: str) -> int:
    """
    Грубая оценка коэффициента сжатия рядов при ресемпле:
    '1m' -> 1, '5m' -> 5, '15m' -> 15, '1h' -> 60, '4h' -> 240 и т.п.
    Если не удаётся — вернём 1.
    """
    def to_minutes(x: str) -> int:
        x = x.strip().lower()
        if x.endswith("m"):
            return int(x[:-1])
        if x.endswith("h"):
            return int(x[:-1]) * 60
        if x.endswith("d"):
            return int(x[:-1]) * 60 * 24
        return 1

    try:
        bmin = to_minutes(base)
        rmin = to_minutes(rule)
        if bmin > 0 and rmin >= bmin:
            return max(1, rmin // bmin)
        return 1
    except Exception:
        return 1


def _slip_price(px: np.ndarray, slip_bps: float, side: str) -> np.ndarray:
    k = float(slip_bps) / 1e4
    return px * (1.0 + k) if side == "buy" else px * (1.0 - k)


# ---------- main ----------

def run_backtest_vectorized(cfg: BtConfig) -> BtResult:
    _ensure_paths(cfg)

    base_tf, req_n = _parse_span(cfg.span)
    need_bars = max(cfg.fast, cfg.slow) + 30  # небольшой запас поверх окон
    factor = _resample_factor(base_tf, cfg.resample_rule) if cfg.resample_rule else 1

    def _load_span(span: str) -> pd.DataFrame:
        candles = fetch_exmo_candles(cfg.pair, span)
        if cfg.resample_rule:
            candles = resample_ohlcv(candles, cfg.resample_rule)
        df0 = _to_df(candles)
        df0 = _ensure_time_column(df0)
        # timestamps
        if pd.api.types.is_numeric_dtype(df0["time"]):
            df0["time"] = pd.to_datetime(df0["time"], utc=True, unit="ms", errors="coerce")
        else:
            df0["time"] = pd.to_datetime(df0["time"], utc=True, errors="coerce")
        df0 = df0.dropna(subset=["time", "close"]).sort_values("time").reset_index(drop=True)
        return df0

    # 1) первая попытка
    df = _load_span(cfg.span)

    # 2) если баров недостаточно — увеличим окно и перезагрузим один раз
    if len(df) < need_bars:
        # если изначально было '1m:2000' — умножим количество
        if req_n > 0:
            # сколько 1m нужно для need_bars после ресемпла? грубо: need_bars * factor
            wanted_src = max(req_n * 3, need_bars * factor * 3)  # тройной запас
            span2 = f"{base_tf}:{wanted_src}"
        else:
            # без количества — подставим дефолт
            span2 = f"{base_tf}:{need_bars * factor * 3}"
        print(f"[bt-v] not enough bars ({len(df)}<{need_bars}), reloading with span={span2}")
        df = _load_span(span2)

    if len(df) < need_bars:
        raise RuntimeError(f"Not enough data after resample: have={len(df)} need>={need_bars}. "
                           f"Try larger --exmo-candles or smaller --resample.")

    # 3) Индики
    f, s = cfg.fast, cfg.slow
    if f <= 0 or s <= 0 or f == s:
        raise ValueError("fast/slow must be positive and different.")
    df["sma_fast"] = df["close"].rolling(f, min_periods=f).mean()
    df["sma_slow"] = df["close"].rolling(s, min_periods=s).mean()

    # 4) Сигналы (кроссы на баре t, исполнение на t+1)
    pf = df["sma_fast"].shift(1)
    ps = df["sma_slow"].shift(1)
    f0 = df["sma_fast"]
    s0 = df["sma_slow"]

    cross_up = (pf <= ps) & (f0 > s0)
    cross_dn = (pf >= ps) & (f0 < s0)
    signal = np.where(cross_up, 1, np.where(cross_dn, -1, 0))

    if cfg.hysteresis_bps and cfg.hysteresis_bps > 0:
        strength_bps = (np.abs(f0 - s0) / np.maximum(1e-12, df["close"])) * 1e4
        signal = np.where(strength_bps < float(cfg.hysteresis_bps), 0, signal)

    # 5) Stateful walk (vector-ish)
    n = len(df)
    time_vals = df["time"].values
    close = df["close"].values.astype(float)

    trig = np.roll(signal, 1)
    trig[0] = 0
    trig[-1] = 0

    pos = np.zeros(n, dtype=float)
    cash = np.zeros(n, dtype=float)
    eq = np.zeros(n, dtype=float)
    cash[0] = float(cfg.start_eur)
    pos_qty = 0.0
    cash_eur = float(cfg.start_eur)

    cooldown = 0
    daily_date = pd.Timestamp(time_vals[0]).date().isoformat()
    eq_day_start = float(cfg.start_eur)
    daily_bps = 0.0
    max_dd = 0.0
    peak = float(cfg.start_eur)

    fills: List[Tuple[str, str, float, float, float]] = []  # (time, side, price, qty, fee_eur)
    fee_mul = float(cfg.fee_bps) / 1e4

    for i in range(1, n):
        ts = pd.Timestamp(time_vals[i])
        px = float(close[i])

        # daily rollover
        today = ts.date().isoformat()
        if today != daily_date:
            daily_date = today
            eq_day_start = cash_eur + pos_qty * px
            daily_bps = 0.0

        # cooldown tick
        if cooldown > 0:
            cooldown -= 1

        # equity & drawdown
        eq_i = cash_eur + pos_qty * px
        eq[i] = eq_i
        if eq_i > peak:
            peak = eq_i
        dd = (peak - eq_i) / max(1e-12, peak)
        if dd > max_dd:
            max_dd = dd

        do_entry = (trig[i] == 1)
        do_exit = (trig[i] == -1)

        # entry blocks
        if do_entry:
            if cooldown > 0:
                do_entry = False
            if cfg.max_daily_loss_bps and cfg.max_daily_loss_bps > 0:
                if daily_bps <= -abs(float(cfg.max_daily_loss_bps)):
                    do_entry = False

        # buy
        if do_entry:
            use_eur = cfg.qty_eur if cfg.qty_eur > 0 else (eq_i * max(0.0, float(cfg.position_pct)) / 100.0)
            if use_eur > 0:
                buy_px = _slip_price(np.array([px]), cfg.slip_bps, "buy")[0]
                qty = use_eur / max(1e-12, buy_px)
                fee_eur = buy_px * qty * fee_mul
                if cash_eur >= (buy_px * qty + fee_eur):
                    cash_eur -= (buy_px * qty + fee_eur)
                    pos_qty += qty
                    fills.append((ts.isoformat(), "buy", float(buy_px), float(qty), float(fee_eur)))
                    cooldown = max(cooldown, int(cfg.cooldown_bars))

        # sell (close all)
        elif do_exit and pos_qty > 0:
            sell_px = _slip_price(np.array([px]), cfg.slip_bps, "sell")[0]
            qty = pos_qty
            fee_eur = sell_px * qty * fee_mul
            cash_eur += sell_px * qty - fee_eur
            pos_qty = 0.0
            fills.append((ts.isoformat(), "sell", float(sell_px), float(qty), float(fee_eur)))
            cooldown = max(cooldown, int(cfg.cooldown_bars))

            # daily bps обновляем по изменению эквити относительно начала дня
            eq_after = cash_eur + pos_qty * sell_px
            daily_bps = ((eq_after - eq_day_start) / max(1e-12, eq_day_start)) * 1e4
            if cfg.max_daily_loss_bps and daily_bps <= -abs(float(cfg.max_daily_loss_bps)):
                cooldown = max(cooldown, 999)  # блокируем дальнейшие входы

        pos[i] = pos_qty
        cash[i] = cash_eur
        eq[i] = cash_eur + pos_qty * px

    # ---- results ----
    trades_df = pd.DataFrame(fills, columns=["time", "side", "price", "qty", "fee_eur"])
    equity_df = pd.DataFrame({"time": df["time"], "equity": eq})

    ret = (eq[-1] / max(1e-12, cfg.start_eur)) - 1.0
    rets = pd.Series(eq).pct_change().fillna(0.0)
    sharpe = float((np.mean(rets) / max(1e-12, np.std(rets))) * np.sqrt(252)) if np.std(rets) > 0 else 0.0

    trades_n = len(trades_df)
    wins = 0
    if trades_n >= 2:
        pnl_list = []
        stack: Optional[Tuple[float, float]] = None
        for _, row in trades_df.iterrows():
            if row["side"] == "buy":
                stack = (row["price"], row["qty"])
            elif row["side"] == "sell" and stack is not None:
                buy_px, qty = stack
                sell_px = float(row["price"])
                fee_sum = float(row["fee_eur"])
                pnl = (sell_px - buy_px) * float(qty) - fee_sum
                pnl_list.append(pnl)
                stack = None
        wins = int(sum(1 for x in pnl_list if x >= 0))
    win_rate = (wins / max(1, trades_n // 2)) * 100.0

    metrics = {
        "bars": int(n),
        "trades": int(trades_n),
        "round_trips": int(trades_n // 2),
        "win_rate_pct": float(win_rate),
        "return_pct": float(ret * 100.0),
        "sharpe_like": float(sharpe),
        "max_drawdown_pct": float(((np.max(pd.Series(eq).cummax() - eq)) / max(1e-12, np.max(eq))) * 100.0)
                         if len(eq) > 0 else 0.0,
        "final_equity": float(eq[-1]),
        "start_equity": float(cfg.start_eur),
    }

    trades_df.to_csv(cfg.out_trades_csv, index=False)
    equity_df.to_csv(cfg.out_equity_csv, index=False)

    return BtResult(metrics=metrics, trades=trades_df, equity=equity_df)
