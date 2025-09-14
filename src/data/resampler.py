# src/data/resampler.py
from __future__ import annotations
import re
import pandas as pd

_MINUTE_RX = re.compile(r"^(\d+)\s*[mM]$")


def normalize_resample_rule(rule: str) -> str:
    """
    Normalize user rule:
      - '5m' -> '5min'
      - '1min' stays '1min'
      - leave pandas-valid rules intact
    """
    rule = rule.strip()
    m = _MINUTE_RX.match(rule)
    if m:
        return f"{int(m.group(1))}min"
    return rule


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample OHLCV by rule (minutes, hours, etc.), keeping UTC tz-aware index.
    """
    if df.empty:
        return df.copy()

    rule_n = normalize_resample_rule(rule)

    o = df["open"].resample(rule_n).first()
    h = df["high"].resample(rule_n).max()
    l = df["low"].resample(rule_n).min()
    c = df["close"].resample(rule_n).last()
    v = df["volume"].resample(rule_n).sum()

    out = pd.concat({"open": o, "high": h, "low": l, "close": c, "volume": v}, axis=1).dropna(how="any")
    out.index = out.index.tz_localize("UTC") if out.index.tz is None else out.index.tz_convert("UTC")
    out.index.name = "time"
    return out
