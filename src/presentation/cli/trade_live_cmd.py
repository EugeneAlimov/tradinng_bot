# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


# --- совместимость/утилиты из backtest.compat (если есть) -------------------
def _normalize_rule_local(rule: Optional[str]) -> Optional[str]:
    if not rule:
        return rule
    r = rule.strip()
    # minutes: "5m" -> "5min"
    if r and r[-1].lower() == "m" and (len(r) == 1 or r[-2].isdigit()):
        return r[:-1] + "min"
    return r


try:
    # если модуль доступен — берём оттуда
    from src.backtest.compat import normalize_resample_rule as _norm_rule  # type: ignore
except Exception:
    _norm_rule = _normalize_rule_local  # fallback


# --- модели данных -----------------------------------------------------------
@dataclass
class ObserveSignal:
    time: pd.Timestamp
    price: float
    ema_fast: float
    ema_slow: float
    side: str  # LONG/SHORT/FLAT


# --- парсинг CSV -------------------------------------------------------------
def _parse_epoch_to_ts(x: Any) -> Optional[pd.Timestamp]:
    if pd.isna(x):
        return None
    # поддержка int секунд/миллисек/микро/нано
    try:
        as_int = int(x)
        # эвристики масштаба
        if as_int > 10_000_000_000_000:  # > ~year 2286 в сек — значит нано
            return pd.to_datetime(as_int, unit="ns", utc=True)
        if as_int > 10_000_000_000:  # миллисекунды
            return pd.to_datetime(as_int, unit="ms", utc=True)
        if as_int > 10_000_000:  # секунды
            return pd.to_datetime(as_int, unit="s", utc=True)
    except Exception:
        pass
    # ISO/datetime-строки
    try:
        return pd.to_datetime(x, utc=True, errors="coerce")
    except Exception:
        return None


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}

    # Определим индекс-время
    if "time" in cols:
        ts = df[cols["time"]]
        dt = pd.to_datetime(ts, utc=True, errors="coerce")
    elif "timestamp" in cols:
        ts = df[cols["timestamp"]]
        dt = ts.map(_parse_epoch_to_ts)
    else:
        # если первый столбец — время
        first = df.columns[0]
        dt = pd.to_datetime(df[first], utc=True, errors="coerce")

    dt = pd.Series(dt).astype("datetime64[ns, UTC]")
    df = df.assign(time=dt).dropna(subset=["time"]).set_index("time").sort_index()

    # нормализуем имена цен/объёма
    rename_map = {}
    for c in ("open", "high", "low", "close", "volume"):
        if c not in df.columns:
            # пытаемся найти без учёта регистра
            for cc in df.columns:
                if cc.lower() == c:
                    rename_map[cc] = c
    if rename_map:
        df = df.rename(columns=rename_map)

    # приводим к числам, ffill
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[["open", "high", "low", "close", "volume"]].ffill()

    return df


# --- генерация демо-данных ---------------------------------------------------
def _make_demo_1m(bars: int = 720) -> pd.DataFrame:
    bars = max(int(bars), 10)
    idx = pd.date_range(end=pd.Timestamp.utcnow().floor("min"), periods=bars, freq="1min", tz="UTC")
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0, 0.0015, size=len(idx))
    price = 100 * np.exp(np.cumsum(rets))
    close = pd.Series(price, index=idx)
    spread = np.abs(rng.normal(0, 0.0025, size=len(idx))) * close.values
    high = close + spread
    low = close - spread
    open_ = close.shift(1).fillna(close.iloc[0])
    vol = rng.integers(50, 500, size=len(idx)).astype(float)
    out = pd.DataFrame(
        {"open": open_.values, "high": high.values, "low": low.values, "close": close.values, "volume": vol},
        index=idx,
    )
    out.index.name = "time"
    return out


