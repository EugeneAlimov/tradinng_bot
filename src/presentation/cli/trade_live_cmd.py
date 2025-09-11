# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from src.backtest.compat import (
    ensure_datetime_index,
    normalize_resample_rule,
    resample_ohlc,
    fetch_exmo_candles_cached,
)

from src.strategies.registry import get as get_strategy  # твой реестр стратегий

log = logging.getLogger("cli")


# ------------------------------
# Внутренние структуры аргументов
# ------------------------------

@dataclass(frozen=True)
class LiveArgs:
    mode: str  # "observe" | "paper"
    strategy: str  # имя стратегии из реестра
    pair: str  # одна пара
    candles: str  # "TF:COUNT", например "1m:720"
    resample: Optional[str]  # например "5m"
    poll_sec: int  # интервал опроса

    # Параметры стратегии (опциональны, чтобы не забивать дефолты None'ом)
    ema_fast: Optional[int] = None
    ema_slow: Optional[int] = None
    adx_len: Optional[int] = None
    adx_on: Optional[float] = None
    adx_off: Optional[float] = None
    require_di: bool = False

    # Торговые параметры «бумажного» режима
    risk_max_position_pct: Optional[int] = None
    risk_stop_loss_bps: Optional[int] = None
    cooldown_bars: Optional[int] = None
    fee_bps: Optional[int] = None
    slip_bps: Optional[int] = None

    summary_alert: bool = False


# ------------------------------
# Утилиты
# ------------------------------

def _build_df(pair: str, span: str, resample_rule: Optional[str]) -> pd.DataFrame:
    df = fetch_exmo_candles_cached(pair=pair, span=span)
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise RuntimeError(f"[exmo] empty candles for {pair}")
    df = ensure_datetime_index(df)
    if resample_rule:
        rule = normalize_resample_rule(resample_rule)
        df = resample_ohlc(df, rule)
    return df


def _strategy_kwargs_from(args: LiveArgs) -> dict[str, object]:
    raw = dict(
        fast=args.ema_fast,
        slow=args.ema_slow,
        adx_len=args.adx_len,
        on=args.adx_on,
        off=args.adx_off,
    )
    # require_di добавляем только если True
    if args.require_di:
        raw["require_di"] = True
    return {k: v for k, v in raw.items() if v is not None}


def _print_params_for_log(params: Dict[str, object]) -> None:
    log.info("Strategy parameters: %s", params or "{}")


# ------------------------------
# Основной цикл live
# ------------------------------

def run_live(args: LiveArgs) -> int:
    """
    Запускает наблюдение/бумажную торговлю по одной паре.
    """
    df = _build_df(args.pair, args.candles, args.resample)
    log.info(
        "[live] %s %s %s strategy=%s rows=%d",
        args.mode, args.pair, args.candles, args.strategy, len(df)
    )

    strat_def = get_strategy(args.strategy)
    strat_kwargs = _strategy_kwargs_from(args)
    _print_params_for_log(strat_kwargs)

    last_ts: Optional[pd.Timestamp] = None

    while True:
        try:
            # Перечитываем данные порционно
            df = _build_df(args.pair, args.candles, args.resample)

            # Сигналы
            close = df["close"].to_numpy(float)
            high = df["high"].to_numpy(float)
            low = df["low"].to_numpy(float)

            # ВАЖНО: не передаём None — только то, что указано явно
            signals = strat_def.generate_signals(
                close=close, high=high, low=low, **strat_kwargs
            )

            # Простейший "observe": просто выводим «хвост»
            ts = df.index[-1]
            if last_ts != ts:
                last_ts = ts
                log.info("[live] %s close=%s rows=%d", ts.isoformat(), df["close"].iloc[-1], len(df))

            # В режиме paper здесь может быть эмуляция выставления позиций
            if args.mode == "paper":
                # ... интеграция с твоим paper-движком/PNL ...
                pass

            time.sleep(int(args.poll_sec))
        except KeyboardInterrupt:
            log.info("[live] stopped by user")
            break
        except Exception as e:
            log.exception("Signal evaluation error: %s", e)
            time.sleep(int(args.poll_sec))

    return 0
