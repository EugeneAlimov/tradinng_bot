# src/domain/strategy/ema_adx_atr.py
from __future__ import annotations

from typing import Literal, Tuple, Optional

import numpy as np
import pandas as pd

Side = Literal["LONG", "SHORT", "FLAT"]


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _rma(x: pd.Series, n: int) -> pd.Series:
    # Wilder's RMA (SMMA)
    alpha = 1.0 / float(n)
    return x.ewm(alpha=alpha, adjust=False).mean()


def _adx_dm_di(ohlc: pd.DataFrame, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    high = ohlc["high"].astype(float)
    low = ohlc["low"].astype(float)
    close = ohlc["close"].astype(float)

    up = high.diff()
    down = (-low.diff())

    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = _rma(tr, length)
    plus_di = 100.0 * _rma(pd.Series(plus_dm, index=ohlc.index), length) / atr
    minus_di = 100.0 * _rma(pd.Series(minus_dm, index=ohlc.index), length) / atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = _rma(dx, length)
    return adx, plus_di, minus_di


def resample_ohlc(ohlc_base: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    df = ohlc_base.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").set_index("time")

    o = df["open"].resample(timeframe).first()
    h = df["high"].resample(timeframe).max()
    l = df["low"].resample(timeframe).min()
    c = df["close"].resample(timeframe).last()
    if "volume" in df.columns:
        v = df["volume"].resample(timeframe).sum()
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    else:
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
    out = out.dropna().reset_index()
    return out


def _merge_asof(left: pd.DataFrame, right: pd.DataFrame, left_on: str, right_on: str, cols: list[str]) -> pd.DataFrame:
    r = right[[right_on] + cols].sort_values(right_on).rename(columns={right_on: "__rt"})
    l = left.sort_values(left_on).rename(columns={left_on: "__lt"})
    merged = pd.merge_asof(l, r, left_on="__lt", right_on="__rt", direction="backward")
    merged = merged.drop(columns=["__rt"]).rename(columns={"__lt": left_on})
    return merged


def generate_signals_ema_adx_atr(
        ohlc_base: pd.DataFrame,
        resample_tf: str = "5min",
        ema_fast: int = 12,
        ema_slow: int = 21,
        adx_len: int = 14,
        adx_on: float = 25.0,
        adx_off: float = 18.0,
        require_di: bool = True,
        # NEW: HTF filter
        htf_tf: Optional[str] = None,  # например "15min" или "1H"
        htf_ema_fast: int = 48,
        htf_ema_slow: int = 96,
) -> pd.DataFrame:
    """
    EMA/ADX сигналы на сигнальном ТФ (+ опциональный HTF-фильтр тренда).
    Возвращает DataFrame: ['time','side','price'] где price = close сигнального бара.
    """
    sig_ohlc = resample_ohlc(ohlc_base, resample_tf)
    sig_ohlc = sig_ohlc.copy()
    sig_ohlc["ema_fast"] = _ema(sig_ohlc["close"], ema_fast)
    sig_ohlc["ema_slow"] = _ema(sig_ohlc["close"], ema_slow)

    adx, di_plus, di_minus = _adx_dm_di(sig_ohlc, adx_len)
    sig_ohlc["adx"] = adx
    sig_ohlc["+di"] = di_plus
    sig_ohlc["-di"] = di_minus

    # базовые стороны без HTF
    sides = []
    last_side: Side = "FLAT"
    for i in range(len(sig_ohlc)):
        row = sig_ohlc.iloc[i]
        adx_v = row["adx"]
        fast = row["ema_fast"]
        slow = row["ema_slow"]
        di_p = row["+di"]
        di_m = row["-di"]

        side: Side = last_side
        if np.isfinite(adx_v) and adx_v <= adx_off:
            side = "FLAT"
        elif np.isfinite(adx_v) and adx_v >= adx_on:
            want_long = fast > slow and (not require_di or (di_p > di_m))
            want_short = fast < slow and (not require_di or (di_m > di_p))
            if want_long and not want_short:
                side = "LONG"
            elif want_short and not want_long:
                side = "SHORT"
            else:
                side = "FLAT"
        # в зоне гистерезиса держим прежний side
        sides.append(side)
        last_side = side

    out = sig_ohlc[["time", "close"]].copy()
    out["side"] = sides
    out.rename(columns={"close": "price"}, inplace=True)

    # HTF-фильтр: пропускаем только сделки в сторону тренда старшего ТФ
    if htf_tf:
        htf = resample_ohlc(ohlc_base, htf_tf)
        htf = htf.copy()
        htf["ema_f"] = _ema(htf["close"], htf_ema_fast)
        htf["ema_s"] = _ema(htf["close"], htf_ema_slow)
        htf_side = np.where(htf["ema_f"] > htf["ema_s"], "LONG", np.where(htf["ema_f"] < htf["ema_s"], "SHORT", "FLAT"))
        htf = htf[["time"]].copy().assign(htf_side=htf_side)

        out = _merge_asof(out, htf, "time", "time", ["htf_side"])
        # где нет данных HTF — считаем FLAT (без сделок)
        out["htf_side"] = out["htf_side"].fillna("FLAT")

        def _gate(row) -> str:
            s = row["side"]
            hs = row["htf_side"]
            if s == "LONG" and hs != "LONG":
                return "FLAT"
            if s == "SHORT" and hs != "SHORT":
                return "FLAT"
            return s

        out["side"] = out.apply(_gate, axis=1)
        out = out.drop(columns=["htf_side"])

    return out
