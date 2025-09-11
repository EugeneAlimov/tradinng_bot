# src/presentation/cli/walk_forward_cmd.py
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.backtest.walkforward import WFConfig, run_walk_forward
from src.backtest.compat import normalize_resample_rule  # единая нормализация

log = logging.getLogger("cli.walk_forward")


def _int_arg(x: str) -> int:
    return int(float(x))


def _float_arg(x: str) -> float:
    return float(x)


def register(subparsers) -> argparse.ArgumentParser:
    """
    Регистрирует команду `walk-forward`.
    """
    p = subparsers.add_parser(
        "walk-forward",
        help="Walk-forward валидация фиксированных параметров стратегии",
    )

    # Источник данных
    p.add_argument("--pair", dest="pair", type=str, help="Пара, напр. DOGE_EUR")
    p.add_argument("--exmo-pair", dest="exmo_pair", type=str, help="Алиас для --pair")
    p.add_argument("--candles", dest="candles", type=str, default="1m:3000", help="TF:COUNT, напр. 1m:3000")
    p.add_argument("--exmo-candles", dest="exmo_candles", type=str, help="Алиас для --candles")
    p.add_argument("--resample", dest="resample", type=str, default="5m")

    # Параметры стратегии (минимальный супerset)
    p.add_argument("--strategy", dest="strategy", type=str, default="ema_adx_atr",
                   choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    p.add_argument("--ema-fast", dest="ema_fast", type=_int_arg, default=12)
    p.add_argument("--ema-slow", dest="ema_slow", type=_int_arg, default=21)
    p.add_argument("--adx-len", dest="adx_len", type=_int_arg, default=14)
    p.add_argument("--adx-on", dest="adx_on", type=_float_arg, default=23.0)
    p.add_argument("--adx-off", dest="adx_off", type=_float_arg, default=17.0)
    p.add_argument("--require-di", dest="require_di", action="store_true", default=False)
    p.add_argument("--atr-len", dest="atr_len", type=_int_arg, default=14)
    p.add_argument("--atr-mult", dest="atr_mult", type=_float_arg, default=3.0)

    # Торговые издержки/ограничения
    p.add_argument("--fee-bps", dest="fee_bps", type=_int_arg, default=10)
    p.add_argument("--slip-bps", dest="slip_bps", type=_int_arg, default=2)
    p.add_argument("--cooldown-bars", dest="cooldown_bars", type=_int_arg, default=5)
    p.add_argument("--hysteresis-bps", dest="hysteresis_bps", type=_int_arg, default=0)
    p.add_argument("--qty-eur", dest="qty_eur", type=_float_arg, default=100.0)
    p.add_argument("--max-daily-loss-bps", dest="max_daily_loss_bps", type=_int_arg, default=0)

    # Разбиение на фолды
    p.add_argument("--folds", dest="folds", type=_int_arg, default=4)
    p.add_argument("--wf-folds", dest="wf_folds", type=_int_arg, help="Синоним для --folds")
    p.add_argument("--wf-train-bars", dest="wf_train_bars", type=_int_arg, default=150)
    p.add_argument("--wf-valid-bars", dest="wf_valid_bars", type=_int_arg, default=100)

    # Вывод
    p.add_argument("--csv", dest="csv", type=str, help="Путь к CSV для результатов (по фолдам)")
    p.add_argument("--json", dest="json_out", type=str, help="Путь к JSON для полного ответа")

    p.set_defaults(_handler=_handle_walk_forward)
    return p


def _handle_walk_forward(args) -> Dict[str, Any]:
    pair = args.exmo_pair or args.pair
    if not pair:
        raise SystemExit("walk-forward: требуется указать --pair или --exmo-pair")

    candles = args.exmo_candles or args.candles or "1m:3000"
    resample = normalize_resample_rule(args.resample)

    cfg = WFConfig(
        pair=pair,
        span=candles,
        resample=resample,
        cache_dir=None,
        strategy=args.strategy,
        fast=args.ema_fast,
        slow=args.ema_slow,
        adx_len=args.adx_len,
        on=args.adx_on,
        off=args.adx_off,
        require_di=args.require_di,
        atr_len=args.atr_len,
        atr_mult=args.atr_mult,
        fee_bps=args.fee_bps,
        slip_bps=args.slip_bps,
        hysteresis_bps=args.hysteresis_bps,
        cooldown_bars=args.cooldown_bars,
        qty_eur=args.qty_eur,
        max_daily_loss_bps=args.max_daily_loss_bps,
        folds=(args.wf_folds or args.folds),
        min_train_bars=args.wf_train_bars,
        min_valid_bars=args.wf_valid_bars,
    )

    log.info("Command: walk-forward pair=%s span=%s resample=%s strategy=%s", pair, candles, resample, args.strategy)
    result = run_walk_forward(cfg)

    # CSV по фолдам
    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = result.get("oos", [])
        if rows:
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r.keys()}))
                w.writeheader()
                for r in rows:
                    w.writerow(r)
            log.info("[out] saved %s rows=%d", str(path), len(rows))
        else:
            log.warning("[out] no rows to write: %s", str(path))

    # Полный JSON-ответ (если нужен)
    if args.json_out:
        jpath = Path(args.json_out)
        jpath.parent.mkdir(parents=True, exist_ok=True)
        with jpath.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log.info("[out] saved %s", str(jpath))

    return result
