#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced metrics CLI

Adds:
- Clean JSON-serializable metrics export
- Optional equity, drawdown, PnL histogram plots
- Rich HTML report that embeds all plots (base64) and a small trades table

Usage examples:
python -m src.presentation.cli.metrics_cli \
  --trades-csv /tmp/trades.csv --initial-cash 10000 \
  --export-equity-png /tmp/equity.png \
  --export-drawdown-png /tmp/drawdown.png \
  --export-returns-png /tmp/returns.png \
  --export-metrics-json /tmp/metrics.json \
  --export-report /tmp/report.html
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# -------------------------------
# Utilities
# -------------------------------

def _to_py(obj):
    """Recursively convert numpy / pandas scalars to plain Python types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return type(obj)(_to_py(x) for x in obj)
    if isinstance(obj, dict):
        return {k: _to_py(v) for k, v in obj.items()}
    return obj


def _b64_png(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=160)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# -------------------------------
# Metrics
# -------------------------------

@dataclass
class Metrics:
    trades: int
    wins: int
    losses: int
    win_rate_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    net_pnl: float
    final_equity: float
    max_dd_abs: float
    max_dd_pct: float
    sharpe_per_trade: float
    sortino_per_trade: float
    expectancy: float
    avg_pnl: float
    median_pnl: float
    best_trade: float
    worst_trade: float
    avg_bars: float
    avg_hold_time_min: float
    exposure_pct: float
    max_consec_wins: int
    max_consec_losses: int

    def to_dict(self) -> Dict[str, float]:
        return _to_py(self.__dict__)


def _equity_and_dd(trades: pd.DataFrame, initial_cash: float) -> Tuple[pd.Series, pd.Series]:
    # equity is stepped at exits
    pnl = trades.set_index("exit_time")["pnl"].astype(float).sort_index()
    equity = pnl.cumsum() + float(initial_cash)
    # drawdown (absolute) vs running peak
    peak = equity.cummax()
    dd_abs = equity - peak
    return equity, dd_abs


def _consec_wins_losses(pnl: pd.Series) -> Tuple[int, int]:
    # +1 win, -1 loss, 0 flat
    s = pnl.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    max_w = max_l = cur = 0
    for v in s:
        if v > 0:
            cur = cur + 1 if cur > 0 else 1
        elif v < 0:
            cur = cur - 1 if cur < 0 else -1
        else:
            cur = 0
        max_w = max(max_w, cur if cur > 0 else 0)
        max_l = min(max_l, cur if cur < 0 else 0)
    return int(max_w), int(abs(max_l))


def compute_metrics(trades: pd.DataFrame, initial_cash: float) -> Metrics:
    t = trades.copy()
    t["pnl"] = t["pnl"].astype(float)

    trades_n = int(len(t))
    wins_n = int((t["pnl"] > 0).sum())
    losses_n = int((t["pnl"] < 0).sum())
    win_rate = float(wins_n / trades_n * 100.0) if trades_n else 0.0

    gross_profit = float(t.loc[t["pnl"] > 0, "pnl"].sum())
    gross_loss = float(abs(t.loc[t["pnl"] < 0, "pnl"].sum()))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

    net_pnl = float(t["pnl"].sum())
    equity, dd_abs = _equity_and_dd(t, initial_cash)
    final_equity = float(equity.iloc[-1]) if trades_n else float(initial_cash)

    dd_abs_min = float(dd_abs.min()) if not dd_abs.empty else 0.0
    peak = float((equity.cummax().iloc[-1] if trades_n else initial_cash))
    max_dd_pct = float(dd_abs_min / peak * 100.0) if peak else 0.0

    # per-trade returns (simple) for Sharpe/Sortino
    rets = t["pnl"]
    mean = float(rets.mean()) if trades_n else 0.0
    std = float(rets.std(ddof=1)) if trades_n > 1 else 0.0
    downside = float(rets[rets < 0].std(ddof=1)) if (rets < 0).sum() > 1 else 0.0
    sharpe = float(mean / std) if std > 0 else 0.0
    sortino = float(mean / downside) if downside > 0 else 0.0

    expectancy = float(mean)
    avg_pnl = float(mean)
    median_pnl = float(float(t["pnl"].median()) if trades_n else 0.0)
    best_trade = float(t["pnl"].max()) if trades_n else 0.0
    worst_trade = float(t["pnl"].min()) if trades_n else 0.0
    avg_bars = float(t["bars"].mean()) if "bars" in t.columns and trades_n else 0.0

    # hold time in minutes
    if "entry_time" in t.columns and "exit_time" in t.columns and trades_n:
        dur = (t["exit_time"] - t["entry_time"]).dt.total_seconds() / 60.0
        avg_hold_min = float(dur.mean())
        # exposure = total minutes in trades / span minutes
        span_min = float(
            (t["exit_time"].max() - t["entry_time"].min()).total_seconds() / 60.0
        )
        exposure = float(dur.sum() / span_min * 100.0) if span_min > 0 else 0.0
    else:
        avg_hold_min = 0.0
        exposure = 0.0

    max_w, max_l = _consec_wins_losses(t["pnl"]) if trades_n else (0, 0)

    return Metrics(
        trades=trades_n,
        wins=wins_n,
        losses=losses_n,
        win_rate_pct=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        net_pnl=net_pnl,
        final_equity=final_equity,
        max_dd_abs=dd_abs_min,  # negative number
        max_dd_pct=max_dd_pct,  # negative pct
        sharpe_per_trade=sharpe,
        sortino_per_trade=sortino,
        expectancy=expectancy,
        avg_pnl=avg_pnl,
        median_pnl=median_pnl,
        best_trade=best_trade,
        worst_trade=worst_trade,
        avg_bars=avg_bars,
        avg_hold_time_min=avg_hold_min,
        exposure_pct=exposure,
        max_consec_wins=max_w,
        max_consec_losses=max_l,
    )


# -------------------------------
# Plot helpers
# -------------------------------

def plot_equity(equity: pd.Series, out_png: Path | None = None) -> str | None:
    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.plot(equity.index, equity.values)
    ax.set_title("Equity curve (by exit)")
    ax.set_xlabel("time")
    ax.set_ylabel("equity")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.autofmt_xdate()
    if out_png:
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=160, bbox_inches="tight")
        return None
    return _b64_png(fig)


def plot_drawdown(dd_abs: pd.Series, out_png: Path | None = None) -> str | None:
    fig = plt.figure(figsize=(10, 3))
    ax = fig.add_subplot(111)
    ax.plot(dd_abs.index, dd_abs.values)
    ax.set_title("Drawdown (absolute)")
    ax.set_xlabel("time")
    ax.set_ylabel("drawdown")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.autofmt_xdate()
    if out_png:
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=160, bbox_inches="tight")
        return None
    return _b64_png(fig)


def plot_pnl_hist(pnl: pd.Series, out_png: Path | None = None) -> str | None:
    fig = plt.figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.hist(pnl.values, bins=20)
    ax.set_title("PnL distribution per trade")
    ax.set_xlabel("PnL")
    ax.set_ylabel("count")
    ax.grid(True, linestyle=":", alpha=0.3)
    if out_png:
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=160, bbox_inches="tight")
        return None
    return _b64_png(fig)


# -------------------------------
# HTML report
# -------------------------------

def _fmt_pct(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}%"


def _fmt_num(x: float, digits: int = 6) -> str:
    return f"{x:.{digits}f}"


def render_report(
        title: str,
        m: Metrics,
        png_equity_b64: str | None,
        png_drawdown_b64: str | None,
        png_hist_b64: str | None,
        trades: pd.DataFrame,
        out_html: Path,
):
    rows = []
    rows.append(("trades", m.trades))
    rows.append(("win rate", _fmt_pct(m.win_rate_pct)))
    rows.append(("net PnL", _fmt_num(m.net_pnl)))
    rows.append(("final equity", _fmt_num(m.final_equity)))
    rows.append(("profit factor", f"{m.profit_factor:.3f}"))
    rows.append(("max DD", f"{_fmt_pct(m.max_dd_pct, 2)}   (abs {_fmt_num(m.max_dd_abs)})"))
    rows.append(("Sharpe/Sortino per trade", f"{m.sharpe_per_trade:.3f} / {m.sortino_per_trade:.3f}"))
    rows.append(("exposure", _fmt_pct(m.exposure_pct)))
    rows.append(("best / worst trade", f"{_fmt_num(m.best_trade)} / {_fmt_num(m.worst_trade)}"))
    rows.append(("avg pnl / median pnl", f"{_fmt_num(m.avg_pnl)} / {_fmt_num(m.median_pnl)}"))
    rows.append(("avg bars / hold (min)", f"{_fmt_num(m.avg_bars, 2)} / {_fmt_num(m.avg_hold_time_min, 1)}"))
    rows.append(("max consec wins / losses", f"{m.max_consec_wins} / {m.max_consec_losses}"))

    # Small trades preview (first and last 5)
    preview_cols = [
        c
        for c in [
            "entry_time",
            "exit_time",
            "side",
            "entry",
            "exit",
            "pnl",
            "bars",
        ]
        if c in trades.columns
    ]
    preview = pd.concat([trades.head(5), trades.tail(5)], axis=0)
    preview_html = (
        preview[preview_cols]
        .copy()
        .to_html(index=False, border=0, classes="trades")
    )

    html = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8"/>',
        f"  <title>{title}</title>",
        "  <style>",
        "    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, 'Helvetica Neue', Arial, sans-serif; padding: 16px; }",
        "    table { border-collapse: collapse; margin-bottom: 24px; }",
        "    td,th { border: 1px solid #ddd; padding: 6px 10px }",
        "    th { background: #fafafa; text-align: left }",
        "    h1,h2 { margin: 12px 0 }",
        "    .wrap { display: grid; grid-template-columns: 1fr; gap: 24px; }",
        "    img { max-width: 100%; height: auto; border: 1px solid #eee; }",
        "    .trades { font-size: 12px; }",
        "  </style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        "<table>",
    ]
    for k, v in rows:
        html.append(f"<tr><th>{k}</th><td>{v}</td></tr>")
    html.append("</table>")

    # Plots
    if png_equity_b64:
        html.append("<h2>Equity</h2>")
        html.append(f'<img src="data:image/png;base64,{png_equity_b64}"/>')
    if png_drawdown_b64:
        html.append("<h2>Drawdown</h2>")
        html.append(f'<img src="data:image/png;base64,{png_drawdown_b64}"/>')
    if png_hist_b64:
        html.append("<h2>PnL distribution</h2>")
        html.append(f'<img src="data:image/png;base64,{png_hist_b64}"/>')

    # Trades preview
    html.append("<h2>Trades preview (first 5 & last 5)</h2>")
    html.append(preview_html)

    html.append("</body></html>")

    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("\n".join(html), encoding="utf-8")


# -------------------------------
# CLI
# -------------------------------

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute metrics from trades CSV and optionally export plots/report.")
    p.add_argument("--trades-csv", required=True, help="Path to trades.csv produced by paper_trade_cmd")
    p.add_argument("--initial-cash", type=float, required=True, help="Starting equity")

    # optional exports
    p.add_argument("--export-equity-png", type=str, default=None)
    p.add_argument("--export-drawdown-png", type=str, default=None)
    p.add_argument("--export-returns-png", type=str, default=None, help="Histogram of PnL per trade")
    p.add_argument("--export-metrics-json", type=str, default=None)
    p.add_argument("--export-report", type=str, default=None, help="Self-contained HTML report")
    p.add_argument("--report-title", type=str, default="Trade Report")

    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)

    trades_path = Path(args.trades_csv)
    if not trades_path.exists():
        raise SystemExit(f"Trades CSV not found: {trades_path}")

    df = pd.read_csv(trades_path)

    # Normalize timestamps
    for col in ("entry_time", "exit_time"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    m = compute_metrics(df, float(args.initial_cash))

    # Print quick console metrics
    print("=== METRICS ===")
    print(f"trades:\t\t{m.trades}")
    print(f"win rate:\t\t{m.win_rate_pct:.1f}%")
    print(f"net PnL:\t\t{m.net_pnl:.6f}")
    print(f"final equity:\t{m.final_equity:.6f}")
    print(f"profit factor:\t{m.profit_factor:.3f}")
    # For console, show positive dd as 0.00% (drawdown is negative number)
    dd_pct_disp = m.max_dd_pct if m.max_dd_pct < 0 else 0.0
    print(f"max DD:\t\t{dd_pct_disp:.2f}%   (abs {m.max_dd_abs:.6f})")
    print(
        f"Sharpe/Sortino per trade: {m.sharpe_per_trade:.3f} / {m.sortino_per_trade:.3f}"
    )
    print(f"exposure:\t\t{m.exposure_pct:.2f}%")
    print()

    # Plots (either save to files, or keep in-memory for the report)
    equity, dd_abs = _equity_and_dd(df, float(args.initial_cash))

    eq_b64 = dd_b64 = hist_b64 = None

    if args.export_equity_png:
        plot_equity(equity, Path(args.export_equity_png))
        print(f"Saved equity PNG: {args.export_equity_png}")
    else:
        eq_b64 = plot_equity(equity, None)

    if args.export_drawdown_png:
        plot_drawdown(dd_abs, Path(args.export_drawdown_png))
        print(f"Saved drawdown PNG: {args.export_drawdown_png}")
    else:
        dd_b64 = plot_drawdown(dd_abs, None)

    if args.export_returns_png:
        plot_pnl_hist(df["pnl"].astype(float), Path(args.export_returns_png))
        print(f"Saved returns PNG: {args.export_returns_png}")
    else:
        hist_b64 = plot_pnl_hist(df["pnl"].astype(float), None)

    if args.export_metrics_json:
        out_json = Path(args.export_metrics_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(m.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved metrics JSON: {args.export_metrics_json}")

    if args.export_report:
        # If any images were already saved to disk (user supplied paths), but we didn't get b64,
        # generate lightweight inline versions for the report so it's self-contained.
        if eq_b64 is None:
            eq_b64 = plot_equity(equity, None)
        if dd_b64 is None:
            dd_b64 = plot_drawdown(dd_abs, None)
        if hist_b64 is None:
            hist_b64 = plot_pnl_hist(df["pnl"].astype(float), None)

        render_report(
            title=args.report_title,
            m=m,
            png_equity_b64=eq_b64,
            png_drawdown_b64=dd_b64,
            png_hist_b64=hist_b64,
            trades=df,
            out_html=Path(args.export_report),
        )
        print(f"Saved report: {args.export_report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
