#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI для EXMO SMA-бота/бэктестера.
"""

from __future__ import annotations
import argparse, json, os, sys
from typing import Any, Dict

import pandas as pd

# ——— Импорты, устойчивые к разным способам запуска ———
try:
    # запуск как пакет: python -m src.presentation.cli.app
    from ...integrations.exmo import fetch_exmo_candles, resample_ohlcv
    from ...core.backtest import run_backtest_sma
    from ...analysis.optimize import (
        optimize_sma_grid, optimize_sma_grid_oos,
        walk_forward_sma, optimize_risk_grid,
    )
    from ...plot.plots import plot_ohlc_with_volume, plot_equity, plot_sma_heatmap
except Exception:
    # запуск из корня проекта: python main.py
    from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv
    from src.core.backtest import run_backtest_sma
    from src.analysis.optimize import (
        optimize_sma_grid, optimize_sma_grid_oos,
        walk_forward_sma, optimize_risk_grid,
    )
    from src.plot.plots import plot_ohlc_with_volume, plot_equity, plot_sma_heatmap


def _format_pf_for_console(pf: Any) -> str:
    if isinstance(pf, str) and pf.lower() == "inf":
        return "∞"
    try:
        return f"{float(pf):.2f}"
    except Exception:
        return str(pf)


def print_bt_summary(report: Dict[str, Any]) -> None:
    m = report.get("metrics", {})
    pf_str = _format_pf_for_console(m.get("profit_factor", 0))
    print(
        f"[bt] equity={m.get('end', 0):.6f}  "
        f"trades={int(m.get('trades', 0))}  "
        f"win_rate={m.get('win_rate', 0):.2f}%  "
        f"pf={pf_str}  "
        f"dd={m.get('max_drawdown', 0) * 100:.2f}%  "
        f"sharpe={m.get('sharpe', 0):.2f}"
    )


def main():
    p = argparse.ArgumentParser(description="EXMO SMA bot / backtester")
    p.add_argument("--exmo-pair", default="DOGE_EUR")
    p.add_argument("--exmo-candles", default="1m:600")
    p.add_argument("--resample", default="")
    p.add_argument("--backtest", action="store_true")
    p.add_argument("--fast", type=int, default=10)
    p.add_argument("--slow", type=int, default=30)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slip-bps", type=float, default=2.0)
    p.add_argument("--start-eur", type=float, default=1000.0)
    p.add_argument("--qty-eur", type=float, default=200.0)
    p.add_argument("--warmup-bars", type=int, default=0)
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--atr-mult", type=float, default=0.0)
    p.add_argument("--tp-bps", type=float, default=0.0)
    p.add_argument("--position-pct", type=float, default=0.0)
    p.add_argument("--price-tick", type=float, default=0.0)
    p.add_argument("--qty-step", type=float, default=0.0)
    p.add_argument("--min-quote", type=float, default=0.0)
    p.add_argument("--risk-pct", type=float, default=0.0)
    p.add_argument("--atr-pctl-min", type=float, default=None)
    p.add_argument("--atr-pctl-max", type=float, default=None)

    # выводы/плоты
    p.add_argument("--save-trades", default="")
    p.add_argument("--save-equity", default="")
    p.add_argument("--save-report", default="")
    p.add_argument("--exmo-plot", default="")
    p.add_argument("--plot-equity", default="")
    p.add_argument("--plot-signals", action="store_true")

    # оптимизации/оценки
    p.add_argument("--optimize-sma", action="store_true")
    p.add_argument("--fast-range", default="5:30:1")
    p.add_argument("--slow-range", default="20:120:5")
    p.add_argument("--optimize-out", default="data/sma_grid.csv")
    p.add_argument("--heatmap-out", default="data/sma_heatmap.png")
    p.add_argument("--heatmap-metric", choices=["sharpe", "end", "total_pnl"], default="sharpe")

    p.add_argument("--oos-split", type=float, default=0.0)
    p.add_argument("--oos-out", default="")

    p.add_argument("--walkforward", action="store_true")
    p.add_argument("--wf-window", type=int, default=2000)
    p.add_argument("--wf-step", type=int, default=500)
    p.add_argument("--wf-out", default="data/walkforward.csv")

    p.add_argument("--optimize-risk", action="store_true")
    p.add_argument("--atr-range", default="0.0:3.0:0.5")
    p.add_argument("--tp-range", default="0:120:10")
    p.add_argument("--risk-out", default="data/risk_grid.csv")

    # дневной риск и «перерыв» (общие, подходят и для live paper)
    p.add_argument("--max-daily-loss-bps", type=float, default=0.0,
                   help="Max daily loss (in basis points) to flatten and pause, e.g. 50 = -0.50%.")
    p.add_argument("--cooldown-bars", type=int, default=0,
                   help="Bars to pause after daily loss guard triggers (on the resampled TF).")
    p.add_argument("--align-on-state", action="store_true",
                   help="Align position to SMA regime on every bar (enter if fast>slow, exit if fast<slow).")
    p.add_argument("--enter-on-start", action="store_true",
                   help="On first processed bar, align position to regime once.")
    # ---- LIVE mods ----
    p.add_argument("--live", choices=["observe", "paper", "trade"], default="")
    p.add_argument("--poll-sec", type=int, default=0)
    p.add_argument("--live-log", default="")
    p.add_argument("--heartbeat-sec", type=int, default=0)
    p.add_argument("--align-on-state", action="store_true")
    p.add_argument("--enter-on-start", action="store_true")
    # дневной риск/перерыв (общие с paper)
    p.add_argument("--max-daily-loss-bps", type=float, default=0.0)
    p.add_argument("--cooldown-bars", type=int, default=0)
    # trade safety + ключи
    p.add_argument("--confirm-live-trade", action="store_true",
                   help="Required to actually place real orders.")
    p.add_argument("--exmo-key", default="", help="EXMO API key (optional, prefer env EXMO_KEY)")
    p.add_argument("--exmo-secret", default="", help="EXMO API secret (optional, prefer env EXMO_SECRET)")
    # --------------------------------------------

    args = p.parse_args()

    # 1) данные
    df = fetch_exmo_candles(args.exmo_pair, args.exmo_candles)
    if args.resample:
        df = resample_ohlcv(df, args.resample)

    # LIVE OBSERVE
    # ---- LIVE dispatcher ----
    if args.live == "observe":
        try:
            from ..live import run_live_observe
        except Exception:
            from src.presentation.live import run_live_observe
        run_live_observe(
            pair=args.exmo_pair, span=args.exmo_candles, resample_rule=args.resample,
            fast=args.fast, slow=args.slow, poll_sec=args.poll_sec or None,
            log_csv=args.live_log, heartbeat_sec=args.heartbeat_sec
        )
        return

    if args.live == "paper":
        try:
            from ..paper import run_live_paper
        except Exception:
            from src.presentation.paper import run_live_paper
        run_live_paper(
            pair=args.exmo_pair, span=args.exmo_candles, resample_rule=args.resample,
            fast=args.fast, slow=args.slow,
            start_eur=args.start_eur, qty_eur=args.qty_eur, position_pct=args.position_pct,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            price_tick=args.price_tick, qty_step=args.qty_step, min_quote=args.min_quote,
            poll_sec=args.poll_sec or None, heartbeat_sec=args.heartbeat_sec,
            max_daily_loss_bps=args.max_daily_loss_bps, cooldown_bars=args.cooldown_bars,
            align_on_state=args.align_on_state, enter_on_start=args.enter_on_start,
        )
        return

    if args.live == "trade":
        try:
            from ..trade import run_live_trade
        except Exception:
            from src.presentation.trade import run_live_trade
        run_live_trade(
            pair=args.exmo_pair, span=args.exmo_candles, resample_rule=args.resample,
            fast=args.fast, slow=args.slow,
            start_eur=args.start_eur, qty_eur=args.qty_eur, position_pct=args.position_pct,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            price_tick=args.price_tick, qty_step=args.qty_step, min_quote=args.min_quote,
            poll_sec=args.poll_sec or None, heartbeat_sec=args.heartbeat_sec,
            max_daily_loss_bps=args.max_daily_loss_bps, cooldown_bars=args.cooldown_bars,
            confirm_live_trade=args.confirm_live_trade,
            align_on_state=args.align_on_state, enter_on_start=args.enter_on_start,
            api_key=args.exmo_key, api_secret=args.exmo_secret,
        )
        return
    # -------------------------

    # 2) режимы оптимизаций/оценок
    if args.optimize_sma:
        grid = optimize_sma_grid(
            df,
            fast_range=args.fast_range, slow_range=args.slow_range,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            start_eur=args.start_eur, qty_eur=args.qty_eur,
            out_csv=args.optimize_out, warmup_bars=args.warmup_bars,
        )
        print(f"→ Grid CSV saved to: {args.optimize_out}")
        if args.heatmap_out:
            plot_sma_heatmap(grid, metric=args.heatmap_metric, out_png=args.heatmap_out,
                             title=f"SMA {args.exmo_pair} ({args.heatmap_metric})")
            print(f"→ Heatmap saved to: {args.heatmap_out}")
        return

    if args.oos_split and args.oos_split > 0.0:
        oos = optimize_sma_grid_oos(
            df,
            fast_range=args.fast_range, slow_range=args.slow_range,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            start_eur=args.start_eur, qty_eur=args.qty_eur,
            metric=args.heatmap_metric, train_ratio=args.oos_split,
            warmup_bars=args.warmup_bars,
        )
        best, tm = oos["best"], oos["test_metrics"]
        pf_str = _format_pf_for_console(tm.get("profit_factor", 0))
        print(f"[oos] train_ratio={args.oos_split:.2f}  best=({best['fast']},{best['slow']}) "
              f"train_{args.heatmap_metric}={best['metric_train']:.4f}  "
              f"test_end={tm.get('end', 0):.6f}  pnl={tm.get('total_pnl', 0):.6f}  "
              f"pf={pf_str}  dd={tm.get('max_drawdown', 0) * 100:.2f}%  sharpe={tm.get('sharpe', 0):.2f}")
        if args.oos_out:
            os.makedirs(os.path.dirname(args.oos_out), exist_ok=True)
            with open(args.oos_out, "w") as f:
                json.dump(oos, f, indent=2, ensure_ascii=False)
            print(f"→ OOS JSON saved to: {args.oos_out}")
        return

    if args.walkforward:
        wf = walk_forward_sma(
            df,
            fast_range=args.fast_range, slow_range=args.slow_range,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            start_eur=args.start_eur, qty_eur=args.qty_eur,
            window_bars=args.wf_window, step_bars=args.wf_step,
            metric=args.heatmap_metric, warmup_bars=args.warmup_bars,
        )
        os.makedirs(os.path.dirname(args.wf_out), exist_ok=True)
        wf.to_csv(args.wf_out, index=False)
        print(f"→ Walk-forward CSV saved to: {args.wf_out}")
        return

    if args.optimize_risk:
        rg = optimize_risk_grid(
            df, fast=args.fast, slow=args.slow,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            start_eur=args.start_eur, qty_eur=args.qty_eur,
            atr_range=args.atr_range, tp_range=args.tp_range,
            metric=args.heatmap_metric, warmup_bars=args.warmup_bars,
        )
        os.makedirs(os.path.dirname(args.risk_out), exist_ok=True)
        rg.to_csv(args.risk_out, index=False)
        print(f"→ Risk grid CSV saved to: {args.risk_out}")
        key = args.heatmap_metric
        rg[key] = pd.to_numeric(rg[key], errors="coerce")
        top = rg.sort_values(key, ascending=False).head(5)
        print("[risk-grid top5]")
        for _, r in top.iterrows():
            pf_str = _format_pf_for_console(r.get("pf", 0))
            print(f"  atr_mult={r['atr_mult']}, tp_bps={int(r['tp_bps'])}, "
                  f"{key}={r[key]:.4f}, pf={pf_str}, dd={float(r['dd']) * 100:.2f}%, trades={int(r['trades'])}")
        return

    # 3) обычный бэктест
    trades_df = pd.DataFrame();
    equity_df = pd.DataFrame();
    report: Dict[str, Any] = {}
    if args.backtest:
        trades_df, equity_df, report = run_backtest_sma(
            df, fast=args.fast, slow=args.slow,
            start_eur=args.start_eur, qty_eur=args.qty_eur,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            warmup_bars=args.warmup_bars,
            atr_period=args.atr_period, atr_mult=args.atr_mult, tp_bps=int(args.tp_bps),
            position_pct=args.position_pct,
            price_tick=args.price_tick, qty_step=args.qty_step, min_quote=args.min_quote,
            risk_pct=args.risk_pct, atr_pctl_min=args.atr_pctl_min, atr_pctl_max=args.atr_pctl_max,
        )
        print_bt_summary(report)

    # графики
    if args.exmo_plot and not df.empty:
        first = df["time"].iloc[0].isoformat();
        last = df["time"].iloc[-1].isoformat()
        print(f"[plot] OHLC: points={len(df)}  first={first}  last={last}")
        plot_ohlc_with_volume(
            df, args.exmo_plot,
            f"EXMO candles {args.exmo_pair} {args.resample or args.exmo_candles}",
            sma_overlay=(args.fast, args.slow) if args.plot_signals else None,
            trades_df=trades_df if (args.plot_signals and not trades_df.empty) else None
        )
        print(f"→ Chart saved to: {args.exmo_plot}")

    if args.plot_equity and not equity_df.empty:
        plot_equity(equity_df, args.plot_equity)
        print(f"→ Equity chart saved to: {args.plot_equity}")

    # сохранения
    if args.save_trades and not trades_df.empty:
        os.makedirs(os.path.dirname(args.save_trades), exist_ok=True)
        trades_df.to_csv(args.save_trades, index=False)
        print(f"→ Trades CSV saved to: {args.save_trades}")

    if args.save_equity and not equity_df.empty:
        os.makedirs(os.path.dirname(args.save_equity), exist_ok=True)
        equity_df.to_csv(args.save_equity, index=False)
        print(f"→ Equity CSV saved to: {args.save_equity}")

    if args.save_report and report:
        os.makedirs(os.path.dirname(args.save_report), exist_ok=True)
        with open(args.save_report, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        # ещё раз — короткая сводка
        print_bt_summary(report)
        print(f"EXMO candles[{args.exmo_pair}] rows={len(df)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if os.environ.get("EXMO_DEBUG", "0").lower() in ("1", "true", "yes"):
            import traceback;

            traceback.print_exc()
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