# --- ресэмпл ------------------------------------------------------------------
def _resample_ohlc(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    if not rule:
        return df
    rule = _norm_rule(rule)
    o = df["open"].resample(rule, origin="start_day").first()
    h = df["high"].resample(rule, origin="start_day").max()
    l = df["low"].resample(rule, origin="start_day").min()
    c = df["close"].resample(rule, origin="start_day").last()
    v = df["volume"].resample(rule, origin="start_day").sum()
    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
    out.index.name = "time"
    return out


# --- сигнал и мини-отчёт -----------------------------------------------------
def _ema_sig(df: pd.DataFrame, fast: int = 10, slow: int = 20) -> Tuple[ObserveSignal, Dict[str, float]]:
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    last = df.index[-1]
    sig = ObserveSignal(
        time=pd.Timestamp(last).tz_convert("UTC") if pd.Timestamp(last).tzinfo else pd.Timestamp(last).tz_localize(
            "UTC"),
        price=float(close.iloc[-1]),
        ema_fast=float(ema_f.iloc[-1]),
        ema_slow=float(ema_s.iloc[-1]),
        side="LONG" if ema_f.iloc[-1] > ema_s.iloc[-1] else ("SHORT" if ema_f.iloc[-1] < ema_s.iloc[-1] else "FLAT"),
    )

    # очень лёгкий мини-репорт по кроссам
    lookback = min(500, len(df))
    r = close.pct_change().fillna(0.0)
    pos = (ema_f > ema_s).astype(float)
    pnl = (pos.shift(1).fillna(0.0) * r).iloc[-lookback:]
    eq = (1.0 + pnl).cumprod()
    dd = (eq / eq.cummax() - 1.0)
    trades = int((pos.astype(int).diff().abs() == 1).iloc[-lookback:].sum())

    summary = {
        "trades": trades,
        "exposure_pct": float(100.0 * pos.iloc[-lookback:].mean()),
        "pnl_pct": float(100.0 * (eq.iloc[-1] - 1.0)),
        "max_dd_pct": float(100.0 * dd.min()),
        "sharpe": float((pnl.mean() / (pnl.std() + 1e-12)) * np.sqrt(365 * 24 * 60)) if pnl.std() > 0 else 0.0,
        "lookback": int(lookback),
        "fast": int(fast),
        "slow": int(slow),
    }
    return sig, summary


def _print_signal_human(sig: ObserveSignal, summary: Optional[Dict[str, float]], fast: int, slow: int,
                        quiet: bool) -> None:
    print(
        f"[trade-live] signal={sig.side} time={sig.time.isoformat()} price={sig.price:.6f} "
        f"ema{fast}={sig.ema_fast:.6f} ema{slow}={sig.ema_slow:.6f}"
    )
    if summary and not quiet:
        print(
            f"[trade-live] summary (lookback={summary.get('lookback', 0)}): "
            f"trades={summary.get('trades')} exposure={summary.get('exposure_pct', 0.0):.1f}% "
            f"pnl={summary.get('pnl_pct', 0.0):.2f}% maxDD={summary.get('max_dd_pct', 0.0):.2f}% "
            f"sharpe={summary.get('sharpe', 0.0):.2f}"
        )


def _print_signal_json(sig: ObserveSignal, summary: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {
        "time": sig.time.isoformat(),
        "price": sig.price,
        "ema_fast": sig.ema_fast,
        "ema_slow": sig.ema_slow,
        "side": sig.side,
    }
    if summary:
        for k in ("trades", "exposure_pct", "pnl_pct", "max_dd_pct", "sharpe", "lookback"):
            if k in summary:
                payload[k] = summary[k]
    print(json.dumps(payload, ensure_ascii=False))


def _print_last_bar_json(df: pd.DataFrame) -> None:
    last = df.iloc[-1]
    print(json.dumps({
        "time": str(df.index[-1]),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "close": float(last["close"]),
        "volume": float(last["volume"]),
    }, ensure_ascii=False))


# --- основной обработчик -----------------------------------------------------
def _load_source(args) -> Tuple[pd.DataFrame, str]:
    """
    Возвращает (df_ресемпленный, описание_источника).
    Источник выбирается по приоритету: --demo > --data > --exmo-*.
    """
    df_1m: pd.DataFrame
    src_desc: str

    if getattr(args, "demo", False):
        df_1m = _make_demo_1m(getattr(args, "bars", 720))
        src_desc = f"demo:{len(df_1m)}"
    elif getattr(args, "data", None):
        p = str(args.data)
        if not os.path.exists(p):
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), f"csv_missing:{p}"
        df_1m = _load_csv(p)
        src_desc = f"csv:{p}"
    else:
        # Попытка через compat (если есть сеть/кэш). В оффлайне будет пусто — это ок.
        pair, span = getattr(args, "exmo_pair", None), getattr(args, "exmo_candles", None)
        try:
            from src.backtest.compat import fetch_exmo_candles_cached  # type: ignore
            df_1m = fetch_exmo_candles_cached(pair, span) if (pair and span) else pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            )
        except Exception:
            df_1m = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        src_desc = f"exmo:{pair}:{span}"

    df_1m = df_1m.sort_index()
    df = _resample_ohlc(df_1m, getattr(args, "resample", None))
    return df, src_desc


