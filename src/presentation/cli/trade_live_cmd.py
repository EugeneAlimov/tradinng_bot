# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

# Используем совместимый фасад backtest.compat — он уже оборачивает sweep/exmo
from src.backtest.compat import (
    normalize_resample_rule,
    resample_ohlc,
    fetch_exmo_candles_cached,
)

log = logging.getLogger("cli")


# ---------------------------
# Вспомогательные утилиты
# ---------------------------

def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Осторожно приводим индекс к DatetimeIndex (UTC) и сортируем.
    Ничего «лишнего» не трогаем, чтобы не ломать совместимость.
    """
    if df is None or len(df) == 0:
        return df

    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df = df.copy()
            df.index = df.index.tz_localize("UTC")
        return df.sort_index()

    # Попробуем типичные колонки с временем
    for col in ("ts", "timestamp", "date", "time"):
        if col in df.columns:
            idx = pd.to_datetime(df[col], utc=True, errors="coerce")
            df = df.copy()
            df.index = idx
            df.drop(columns=[col], inplace=True, errors="ignore")
            return df.sort_index()

    # Фолбэк: попытаться распарсить текущий индекс
    try:
        idx = pd.to_datetime(df.index, utc=True, errors="coerce")
        df = df.copy()
        df.index = idx
        return df.sort_index()
    except Exception:
        return df


# ---------------------------
# Вспомогательные структуры
# ---------------------------

@dataclass
class LiveArgs:
    pair: str  # EXMO символ, например "DOGE_EUR"
    candles: str  # "TF:COUNT", например "1m:720"
    resample: str  # "5m", "1H" и т.п. (уже нормализованное)
    mode: str  # "observe" | "paper"
    strategy: str  # "ema_adx", "ema_adx_atr", ...
    ema_fast: Optional[int]  # для ema_adx/ema_adx_atr
    ema_slow: Optional[int]
    adx_len: Optional[int]
    adx_on: Optional[int]
    adx_off: Optional[int]
    require_di: bool
    risk_max_position_pct: Optional[int]
    risk_stop_loss_bps: Optional[int]
    cooldown_bars: Optional[int]
    fee_bps: Optional[int]
    slip_bps: Optional[int]
    poll_sec: int
    summary_alert: bool


# ---------------------------
# Парсинг аргумента --pairs
# ---------------------------

def _parse_pairs_arg(pairs: Optional[str]) -> List[str]:
    """
    Разбор строки из --pairs. Возвращает список непустых символов EXMO.
    """
    if not pairs:
        return []
    out: List[str] = []
    for raw in pairs.split(","):
        s = (raw or "").strip()
        if not s:
            continue
        out.append(s)
    return out


# ---------------------------
# Цикл по одной паре
# ---------------------------

def _run_live_for_single_pair(a: LiveArgs) -> None:
    """
    Один бесконечный цикл по одной паре. Поведение как в однопарном режиме:
    печатаем последний close и число строк после ресэмплинга.
    """
    header = f"[live] {a.mode} {a.pair} {a.candles} strategy={a.strategy}"
    try:
        # sanity-check аргументов до вызовов EXMO
        if not a.pair:
            log.error("[live] empty pair received — skip thread start")
            return
        if ":" not in a.candles:
            log.error("[live] bad candles format for %s: %s", a.pair, a.candles)
            return

        # Нормализуем правило ресэмплинга
        rr = normalize_resample_rule(a.resample)
        log.info("%s starting (resample=%s)", header, rr)

        # Основной цикл
        while True:
            try:
                # 1) забираем сырые свечи через совместимый фасад
                raw = fetch_exmo_candles_cached(pair=a.pair, span=a.candles)
                if raw is None or len(raw) == 0:
                    log.warning("[live] %s no data", a.pair)
                    time.sleep(a.poll_sec)
                    continue

                df = _ensure_datetime_index(raw)
                # 2) ресэмплим
                rs = resample_ohlc(df, rr) if rr else df
                if rs is None or len(rs) == 0:
                    log.warning("[live] %s resample empty", a.pair)
                    time.sleep(a.poll_sec)
                    continue

                # 3) печать как раньше (observe/paper одинаково для вывода)
                last_ts = rs.index[-1]
                last_close = float(pd.to_numeric(rs["close"].iloc[-1], errors="coerce"))
                print(f"[live] {last_ts} close={last_close:.6f} rows={len(rs)}", flush=True)

                # 4) пауза
                time.sleep(a.poll_sec)

            except KeyboardInterrupt:
                print("[live] stopped by user", flush=True)
                break
            except Exception as e:
                log.exception("[live] loop error for %s: %s", a.pair, e)
                time.sleep(a.poll_sec)
    except KeyboardInterrupt:
        print("[live] stopped by user", flush=True)


# ---------------------------
# Публичная CLI-обвязка
# ---------------------------

def register(subparsers):
    """
    Регистрирует команду trade-live с мультипарной поддержкой (--pairs).
    """
    p = subparsers.add_parser(
        "trade-live",
        help="Онлайн наблюдение или paper-трейдинг по стратегии",
    )

    # Источник данных (совместимо с текущим контрактом)
    p.add_argument("--pair", dest="pair", help="Пара, напр. DOGE_EUR")
    p.add_argument("--exmo-pair", dest="exmo_pair", help="Пара EXMO (синоним)")
    p.add_argument("--candles", dest="candles", help="TF:COUNT (e.g. 5m:2500)")
    p.add_argument("--exmo-candles", dest="exmo_candles", help="Алиас для --candles")
    p.add_argument("--resample", dest="resample", default="5m", help="Правило ресемплинга (e.g. 5m, 1H)")

    # Новый аргумент: несколько пар
    p.add_argument("--pairs", dest="pairs", help="Список пар через запятую, напр. DOGE_EUR,XRP_EUR")

    # Режим и стратегия
    p.add_argument("--mode", required=True, choices=["observe", "paper"])
    p.add_argument("--strategy", required=True, choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])

    # Параметры стратегий (оставляем как есть)
    p.add_argument("--ema-fast", dest="ema_fast", type=int)
    p.add_argument("--ema-slow", dest="ema_slow", type=int)
    p.add_argument("--adx-len", dest="adx_len", type=int)
    p.add_argument("--adx-on", dest="adx_on", type=int)
    p.add_argument("--adx-off", dest="adx_off", type=int)
    p.add_argument("--require-di", dest="require_di", action="store_true")

    # Риск-менеджмент и издержки
    p.add_argument("--risk-max-position-pct", dest="risk_max_position_pct", type=int)
    p.add_argument("--risk-stop-loss-bps", dest="risk_stop_loss_bps", type=int)
    p.add_argument("--cooldown-bars", dest="cooldown_bars", type=int)
    p.add_argument("--fee-bps", dest="fee_bps", type=int)
    p.add_argument("--slip-bps", dest="slip_bps", type=int)

    # Прочее
    p.add_argument("--poll-sec", dest="poll_sec", type=int, default=15, help="Интервал опроса (сек)")
    p.add_argument("--summary-alert", dest="summary_alert", action="store_true", help="Короткое резюме сигналов")

    p.set_defaults(_handler=_handle_trade_live)


def _handle_trade_live(args) -> None:
    """
    Точка входа для команды trade-live.
    - если задан --pairs, работаем ТОЛЬКО по нему (чтобы не подхватить пустую пару);
    - иначе — одиночная ветка совместимая с прежним поведением.
    """
    log.info("Command: trade-live mode=%s strategy=%s", args.mode, args.strategy)

    # 1) Мультипары
    pairs = _parse_pairs_arg(getattr(args, "pairs", None))
    if pairs:
        candles = getattr(args, "exmo_candles", None) or getattr(args, "candles", None) or "1m:720"
        resample_rule = getattr(args, "resample", "5m")

        common_kwargs = dict(
            candles=candles,
            resample=resample_rule,
            mode=args.mode,
            strategy=args.strategy,
            ema_fast=getattr(args, "ema_fast", None),
            ema_slow=getattr(args, "ema_slow", None),
            adx_len=getattr(args, "adx_len", None),
            adx_on=getattr(args, "adx_on", None),
            adx_off=getattr(args, "adx_off", None),
            require_di=getattr(args, "require_di", False),
            risk_max_position_pct=getattr(args, "risk_max_position_pct", None),
            risk_stop_loss_bps=getattr(args, "risk_stop_loss_bps", None),
            cooldown_bars=getattr(args, "cooldown_bars", None),
            fee_bps=getattr(args, "fee_bps", None),
            slip_bps=getattr(args, "slip_bps", None),
            poll_sec=getattr(args, "poll_sec", 15),
            summary_alert=getattr(args, "summary_alert", False),
        )

        threads: List[threading.Thread] = []
        for p in pairs:
            if not p:
                continue
            live_args = LiveArgs(pair=p, **common_kwargs)
            t = threading.Thread(target=_run_live_for_single_pair, args=(live_args,), daemon=True)
            t.start()
            threads.append(t)

        if not threads:
            print("(no data)")
            return

        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("[live] stopped by user")
        return

    # 2) Одиночная ветка
    pair = getattr(args, "exmo_pair", None) or getattr(args, "pair", None)
    if not pair:
        log.error("[live] neither --pair/--exmo-pair nor --pairs specified")
        print("(no data)")
        return

    candles = getattr(args, "exmo_candles", None) or getattr(args, "candles", None) or "1m:720"
    resample_rule = getattr(args, "resample", "5m")

    live_args = LiveArgs(
        pair=pair,
        candles=candles,
        resample=resample_rule,
        mode=args.mode,
        strategy=args.strategy,
        ema_fast=getattr(args, "ema_fast", None),
        ema_slow=getattr(args, "ema_slow", None),
        adx_len=getattr(args, "adx_len", None),
        adx_on=getattr(args, "adx_on", None),
        adx_off=getattr(args, "adx_off", None),
        require_di=getattr(args, "require_di", False),
        risk_max_position_pct=getattr(args, "risk_max_position_pct", None),
        risk_stop_loss_bps=getattr(args, "risk_stop_loss_bps", None),
        cooldown_bars=getattr(args, "cooldown_bars", None),
        fee_bps=getattr(args, "fee_bps", None),
        slip_bps=getattr(args, "slip_bps", None),
        poll_sec=getattr(args, "poll_sec", 15),
        summary_alert=getattr(args, "summary_alert", False),
    )
    _run_live_for_single_pair(live_args)
