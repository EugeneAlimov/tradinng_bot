# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("cli")


# -----------------------------------------------------------------------------
# Динамические импорты с фолбэками, чтобы IDE не ругалась и рантайм был устойчив
# -----------------------------------------------------------------------------
def _load_compat_funcs():
    """
    Пытаемся подтянуть утилиты ресемплинга из проекта.
    Если не вышло — даём минимальные локальные версии.
    """
    normalize_resample_rule = None
    resample_ohlc = None
    ensure_datetime_index = None

    try:
        compat = importlib.import_module("src.backtest.compat")
        normalize_resample_rule = getattr(compat, "normalize_resample_rule", None)
        resample_ohlc = getattr(compat, "resample_ohlc", None)
        ensure_datetime_index = getattr(compat, "ensure_datetime_index", None)
    except Exception:
        pass

    def _local_normalize_resample_rule(rule: str) -> str:
        if not rule:
            return "5min"
        rule = str(rule).strip().lower()
        # pandas совместимые алиасы
        rule = rule.replace("m", "min").replace("h", "H")
        return rule

    def _local_ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df.index, pd.DatetimeIndex):
            idx_name = df.columns[0] if len(df.columns) else None
            if "time" in df.columns:
                df = df.set_index("time")
            elif "date" in df.columns:
                df = df.set_index("date")
            elif idx_name:
                df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df.sort_index()

    def _local_resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        rule = _local_normalize_resample_rule(rule)
        df = _local_ensure_datetime_index(df)
        o = df["open"].resample(rule).first()
        h = df["high"].resample(rule).max()
        l = df["low"].resample(rule).min()
        c = df["close"].resample(rule).last()
        v = None
        if "volume" in df.columns:
            v = df["volume"].resample(rule).sum()
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
        if v is not None:
            out["volume"] = v
        return out.dropna(how="any")

    return (
        normalize_resample_rule or _local_normalize_resample_rule,
        resample_ohlc or _local_resample_ohlc,
        ensure_datetime_index or _local_ensure_datetime_index,
    )


def _load_exmo_fetcher() -> Callable[[str, str], pd.DataFrame]:
    """
    Возвращает функцию fetch_exmo_candles_cached(symbol, candles_spec)
    candles_spec: 'TF:COUNT' (например, '1m:720' или '5m:3000')
    """
    try:
        mod = importlib.import_module("src.infrastructure.exchange.exmo")
        fn = getattr(mod, "fetch_exmo_candles_cached", None)
        if callable(fn):
            return fn
    except Exception:
        pass

    # Минимальный фолбэк — просто бросаем исключение с подсказкой.
    def _fallback(_symbol: str, _candles_spec: str) -> pd.DataFrame:
        raise RuntimeError(
            "EXMO fetcher not available. Expected "
            "`src.infrastructure.exchange.exmo.fetch_exmo_candles_cached`."
        )

    return _fallback


# -----------------------------------------------------------------------------
# Аргументы live-режима
# -----------------------------------------------------------------------------
@dataclass
class LiveArgs:
    mode: str
    strategy: str
    pairs: List[str]
    candles: str
    resample: Optional[str]
    poll_sec: int
    ema_fast: Optional[int] = None
    ema_slow: Optional[int] = None
    adx_len: Optional[int] = None
    adx_on: Optional[float] = None
    adx_off: Optional[float] = None
    require_di: bool = False
    risk_max_position_pct: Optional[int] = None
    risk_stop_loss_bps: Optional[int] = None
    cooldown_bars: Optional[int] = None
    fee_bps: int = 0
    slip_bps: int = 0
    summary_alert: bool = False


# -----------------------------------------------------------------------------
# Вспомогательные
# -----------------------------------------------------------------------------
def _parse_pairs(args: argparse.Namespace) -> List[str]:
    if getattr(args, "pairs", None):
        return [s.strip() for s in str(args.pairs).split(",") if s.strip()]
    # обратная совместимость: --exmo-pair / --pair
    pair = getattr(args, "exmo_pair", None) or getattr(args, "pair", None)
    if not pair:
        return []
    return [str(pair).strip()]


def _pick_candles(args: argparse.Namespace) -> str:
    # поддерживаем оба флага, берём первый непустой
    return (
        getattr(args, "exmo_candles", None)
        or getattr(args, "candles", None)
        or "1m:720"
    )