def handler(args) -> int:
    """Совместимый с app.py вход — то же, что и run/main."""
    return run(args)


def main(args) -> int:
    """Совместимый с app.py вход — то же, что и run/handler."""
    return run(args)


def run(args) -> int:
    mode = getattr(args, "mode", "observe")
    strategy = getattr(args, "strategy", None)
    resample = getattr(args, "resample", None)
    poll_sec = int(getattr(args, "poll_sec", 10))
    once = bool(getattr(args, "once", False))
    quiet = bool(getattr(args, "quiet", False))
    signal_json = bool(getattr(args, "signal_json", False))
    stdout_json = bool(getattr(args, "stdout_json", False))
    bars = int(getattr(args, "bars", 720))

    print(
        f"[trade-live] mode={mode} strategy={strategy} "
        f"pair={getattr(args, 'exmo_pair', None)} span={getattr(args, 'exmo_candles', None)} "
        f"resample={resample} poll_sec={poll_sec} data={getattr(args, 'data', None)} "
        f"demo={getattr(args, 'demo', False)} bars={bars}"
    )

    df, source = _load_source(args)
    if df.empty:
        print("[trade-live] Пустые данные. Варианты:\n"
              "  • --demo [--bars N] — сгенерировать синтетические свечи\n"
              "  • --data /путь/к/ohlcv.csv — загрузить локальный CSV\n"
              "  • --exmo-pair ... --exmo-candles ... — если кэш EXMO уже прогрет")
        return 0

    if not quiet:
        print(f"[trade-live] источник={source} bars={len(df)}")
        if len(df) >= 5 and once:
            # Только в подробном разовом режиме покажем head(5)
            print(df.head(5))

    # Настройки простой EMA-стратегии (пока фиксированные; параметры можно пробросить позже)
    fast, slow = 10, 20

    def _one_step() -> None:
        last_ts = df.index[-1]
        last = df.loc[last_ts]
        if not quiet:
            print(
                f"[trade-live] last={pd.Timestamp(last_ts).isoformat()} "
                f"O={last['open']} H={last['high']} L={last['low']} C={last['close']} V={last['volume']}"
            )
        sig, summary = _ema_sig(df, fast=fast, slow=slow)
        if signal_json:
            _print_signal_json(sig, summary)
        elif stdout_json:
            _print_last_bar_json(df)
        else:
            _print_signal_human(sig, summary, fast=fast, slow=slow, quiet=quiet)

    try:
        _one_step()
        if once:
            return 0
        while True:
            time.sleep(max(1, poll_sec))
            # в простом оффлайн-режиме данных нет обновления — для примера используем тот же df
            _one_step()
    except KeyboardInterrupt:
        print("[trade-live] Останов по Ctrl+C")
        return 0
