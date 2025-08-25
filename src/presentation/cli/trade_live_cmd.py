# src/presentation/cli/trade_live_cmd.py
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

# Наши зависимости из проекта
from src.infrastructure.exchange.exmo_api import build_exmo_from_settings
from src.infrastructure.notify.telegram import TelegramNotifier
from src.application.engine.integration import EngineIntegration
from src.domain.risk.risk_service import RiskService, RiskCfg

LOG = logging.getLogger("trade-live")


# ---------------------------
# ВНУТРЕННИЕ УТИЛИТЫ
# ---------------------------

def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug or os.getenv("DEBUG", "").lower() in {"1", "true", "yes", "on"} else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    LOG.debug("Logging configured. Level=%s", logging.getLevelName(level))


def _parse_candles_span(spec: Optional[str]) -> Tuple[int, int]:
    """
    '1m:300' -> (1, 300), поддерживаем только минуты.
    """
    if not spec:
        return 1, 300
    try:
        frame, cnt = spec.split(":")
        cnt = int(cnt)
        if frame.endswith("m"):
            res_min = int(frame[:-1])
            if res_min > 0 and cnt > 0:
                return res_min, cnt
    except Exception:
        pass
    return 1, 300


def _unix_seconds(ts_like: Any) -> Optional[int]:
    """
    Нормализация timestamp: секунды / миллисекунды / микросекунды -> секунды (int).
    """
    try:
        ts = float(ts_like)
    except Exception:
        return None
    if ts > 1e15:  # µs
        ts /= 1_000_000.0
    elif ts > 1e12:  # ms
        ts /= 1_000.0
    return int(ts)