def _strategy_def(strategy: str):
    """
    Возвращает объект стратегии из реестра, иначе напрямую модуль.
    Ожидается, что у объекта есть .generate_signals(...) и, опционально, .status(...)
    """
    # сначала пробуем реестр
    try:
        reg = importlib.import_module("src.strategies.registry")
        get = getattr(reg, "get", None)
        if callable(get):
            d = get(strategy)
            if d is not None:
                return d
    except Exception:
        pass

    # модуль напрямую
    try:
        mod = importlib.import_module(f"src.strategies.{strategy}")
        return mod
    except Exception as e:
        raise RuntimeError(f"Strategy '{strategy}' not found") from e


def _ema_adx_default_params(args: LiveArgs) -> Dict[str, object]:
    # разумные дефолты, можно перекрыть флагами CLI
    out = dict(
        fast=args.ema_fast or 12,
        slow=args.ema_slow or 21,
        adx_len=args.adx_len or 14,
        on=args.adx_on if args.adx_on is not None else 23.0,
        off=args.adx_off if args.adx_off is not None else 17.0,
        require_di=args.require_di or False,
    )
    return out


# -----------------------------------------------------------------------------
# Основная логика live
# -----------------------------------------------------------------------------
def _run_live_for_single_pair(
    pair: str,
    args: LiveArgs,
    fetch_candles: Callable[[str, str], pd.DataFrame],
    normalize_resample_rule: Callable[[str], str],
    resample_ohlc: Callable[[pd.DataFrame, str], pd.DataFrame],
    ensure_datetime_index: Callable[[pd.DataFrame], pd.DataFrame],
):
    candles_spec = args.candles
    resample_rule = normalize_resample_rule(args.resample) if args.resample else None

    strat = _strategy_def(args.strategy)
    log.info(
        "Strategy parameters: %s",
        _ema_adx_default_params(args) if args.strategy.startswith("ema") else {},
    )

    open_pos = False
    entry_price = None
    entry_time = None

    # первичная загрузка
    df = fetch_candles(pair, candles_spec)
    log.info("[exmo] received %s candles for %s", len(df), pair)
    df = ensure_datetime_index(df)
    if resample_rule:
        df = resample_ohlc(df, resample_rule)

    print(f"[live] {args.mode} {pair} {candles_spec} strategy={args.strategy} rows={len(df)}")

    # основной цикл
    while True:
        # обновление котировок
        try:
            df = fetch_candles(pair, candles_spec)
            df = ensure_datetime_index(df)
            if resample_rule:
                df = resample_ohlc(df, resample_rule)
        except KeyboardInterrupt:
            log.info("[live] stopped by user")
            break
        except Exception as e:
            log.warning("Fetch failed: %s", e)
            time.sleep(max(5, args.poll_sec))
            continue

        if df.empty or "close" not in df.columns:
            print("(no data)")
            time.sleep(args.poll_sec)
            continue

        # сигналы
        try:
            params = {}
            if args.strategy in ("ema_adx", "ema_adx_atr"):
                params = _ema_adx_default_params(args)

            # общее API: generate_signals(close, high, low, **params) -> List[int]
            sig = strat.generate_signals(
                close=df["close"], high=df.get("high"), low=df.get("low"), **params
            )
            last_sig = int(sig[-1]) if sig else 0
        except Exception:
            # если что-то пошло не так со стратегией — просто печатаем последнюю цену
            last_sig = 0

        last_ts = df.index[-1]
        last_close = float(df["close"].iloc[-1])

        # простая бумажная логика вход/выход
        if args.mode == "observe":
            print(f"[live] {last_ts} close={last_close:.6f} rows={len(df)}")
        else:
            # paper
            if not open_pos and last_sig > 0:
                open_pos = True
                entry_price = last_close
                entry_time = last_ts
                print(
                    f"[live] ENTER {pair} @ {entry_price:.6f} "
                    f"(EMA/ADX conditions met)"
                )
            elif open_pos and last_sig < 0:
                pnl = (last_close / entry_price - 1.0) * 100.0 if entry_price else 0.0
                dur_min = (last_ts - entry_time).total_seconds() / 60.0 if entry_time else 0.0
                print(
                    f"[live] EXIT {pair} @ {last_close:.6f} "
                    f"PnL: {pnl:+.2f}% Duration: {dur_min:.1f}min"
                )
                open_pos = False
                entry_price = None
                entry_time = None

        try:
            time.sleep(max(1, args.poll_sec))
        except KeyboardInterrupt:
            log.info("[live] stopped by user")
            if open_pos and entry_price is not None:
                pnl = (last_close / entry_price - 1.0) * 100.0
                print(f"[live] Final position PnL: {pnl:+.2f}%")
            break


