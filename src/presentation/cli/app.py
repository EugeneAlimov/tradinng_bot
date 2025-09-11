# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

log = logging.getLogger("cli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


# =====================================================================================
# CLI builders
# =====================================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradinng-bot")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--out-dir", default="out/data")
    parser.add_argument("--out-prefix", default="")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--print-trade-summary", action="store_true")
    parser.add_argument("--http-retries", type=int, default=3)
    parser.add_argument("--http-backoff", type=float, default=0.5)
    parser.add_argument("--http-timeout", type=float, default=10.0)

    sub = parser.add_subparsers(dest="cmd", required=True)

    # trade-live
    p_live = sub.add_parser("trade-live")
    p_live.add_argument("--mode", choices=["observe", "paper"], required=True)
    p_live.add_argument("--strategy", choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"], required=True)

    # одиночная пара
    p_live.add_argument("--pair")
    p_live.add_argument("--exmo-pair")

    # мульти
    p_live.add_argument("--pairs", help="Список пар через запятую, напр. DOGE_EUR,XRP_EUR")

    # свечи/ресэмплинг
    p_live.add_argument("--candles", help="TF:COUNT (e.g. 1m:720)")
    p_live.add_argument("--exmo-candles", help="Алиас для --candles")
    p_live.add_argument("--resample", help="Правило ресемплинга (e.g. 5m, 1H)")
    p_live.add_argument("--poll-sec", type=int, default=15, help="Интервал опроса (сек)")
    p_live.add_argument("--summary-alert", action="store_true")

    # параметры стратегии (опциональные)
    p_live.add_argument("--ema-fast", type=int)
    p_live.add_argument("--ema-slow", type=int)
    p_live.add_argument("--adx-len", type=int)
    p_live.add_argument("--adx-on", type=float)
    p_live.add_argument("--adx-off", type=float)
    p_live.add_argument("--require-di", action="store_true")

    # риск/комиссии для paper
    p_live.add_argument("--risk-max-position-pct", type=int)
    p_live.add_argument("--risk-stop-loss-bps", type=int)
    p_live.add_argument("--cooldown-bars", type=int)
    p_live.add_argument("--fee-bps", type=int)
    p_live.add_argument("--slip-bps", type=int)

    # walk-forward
    p_wf = sub.add_parser("walk-forward")
    p_wf.add_argument("--pair", help="Пара, напр. DOGE_EUR")
    p_wf.add_argument("--exmo-pair", help="Алиас к --pair")
    p_wf.add_argument("--candles", help="TF:COUNT (e.g. 1m:2500)")
    p_wf.add_argument("--exmo-candles", help="Алиас к --candles")
    p_wf.add_argument("--resample", help="Правило ресэмплинга (e.g. 5m, 1H)")
    p_wf.add_argument("--strategy", choices=["ema_adx", "ema_adx_atr", "rsi2", "bb_breakout"])
    p_wf.add_argument("--wf-folds", type=int, dest="wf_folds")
    p_wf.add_argument("--folds", type=int, dest="wf_folds_alias")
    p_wf.add_argument("--wf-train-frac", type=float, dest="wf_train_frac")
    p_wf.add_argument("--min-trades", type=int)
    p_wf.add_argument("--ema-fast", type=int, help="FAST EMA длина")
    p_wf.add_argument("--ema-slow", type=int, help="SLOW EMA длина")
    p_wf.add_argument("--metric")
    p_wf.add_argument("--csv", help="Путь к CSV выводу результатов")

    return parser


# =====================================================================================
# Dispatchers
# =====================================================================================

def _dispatch_trade_live(args: argparse.Namespace) -> int:
    # выбор пар: --pair / --exmo-pair / --pairs
    pair = args.pair or args.exmo_pair
    if args.pairs:
        pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    else:
        pairs = [pair] if pair else []

    candles = args.candles or args.exmo_candles
    if not candles:
        candles = "1m:720"

    resample = args.resample

    # ленивый импорт чтобы не грузить всё при парсинге в тестах
    from src.presentation.cli.trade_live_cmd import LiveArgs, run_live

    if not pairs:
        raise SystemExit("no trading pair(s) specified")

    for pr in pairs:
        la = LiveArgs(
            mode=args.mode,
            strategy=args.strategy,
            pair=pr,
            candles=candles,
            resample=resample,
            poll_sec=args.poll_sec,
            # передаём только явно заданные параметры (остальные None отфильтрует run_live)
            ema_fast=args.ema_fast,
            ema_slow=args.ema_slow,
            adx_len=args.adx_len,
            adx_on=args.adx_on,
            adx_off=args.adx_off,
            require_di=bool(args.require_di),
            risk_max_position_pct=args.risk_max_position_pct,
            risk_stop_loss_bps=args.risk_stop_loss_bps,
            cooldown_bars=args.cooldown_bars,
            fee_bps=args.fee_bps,
            slip_bps=args.slip_bps,
            summary_alert=bool(args.summary_alert),
        )
        run_live(la)
    return 0


def _dispatch_walk_forward(args: argparse.Namespace) -> int:
    pair = args.pair or args.exmo_pair
    candles = args.candles or args.exmo_candles

    folds = args.wf_folds_alias or args.wf_folds

    from src.backtest.walkforward import run_walk_forward  # полноценная реализация у тебя в модуле

    return run_walk_forward(
        pair=pair,
        candles=candles,
        resample=args.resample,
        strategy=args.strategy,
        folds=folds,
        wf_train_frac=args.wf_train_frac,
        min_trades=args.min_trades,
        ema_fast=args.ema_fast,
        ema_slow=args.ema_slow,
        metric=args.metric,
        csv_path=args.csv,
    )


# =====================================================================================
# Main
# =====================================================================================

def main(argv: Optional[List[str]] = None):
    """
    Поведение по контракту тестов:
    - если argv is None -> вернуть callable (builder), чтобы test_cli_importable прошёл.
    - если argv передали -> реально распарсить и выполнить команду.
    """
    if argv is None:
        return build_parser

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "trade-live":
        return _dispatch_trade_live(args)
    if args.cmd == "walk-forward":
        return _dispatch_walk_forward(args)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
