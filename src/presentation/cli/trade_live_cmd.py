# -*- coding: utf-8 -*-
"""
trade-live: наблюдение (observe) и бумажная торговля (paper).
Добавлено:
- корректный парс процентов/бпс (--risk-max-position-pct принимает 0.25 или 25)
- мультипары через --pairs DOGE_EUR,XRP_EUR
- безопасный fallback-раннер, если "боевой" раннер недоступен
"""

from __future__ import annotations

import time
import typing as t
from dataclasses import dataclass


# --- утилиты парсинга процентов/бпс -------------------------------------------------

def _pct_arg(s: str) -> float:
    """
    Принимает '0.25' или '25' и приводит к доле (0,1].
    """
    v = float(s)
    if v > 1.0:
        v = v / 100.0
    if not (0.0 < v <= 1.0):
        raise ValueError("percentage must be in (0,1] или (0,100]")
    return v


def _bps_arg(s: str) -> int:
    v = int(s)
    if v < 0:
        raise ValueError("bps must be >= 0")
    return v


# --- регистрация сабкоманды ---------------------------------------------------------

def register(subparsers):
    """
    Регистрирует команду 'trade-live'.
    """
    sub = subparsers.add_parser(
        "trade-live",
        help="Онлайн режим: observe/paper для одной или нескольких пар",
    )

    # источник данных (EXMO)
    sub.add_argument("--pair", type=str, help="Пара, напр. BTC_EUR")
    sub.add_argument("--exmo-pair", dest="exmo_pair", type=str, help="Пара EXMO, напр. BTC_EUR")
    sub.add_argument("--candles", type=str, help="Правило загрузки свечей, напр. 1m:720")
    sub.add_argument("--exmo-candles", dest="exmo_candles", type=str, help="Правило загрузки EXMO, напр. 1m:720")
    sub.add_argument("--resample", type=str, default="5m", help="Ресэмплинг, напр. 5m")
    sub.add_argument("--poll-sec", type=int, default=15, help="Интервал опроса, сек")

    # НОВОЕ: мультипары
    sub.add_argument("--pairs", type=str, help="Список пар через запятую: DOGE_EUR,XRP_EUR")

    # режим и стратегия
    sub.add_argument("--mode", required=True, choices=["observe", "paper"], help="Режим работы")
    sub.add_argument(
        "--strategy",
        required=True,
        choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"],
        help="Стратегия",
    )

    # параметры стратегии (если ваша реализация их использует)
    sub.add_argument("--ema-fast", type=int, default=10)
    sub.add_argument("--ema-slow", type=int, default=20)
    sub.add_argument("--adx-len", type=int, default=14)
    sub.add_argument("--adx-on", type=int, default=18)
    sub.add_argument("--adx-off", type=int, default=14)
    sub.add_argument("--require-di", action="store_true", default=False)

    # НОВОЕ: нормальный парс процентов/бпс
    sub.add_argument(
        "--risk-max-position-pct",
        type=_pct_arg,
        default=0.25,
        help="Макс. размер позиции (0..1) или (0..100] в процентах. Примеры: 0.25 или 25",
    )
    sub.add_argument("--risk-stop-loss-bps", type=_bps_arg, default=300, help="Стоп-лосс в bps (1/100%): 300 = 3.0%")
    sub.add_argument("--cooldown-bars", type=int, default=5)
    sub.add_argument("--fee-bps", type=_bps_arg, default=10)
    sub.add_argument("--slip-bps", type=_bps_arg, default=2)

    sub.add_argument("--summary-alert", action="store_true", help="Отправлять краткое резюме в конце итерации")

    sub.set_defaults(_handler=_handle_trade_live)
    return sub


# --- диспетчер и запуск для одной пары ---------------------------------------------

def _handle_trade_live(args):
    """
    Поддерживает одну пару (--pair/--exmo-pair) или много (--pairs=...).
    Для каждой пары запускает live-петлю (боевой раннер или fallback).
    """
    # собираем пары
    pairs: list[str] = []
    if getattr(args, "pairs", None):
        pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    elif getattr(args, "exmo_pair", None):
        pairs = [args.exmo_pair]
    elif getattr(args, "pair", None):
        pairs = [args.pair]

    if not pairs:
        raise SystemExit("нужно указать пару: --pairs или --exmo-pair/--pair")

    results = []
    for pair in pairs:
        results.append(_run_live_for_single_pair(pair, args))
    return results


def _run_live_for_single_pair(pair: str, args):
    """
    Пытаемся вызвать «боевой» раннер, если он есть; иначе — используем встроенный
    fallback-наблюдатель/бумажную торговлю.
    """
    # 1) попытка делегировать в существующий раннер (если он есть в проекте)
    #    это сохранит прежнее поведение без переписывания ядра
    for mod, func in [
        ("src.presentation.cli.live", "run_live"),
        ("src.presentation.cli.trade_live_core", "run_live"),
        ("src.presentation.cli.app_live", "run_live"),
    ]:
        try:
            m = __import__(mod, fromlist=[func])
            run_live = getattr(m, func, None)
            if callable(run_live):
                return run_live(
                    pair=pair,
                    candles=args.exmo_candles or args.candles,
                    resample=args.resample,
                    mode=args.mode,
                    strategy=args.strategy,
                    ema_fast=args.ema_fast,
                    ema_slow=args.ema_slow,
                    adx_len=args.adx_len,
                    adx_on=args.adx_on,
                    adx_off=args.adx_off,
                    require_di=args.require_di,
                    risk_max_position_pct=args.risk_max_position_pct,
                    risk_stop_loss_bps=args.risk_stop_loss_bps,
                    cooldown_bars=args.cooldown_bars,
                    fee_bps=args.fee_bps,
                    slip_bps=args.slip_bps,
                    poll_sec=args.poll_sec,
                    summary_alert=args.summary_alert,
                )
        except Exception:
            # пробуем следующий вариант
            pass

    # 2) fallback: лёгкая наблюдательная петля (без реальных ордеров)
    return _fallback_live_runner(pair, args)