# -----------------------------------------------------------------------------
# CLI entry
# -----------------------------------------------------------------------------
def build(subparsers: argparse._SubParsersAction | argparse.ArgumentParser):
    """
    Регистрирует команду trade-live; тип аннотации сделан максимально нейтральным
    чтобы IDE не ругалась на приватные типы из argparse.pyi.
    """
    p = subparsers.add_parser(
        "trade-live",
        help="Live observe/paper на EXMO (одна или несколько пар)",
    )
    # источники данных
    p.add_argument("--pair", help="Пара, напр. DOGE_EUR")
    p.add_argument("--exmo-pair", dest="exmo_pair", help="Пара EXMO (синоним)")
    p.add_argument("--candles", help="TF:COUNT (e.g. 5m:2500)")
    p.add_argument("--exmo-candles", dest="exmo_candles", help="Алиас для --candles")
    p.add_argument("--resample", help="Правило ресемплинга (e.g. 5m, 1H)")

    # режим/стратегия
    p.add_argument("--mode", required=True, choices=["observe", "paper"])
    p.add_argument(
        "--strategy",
        required=True,
        choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"],
    )

    # мульти-пары
    p.add_argument(
        "--pairs",
        help="Список пар через запятую, напр. DOGE_EUR,XRP_EUR",
    )

    # параметры стратегий (опционально)
    p.add_argument("--ema-fast", type=int, dest="ema_fast")
    p.add_argument("--ema-slow", type=int, dest="ema_slow")
    p.add_argument("--adx-len", type=int, dest="adx_len")
    p.add_argument("--adx-on", type=float, dest="adx_on")
    p.add_argument("--adx-off", type=float, dest="adx_off")
    p.add_argument("--require-di", action="store_true", dest="require_di")

    # риск/издержки (используются в paper для отчётности)
    p.add_argument("--risk-max-position-pct", type=int, dest="risk_max_position_pct")
    p.add_argument("--risk-stop-loss-bps", type=int, dest="risk_stop_loss_bps")
    p.add_argument("--cooldown-bars", type=int, dest="cooldown_bars")
    p.add_argument("--fee-bps", type=int, default=0)
    p.add_argument("--slip-bps", type=int, default=0)

    p.add_argument("--poll-sec", type=int, default=15, help="Интервал опроса (сек)")
    p.add_argument("--summary-alert", action="store_true", help="Короткое резюме сигналов")

    p.set_defaults(func=_run)


def _run(ns: argparse.Namespace):
    pairs = _parse_pairs(ns)
    candles = _pick_candles(ns)
    if not pairs:
        log.warning("No pair specified. Use --pair/--exmo-pair or --pairs")
        print("(no data)")
        return

    args = LiveArgs(
        mode=ns.mode,
        strategy=ns.strategy,
        pairs=pairs,
        candles=candles,
        resample=getattr(ns, "resample", None),
        poll_sec=int(getattr(ns, "poll_sec", 15) or 15),
        ema_fast=getattr(ns, "ema_fast", None),
        ema_slow=getattr(ns, "ema_slow", None),
        adx_len=getattr(ns, "adx_len", None),
        adx_on=getattr(ns, "adx_on", None),
        adx_off=getattr(ns, "adx_off", None),
        require_di=bool(getattr(ns, "require_di", False)),
        risk_max_position_pct=getattr(ns, "risk_max_position_pct", None),
        risk_stop_loss_bps=getattr(ns, "risk_stop_loss_bps", None),
        cooldown_bars=getattr(ns, "cooldown_bars", None),
        fee_bps=int(getattr(ns, "fee_bps", 0) or 0),
        slip_bps=int(getattr(ns, "slip_bps", 0) or 0),
        summary_alert=bool(getattr(ns, "summary_alert", False)),
    )

    log.info(
        "Command: trade-live mode=%s strategy=%s pair%s=%s",
        args.mode,
        args.strategy,
        "(s)" if len(args.pairs) > 1 else "",
        ",".join(args.pairs),
    )

    normalize_resample_rule, resample_ohlc, ensure_datetime_index = _load_compat_funcs()
    fetch_candles = _load_exmo_fetcher()

    # запускаем последовательно (простая реализация)
    for pair in args.pairs:
        try:
            _run_live_for_single_pair(
                pair=pair,
                args=args,
                fetch_candles=fetch_candles,
                normalize_resample_rule=normalize_resample_rule,
                resample_ohlc=resample_ohlc,
                ensure_datetime_index=ensure_datetime_index,
            )
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("Live session failed for %s: %s", pair, e)
            print("(no data)")