def _sma(series: List[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("window must be > 0")
    out: List[Optional[float]] = [None] * len(series)
    s = 0.0
    for i, x in enumerate(series):
        s += x
        if i >= window:
            s -= series[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def _fetch_candles(pair: str, res_min: int, count: int) -> List[Tuple[int, float]]:
    """
    Забираем свечи EXMO, отдаём [(ts_sec, close), ...] отсортировано.
    """
    now = int(time.time())
    since = now - res_min * 60 * count
    exmo = build_exmo_from_settings()
    data = exmo.candles_history(pair, res_min, since, now)

    candles = []
    if isinstance(data, dict) and isinstance(data.get("candles"), list):
        candles = data["candles"]
    elif isinstance(data, list):
        candles = data
    else:
        raise RuntimeError(f"Unexpected candles format: {type(data)}")

    rows: List[Tuple[int, float]] = []
    for c in candles:
        ts_raw = c.get("t") or c.get("time") or c.get("timestamp") or c.get("date")
        close_raw = c.get("c") or c.get("close")
        if ts_raw is None or close_raw is None:
            continue
        ts = _unix_seconds(ts_raw)
        try:
            close = float(close_raw)
        except Exception:
            continue
        if ts is None:
            continue
        rows.append((ts, close))

    rows.sort(key=lambda x: x[0])
    return rows


# ---------------------------
# НАБЛЮДЕНИЕ (observe)
# ---------------------------

def _run_observe(args: argparse.Namespace) -> int:
    """
    Поллинг свечей, пересчёт SMA(fast/slow), лог последнего бара,
    опциональные Telegram-алёрты (смена состояния + heartbeat).
    """
    if args.exmo_debug:
        os.environ["EXMO_DEBUG"] = "1"

    _setup_logging(args.debug)

    # Telegram
    notifier = TelegramNotifier(token=args.tg_token, chat_id=args.tg_chat)

    # Risk-интеграция «на будущее» (когда появится trade-режим)
    risk = RiskService(RiskCfg(
        max_position_pct=args.max_position_pct,
        stop_loss_bps=args.stop_loss_bps,
        max_daily_loss_bps=args.max_daily_loss_bps,
    ))
    integration = EngineIntegration(
        notifier=notifier,
        risk=risk,
        reconcile_threshold_qty=args.reconcile_threshold_qty,
    )

    pair: str = args.exmo_pair
    res_min, count = _parse_candles_span(args.exmo_candles)
    fast = max(2, int(args.fast))
    slow = max(fast + 1, int(args.slow))
    poll_sec = max(1, int(args.poll_sec))
    hb_sec = max(5, int(args.heartbeat_sec))

    last_ts = 0
    last_state: Optional[int] = None
    last_hb = 0.0

    LOG.info("[live] observe %s %s fast=%d slow=%d poll=%ds", pair, args.exmo_candles, fast, slow, poll_sec)

    try:
        while True:
            try:
                rows = _fetch_candles(pair, res_min, count)
            except Exception as e:
                LOG.error("[live] EXMO error: %s", e)
                time.sleep(poll_sec)
                continue

            if not rows:
                time.sleep(poll_sec)
                continue

            ts_list = [ts for ts, _ in rows]
            prices = [p for _, p in rows]
            sma_f = _sma(prices, fast)
            sma_s = _sma(prices, slow)
            i = len(prices) - 1
            if i < 0 or sma_f[i] is None or sma_s[i] is None:
                time.sleep(poll_sec)
                continue

            ts = ts_list[i]
            close = prices[i]
            f = float(sma_f[i])
            s_val = float(sma_s[i])
            state = 1 if f > s_val else (-1 if f < s_val else 0)

            # новый бар
            if ts != last_ts:
                t_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                LOG.info("[live] %s tick  close=%.6f  f=%.6f  s=%.6f", t_iso, close, f, s_val)

                # алерт при смене состояния
                if args.summary_alert and notifier.enabled and (last_state is None or state != last_state):
                    arrow = "🔼" if state == 1 else ("🔽" if state == -1 else "⏸")
                    msg = (
                        f"<b>Signal {pair}</b> {args.exmo_candles}\n"
                        f"{arrow} state={state} close={close:.6f}\n"
                        f"fast={fast} slow={slow}\n"
                        f"SMAf={f:.6f} SMAs={s_val:.6f}"
                    )
                    try:
                        notifier.send(msg)
                    except Exception:
                        pass

                last_ts = ts
                last_state = state

            # heartbeat
            now_mono = time.monotonic()
            if args.summary_alert and notifier.enabled and (now_mono - last_hb >= hb_sec):
                try:
                    notifier.send(f"✅ live {pair} ok  close={close:.6f}  f={f:.6f}  s={s_val:.6f}")
                except Exception:
                    pass
                last_hb = now_mono

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
        return 0


# ---------------------------
# ПУБЛИЧНЫЙ РЕГИСТРАТОР КОМАНД
# ---------------------------

def register_trade_live(subparsers: argparse._SubParsersAction) -> None:
    """
    Регистрирует подкоманду `trade-live` в твоём большом main.py.
    Никаких правок main.py не требуется.
    """
    p = subparsers.add_parser("trade-live", help="Live pipelines (observe-only)")
    p.add_argument("--mode", type=str, choices=["observe"], default="observe",
                   help="Live mode")
    p.add_argument("--exmo-pair", type=str, default="DOGE_EUR")
    p.add_argument("--exmo-candles", type=str, default="1m:300")
    p.add_argument("--fast", type=int, default=6)
    p.add_argument("--slow", type=int, default=25)

    p.add_argument("--poll-sec", type=int, default=10)
    p.add_argument("--heartbeat-sec", type=int, default=60)

    # Risk-флаги (на будущее — когда добавим trade)
    p.add_argument("--max-position-pct", type=float, default=0.25)
    p.add_argument("--stop-loss-bps", type=int, default=300)
    p.add_argument("--max-daily-loss-bps", type=int, default=0)
    p.add_argument("--reconcile-threshold-qty", type=float, default=0.0001)

    # Telegram
    p.add_argument("--summary-alert", action="store_true")
    p.add_argument("--tg-token", type=str, default=os.getenv("TG_TOKEN", ""))
    p.add_argument("--tg-chat", type=str, default=os.getenv("TG_CHAT", ""))

    # Отладка
    p.add_argument("--debug", action="store_true")
    p.add_argument("--exmo-debug", action="store_true")

    # обработчик
    def _handler(args: argparse.Namespace) -> None:
        if args.mode == "observe":
            rc = _run_observe(args)
            # main.py ожидает, что handler сам печатает/выходит при ошибках.
            # Мы просто возвращаем управление.
            return
        print(f'{"error": "Unsupported live mode"}', flush=True)

    p.set_defaults(func=_handler)