# --- fallback live runner -----------------------------------------------------------

@dataclass
class _StrategyDef:
    name: str
    gen: t.Callable[..., t.List[int]] | None = None


def _fallback_live_runner(pair: str, args):
    """
    Простой цикл: каждые poll-sec подтягиваем свечи из EXMO, ресэмплим,
    считаем сигналы (если стратегия известна) и печатаем сводку.
    Никаких заявок/ордеров в этом fallback нет — только observe/paper-принт.
    """
    # необходимые функции из вашего бэктеста
    from src.backtest.compat import resample_ohlc, normalize_resample_rule

    # пытаемся найти функцию загрузки EXMO-свечей (путь в проекте может отличаться)
    fetch = None
    for mod, func in [
        ("src.infrastructure.exmo.candles", "fetch_exmo_candles_cached"),
        ("src.infrastructure.exmo.api", "fetch_exmo_candles_cached"),
        ("src.infrastructure.exmo", "fetch_exmo_candles_cached"),
    ]:
        try:
            m = __import__(mod, fromlist=[func])
            fetch = getattr(m, func, None)
            if callable(fetch):
                break
        except Exception:
            pass
    if fetch is None:
        raise RuntimeError("Не найден fetch_exmo_candles_cached (проверьте модуль инфраструктуры EXMO).")

    # стратегия и генератор сигналов (если доступен в реестре)
    strat = _resolve_strategy(args)

    span = args.exmo_candles or args.candles
    if not span:
        span = "1m:720"
    rr = normalize_resample_rule(args.resample)

    mode_prefix = "[live] observe" if args.mode == "observe" else "[live] paper"
    print(f"{mode_prefix} {pair} {span} strategy={args.strategy}")

    try:
        while True:
            df = fetch(pair, span)
            if df is None or len(df) == 0:
                print("[live] (no data)")
                time.sleep(args.poll_sec)
                continue

            try:
                rs = resample_ohlc(df, rr)
            except Exception:
                # на всякий случай работаем на исходных свечах
                rs = df

            rows = len(rs)
            last_ts = getattr(rs.index[-1], "isoformat", lambda: str(rs.index[-1]))()
            last_close = float(rs["close"].iloc[-1])

            # если есть генератор сигналов — посчитаем (для информации)
            if strat.gen is not None:
                try:
                    sig = _compute_signals(strat, rs, args)
                    # пример: можно распечатать последний статус
                    last_sig = sig[-1] if sig else 0
                    print(f"[live] {last_ts} close={last_close:.6f} rows={rows} sig={last_sig}")
                except Exception:
                    print(f"[live] {last_ts} close={last_close:.6f} rows={rows}")
            else:
                print(f"[live] {last_ts} close={last_close:.6f} rows={rows}")

            time.sleep(args.poll_sec)
    except KeyboardInterrupt:
        print("[live] stopped by user")
        return {"pair": pair, "ok": True}


def _resolve_strategy(args) -> _StrategyDef:
    """
    Пытаемся найти генератор сигналов стратегии из реестра.
    Если не нашли — вернём заглушку.
    """
    try:
        reg = __import__("src.strategies.registry", fromlist=["get"])
        get = getattr(reg, "get", None)
        if callable(get):
            d = get(args.strategy)
            gen = getattr(d, "generate_signals", None)
            if callable(gen):
                return _StrategyDef(name=args.strategy, gen=gen)
    except Exception:
        pass
    return _StrategyDef(name=args.strategy, gen=None)


def _compute_signals(strat: _StrategyDef, df, args) -> t.List[int]:
    """
    Вызов генератора сигналов с типичными именами аргументов.
    Для ema_adx_atr используем поля, присутствующие в проекте.
    """
    close = df["close"]
    high = df["high"] if "high" in df.columns else df["close"]
    low = df["low"] if "low" in df.columns else df["close"]

    if strat.name == "ema_adx_atr":
        return strat.gen(
            close=close,
            high=high,
            low=low,
            fast=args.ema_fast,
            slow=args.ema_slow,
            adx_len=args.adx_len,
            on=args.adx_on,
            off=args.adx_off,
            require_di=args.require_di,
            atr_len=14,
            atr_mult=3.0,
        )
    elif strat.name == "ema_adx":
        return strat.gen(
            close=close,
            high=high,
            low=low,
            fast=args.ema_fast,
            slow=args.ema_slow,
            adx_len=args.adx_len,
            on=args.adx_on,
            off=args.adx_off,
            require_di=args.require_di,
        )
    else:
        # другие стратегии — пробуем только close
        return strat.gen(close=close)  # type: ignore[call-arg]
