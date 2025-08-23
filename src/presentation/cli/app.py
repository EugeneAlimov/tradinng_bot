# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from typing import Optional

from src.presentation.live import run_live_observe  # если есть
from src.presentation.paper import run_live_paper    # если есть
from src.presentation.live_trade import run_live_trade

from src.backtest.vectorized_bt import BtConfig, run_backtest_vectorized
# Если у тебя есть старый backtest (simple_bt), можно оставить как fallback:
try:
    from src.backtest.simple_bt import run_backtest as run_backtest_legacy  # type: ignore
except Exception:
    run_backtest_legacy = None  # type: ignore


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("tradinng_bot cli")

    # режимы
    gmode = p.add_mutually_exclusive_group(required=True)
    gmode.add_argument("--backtest", action="store_true", help="Run backtest")
    gmode.add_argument("--live", choices=["observe", "paper", "trade"], help="Live mode")

    # рынок/данные
    p.add_argument("--exmo-pair", dest="pair", required=True, help="EXMO pair, e.g. DOGE_EUR")
    p.add_argument("--exmo-candles", dest="span", default="1m:1000", help="source candles span like 1m:1000")
    p.add_argument("--resample", dest="rule", default="5m", help="resample rule like 5m")

    # стратегия SMA
    p.add_argument("--fast", type=int, default=6)
    p.add_argument("--slow", type=int, default=25)
    p.add_argument("--hysteresis-bps", type=float, default=0.0)

    # риск/объемы
    p.add_argument("--qty-eur", type=float, default=0.0, help="fixed EUR size per entry (0=use position_pct)")
    p.add_argument("--position-pct", type=float, default=100.0, help="% of equity to use if qty-eur=0")
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slip-bps", type=float, default=2.0)
    p.add_argument("--cooldown-bars", type=int, default=0)
    p.add_argument("--max-daily-loss-bps", type=float, default=0.0)
    p.add_argument("--enter-on-start", action="store_true")

    # live specific
    p.add_argument("--poll-sec", type=int, default=15)
    p.add_argument("--heartbeat-sec", type=int, default=60)
    p.add_argument("--price-tick", type=float, default=0.0)
    p.add_argument("--qty-step", type=float, default=0.0)
    p.add_argument("--min-quote", type=float, default=0.0)
    p.add_argument("--confirm-live-trade", action="store_true")
    p.add_argument("--align-on-state", action="store_true")
    p.add_argument("--fok-wait-sec", type=float, default=1.0)
    p.add_argument("--reprice-attempts", type=int, default=0)
    p.add_argument("--reprice-step-bps", type=float, default=0.0)
    p.add_argument("--aggr-limit", action="store_true")
    p.add_argument("--aggr-ticks", type=int, default=0)
    p.add_argument("--force-entry", choices=["", "buy", "sell"], default="")
    p.add_argument("--start-eur", type=float, default=1000.0)

    # vectorized backtest switch
    p.add_argument("--vectorized", action="store_true", help="Use vectorized backtest engine")

    return p


def main(argv: Optional[list] = None) -> None:
    args = _arg_parser().parse_args(argv)

    pair = args.pair
    span = args.span
    rule = args.rule

    if args.backtest:
        if args.vectorized:
            cfg = BtConfig(
                pair=pair,
                span=span,
                resample_rule=rule,
                fast=int(args.fast),
                slow=int(args.slow),
                hysteresis_bps=float(args.hysteresis_bps),
                start_eur=float(args.start_eur),
                qty_eur=float(args.qty_eur),
                position_pct=float(args.position_pct),
                fee_bps=float(args.fee_bps),
                slip_bps=float(args.slip_bps),
                cooldown_bars=int(args.cooldown_bars),
                max_daily_loss_bps=float(args.max_daily_loss_bps),
                enter_on_start=bool(args.enter_on_start),
            )
            res = run_backtest_vectorized(cfg)
            m = res.metrics
            print("[bt-v] metrics:")
            for k in ["bars", "trades", "round_trips", "win_rate_pct",
                      "return_pct", "sharpe_like", "max_drawdown_pct",
                      "start_equity", "final_equity"]:
                print(f"  {k}: {m.get(k)}")
            print(f"[bt-v] trades -> {cfg.out_trades_csv}")
            print(f"[bt-v] equity -> {cfg.out_equity_csv}")
        else:
            if run_backtest_legacy is None:
                print("Legacy backtest is not available. Use --vectorized.", file=sys.stderr)
                sys.exit(2)
            # legacy path, keep previous signature as-is
            run_backtest_legacy(
                pair=pair, span=span, resample_rule=rule,
                fast=args.fast, slow=args.slow,
                hysteresis_bps=args.hysteresis_bps,
                fee_bps=args.fee_bps, slip_bps=args.slip_bps,
                start_eur=args.start_eur, qty_eur=args.qty_eur,
                position_pct=args.position_pct,
                cooldown_bars=args.cooldown_bars,
                max_daily_loss_bps=args.max_daily_loss_bps,
                enter_on_start=args.enter_on_start,
            )
        return

    # ---- LIVE MODES ----
    if args.live == "observe":
        run_live_observe(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec
        )
        return

    if args.live == "paper":
        run_live_paper(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec,
            start_eur=args.start_eur, qty_eur=args.qty_eur, position_pct=args.position_pct,
        )
        return

    if args.live == "trade":
        run_live_trade(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            start_eur=args.start_eur,
            qty_eur=args.qty_eur, position_pct=args.position_pct,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            price_tick=args.price_tick, qty_step=args.qty_step, min_quote=args.min_quote,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec,
            max_daily_loss_bps=args.max_daily_loss_bps,
            cooldown_bars=args.cooldown_bars,
            confirm_live_trade=args.confirm_live_trade,
            align_on_state=args.align_on_state,
            enter_on_start=args.enter_on_start,
            fok_wait_sec=args.fok_wait_sec,
            reprice_attempts=args.reprice_attempts,
            reprice_step_bps=args.reprice_step_bps,
            aggr_limit=args.aggr_limit,
            aggr_ticks=args.aggr_ticks,
            force_entry=args.force_entry,
            hysteresis_bps=args.hysteresis_bps,
        )
        return

    print("Unknown mode", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
