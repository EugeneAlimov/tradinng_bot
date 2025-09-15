# -*- coding: utf-8 -*-
"""
scripts/plot_trades_equity.py

Utility: take a CSV of paper-trade deals (as produced by --export-csv) and
produce (a) equity & drawdown PNG chart and (b) optional JSON with summary metrics.

Usage:
    python -m scripts.plot_trades_equity \
        --trades-csv /tmp/trades.csv --initial-cash 10000 \
        --out-png /tmp/equity.png --out-json /tmp/summary.json
"""
from __future__ import annotations

import argparse
import json
import pandas as pd


def _ensure_utc_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def _equity_curve(trades: pd.DataFrame, initial_cash: float) -> pd.Series:
    if trades.empty:
        return pd.Series([initial_cash])
    t = trades.copy()
    t["exit_time"] = _ensure_utc_series(t["exit_time"])
    t = t.sort_values("exit_time")
    eq = initial_cash + t["pnl"].astype(float).cumsum()
    eq.index = t["exit_time"]
    return eq


def _max_drawdown_from_equity(equity: pd.Series):
    if len(equity) == 0:
        return 0.0, 0.0
    peak = equity.cummax()
    dd = equity - peak
    max_dd_abs = float(dd.min())
    dd_pct = ((equity / peak) - 1.0).min()
    return max_dd_abs, float(dd_pct * 100.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades-csv", required=True)
    ap.add_argument("--initial-cash", type=float, default=0.0)
    ap.add_argument("--out-png")
    ap.add_argument("--out-json")
    args = ap.parse_args(argv)

    df = pd.read_csv(args.trades_csv)
    if not {"exit_time", "pnl"}.issubset(df.columns):
        raise SystemExit("CSV must contain exit_time and pnl columns (export with --export-csv).")

    eq = _equity_curve(df, args.initial_cash)
    max_dd_abs, max_dd_pct = _max_drawdown_from_equity(eq)

    summary = {
        "trades": int(len(df)),
        "net_pnl": float(df["pnl"].sum()),
        "final_equity": float(args.initial_cash + df["pnl"].sum()),
        "max_dd_abs": float(max_dd_abs),
        "max_dd_pct": float(max_dd_pct),
        "win_rate_pct": float((df["pnl"] > 0).mean() * 100.0) if len(df) else 0.0,
    }

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"Saved JSON: {args.out_json}")

    if args.out_png:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception as e:
            print(f"[warn] matplotlib not available: {e}")
        else:
            peak = eq.cummax()
            dd = eq - peak
            fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(10, 6), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1]})
            axes[0].plot(eq.index, eq.values, label="Equity")
            axes[0].plot(peak.index, peak.values, linestyle="--", linewidth=1, label="Equity Peak")
            axes[0].legend(loc="best")
            axes[0].set_ylabel("Equity")
            axes[1].plot(dd.index, dd.values, label="Drawdown")
            axes[1].legend(loc="best")
            axes[1].set_ylabel("Drawdown")
            axes[1].set_xlabel("Time (UTC)")
            fig.tight_layout()
            fig.savefig(args.out_png, dpi=120)
            plt.close(fig)
            print(f"Saved PNG: {args.out_png}")

    # short console summary
    print("Summary:", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
