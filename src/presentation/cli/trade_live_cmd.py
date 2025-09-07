# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import argparse
import logging
import time
from typing import List, Tuple

import pandas as pd

from src.backtest.compat import (
    normalize_resample_rule,
    resample_ohlc,
    fetch_exmo_candles_cached,
)
from src.strategies import registry as reg

log = logging.getLogger("cli")


# ------------------------------
# Helpers
# ------------------------------

def _split_tf_count(spec: str) -> Tuple[str, int]:
    if not spec or ":" not in spec:
        raise ValueError(f"Bad candles spec: {spec!r}")
    tf, count_s = spec.split(":", 1)
    return tf.strip(), int(count_s)


def _ensure_dtindex(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        if "ts" in df.columns:
            df = df.set_index("ts")
        else:
            raise ValueError("DataFrame must have DatetimeIndex or 'ts' column")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index()


def _parse_pairs(ns) -> List[str]:
    if getattr(ns, "pairs", None):
        return [p.strip() for p in ns.pairs.split(",") if p.strip()]
    if getattr(ns, "exmo_pair", None):
        return [ns.exmo_pair.strip()]
    if getattr(ns, "pair", None):
        return [ns.pair.strip()]
    raise SystemExit("Укажите хотя бы одну пару через --pairs или --exmo-pair/--pair")


def _fetch_resampled(pair: str, candles: str, resample_rule: str) -> pd.DataFrame:
    tf, count = _split_tf_count(candles)
    raw = fetch_exmo_candles_cached(pair, f"{tf}:{count}")
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    raw = _ensure_dtindex(raw)
    rule = normalize_resample_rule(resample_rule)
    rs = resample_ohlc(raw, rule)
    return rs.dropna()


# ------------------------------
# Live loop
# ------------------------------

def _run_live_for_single_pair(ns, pair: str) -> None:
    candles = getattr(ns, "exmo_candles", None) or getattr(ns, "candles", None)
    if not candles:
        raise SystemExit("Укажите глубину свечей через --candles/--exmo-candles, например 1m:720")
    rule = normalize_resample_rule(ns.resample)

    defn = reg.get(ns.strategy)
    if defn is None:
        raise SystemExit(f"Не найдена стратегия: {ns.strategy}")

    s_kwargs = dict(
        fast=getattr(ns, "ema_fast", 10),
        slow=getattr(ns, "ema_slow", 20),
        adx_len=getattr(ns, "adx_len", 14),
        on=getattr(ns, "adx_on", 18),
        off=getattr(ns, "adx_off", 14),
        require_di=getattr(ns, "require_di", False),
        atr_len=getattr(ns, "atr_len", 14) if hasattr(ns, "atr_len") else 14,
        atr_mult=getattr(ns, "atr_mult", 3.0) if hasattr(ns, "atr_mult") else 3.0,
    )

    while True:
        try:
            df = _fetch_resampled(pair, candles, rule)
            if df.empty:
                log.info("(live) %s no data", pair)
            else:
                last_close = float(df["close"].iloc[-1])
                log.info("[live] %s %s close=%.6f rows=%d", ns.mode, pair, last_close, len(df))

                # Генерим сигналы (для observe просто побочный эффект)
                _ = defn.generate_signals(
                    close=df["close"],
                    high=df.get("high", df["close"]),
                    low=df.get("low", df["close"]),
                    **s_kwargs,
                )

            time.sleep(ns.poll_sec)
        except KeyboardInterrupt:
            log.info("[live] stopped by user")
            break
        except Exception:
            log.exception("live loop failed on %s", pair)
            time.sleep(max(5, ns.poll_sec))


# ------------------------------
# Argparse actions to ensure compatibility
# ------------------------------

class PairsAction(argparse.Action):
    """
    При разборе --pairs:
      - нормализуем строку,
      - сразу заполняем exmo_pair/pair первой парой (важно для префлайтов вне нашей команды).
    """

    def __call__(self, parser, namespace, values, option_string=None):
        pairs_list = [p.strip() for p in (values or "").split(",") if p.strip()]
        setattr(namespace, self.dest, ",".join(pairs_list))
        if pairs_list:
            # back-compat for any upstream code
            if not getattr(namespace, "exmo_pair", None):
                setattr(namespace, "exmo_pair", pairs_list[0])
            if not getattr(namespace, "pair", None):
                setattr(namespace, "pair", pairs_list[0])


class CandlesAliasAction(argparse.Action):
    """
    Делает --exmo-candles полноценным алиасом для --candles прямо на этапе parse_args.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, "exmo_candles", values)
        if not getattr(namespace, "candles", None):
            setattr(namespace, "candles", values)


# ------------------------------
# Entry points
# ------------------------------

def run(ns) -> None:
    pairs = _parse_pairs(ns)
    # Уже не обязательно, но оставим на всякий случай
    setattr(ns, "exmo_pair", pairs[0])
    setattr(ns, "pair", pairs[0])

    log.info("Command: trade-live mode=%s strategy=%s", ns.mode, ns.strategy)

    # Последовательно по всем парам (по запросу сделаем параллель)
    for p in pairs:
        _run_live_for_single_pair(ns, p)
        # break  # раскомментируй, если хочешь обрабатывать только первую пару


def register(subparsers) -> None:
    sub = subparsers.add_parser(
        "trade-live",
        help="Онлайн наблюдение/симуляция сигналов на EXMO",
    )

    sub.add_argument("--pair", type=str, help="Пара, напр. DOGE_EUR")
    sub.add_argument("--exmo-pair", dest="exmo_pair", type=str, help="Пара EXMO (алиас)")

    sub.add_argument("--candles", type=str, help="TF:COUNT, напр. 1m:720")
    sub.add_argument("--exmo-candles", dest="exmo_candles", action=CandlesAliasAction,
                     help="Алиас для --candles")
    sub.add_argument("--resample", type=str, default="5m", help="Ресэмплинг, напр. 5m")

    sub.add_argument("--pairs", type=str, action=PairsAction,
                     help="Список пар через запятую: DOGE_EUR,XRP_EUR")

    sub.add_argument("--mode", required=True, choices=["observe", "paper"], help="Режим работы")
    sub.add_argument(
        "--strategy",
        required=True,
        choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"],
        help="Стратегия",
    )

    sub.add_argument("--ema-fast", type=int, default=10, help="FAST EMA длина")
    sub.add_argument("--ema-slow", type=int, default=20, help="SLOW EMA длина")
    sub.add_argument("--adx-len", type=int, default=14)
    sub.add_argument("--adx-on", type=int, default=18)
    sub.add_argument("--adx-off", type=int, default=14)
    sub.add_argument("--require-di", action="store_true")

    sub.add_argument("--risk-max-position-pct", type=int, default=25)
    sub.add_argument("--risk-stop-loss-bps", type=int, default=300)
    sub.add_argument("--cooldown-bars", type=int, default=5)
    sub.add_argument("--fee-bps", type=int, default=10)
    sub.add_argument("--slip-bps", type=int, default=2)

    sub.add_argument("--poll-sec", type=int, default=15, help="Интервал опроса (сек)")
    sub.add_argument("--summary-alert", action="store_true", help="Короткое резюме сигналов")

    sub.set_defaults(func=run)
