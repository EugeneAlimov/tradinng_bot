# src/presentation/cli/fetch_cmd.py
from __future__ import annotations

import sys
import pandas as pd

from src.backtest.compat import fetch_exmo_candles_cached, resample_ohlc
from src.presentation.cli.trade_live_cmd import _ensure_dt  # переиспользуем


def run(args) -> int:
    pair = getattr(args, "exmo_pair", None)
    span = getattr(args, "exmo_candles", None)
    out = getattr(args, "out", None)
    rule = getattr(args, "resample", None)

    if not pair or not span or not out:
        print("[fetch] Требуются --exmo-pair, --exmo-candles и --out")
        return 2

    df = fetch_exmo_candles_cached(pair, span)
    if df.empty:
        print("[fetch] Пустые данные от EXMO (возможно, нет доступа к сети).")
        return 0

    df = _ensure_dt(df)
    if rule:
        try:
            df = resample_ohlc(df, rule)
        except Exception:
            o = df["open"].resample(rule).first()
            h = df["high"].resample(rule).max()
            l = df["low"].resample(rule).min()
            c = df["close"].resample(rule).last()
            v = df["volume"].resample(rule).sum()
            df = pd.concat([o, h, l, c, v], axis=1)
            df.columns = ["open", "high", "low", "close", "volume"]
            df = df.dropna(how="any")
            df.index.name = "time"

    try:
        df.reset_index().rename(columns={"time": "timestamp"}).to_csv(out, index=False)
        print(f"[fetch] Сохранено: {out} (rows={len(df)})")
        return 0
    except Exception as e:
        print(f"[fetch] Ошибка сохранения '{out}': {e}")
        return 1
