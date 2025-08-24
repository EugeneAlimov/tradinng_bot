# src/report/html_report.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import base64
import io

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def _png_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _drawdown_series(equity: pd.Series) -> pd.Series:
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    return dd


@dataclass
class ReportInputs:
    sweep_csv: Optional[Path] = None
    ranked_csv: Optional[Path] = None
    wf_csv: Optional[Path] = None
    final_equity_csv: Optional[Path] = None
    final_trades_csv: Optional[Path] = None
    out_html: Path = Path("data/optimize/report.html")


def render_report(inp: ReportInputs) -> Path:
    inp.out_html.parent.mkdir(parents=True, exist_ok=True)

    # таблицы «по возможности»
    sweep = pd.read_csv(inp.sweep_csv) if inp.sweep_csv and Path(inp.sweep_csv).exists() else None
    ranked = pd.read_csv(inp.ranked_csv) if inp.ranked_csv and Path(inp.ranked_csv).exists() else None
    wf = pd.read_csv(inp.wf_csv) if inp.wf_csv and Path(inp.wf_csv).exists() else None
    equity = None
    if inp.final_equity_csv and Path(inp.final_equity_csv).exists():
        equity = pd.read_csv(inp.final_equity_csv, parse_dates=[0], index_col=0)["equity"]

    charts = {}

    if equity is not None and len(equity) > 0:
        # equity
        fig1 = plt.figure(figsize=(10, 4))
        plt.plot(equity.index, equity.values)
        plt.title("Final Backtest — Equity")
        plt.xlabel("Time"); plt.ylabel("Equity (EUR)")
        charts["equity"] = _png_base64(fig1)

        # drawdown
        dd = _drawdown_series(equity)
        fig2 = plt.figure(figsize=(10, 2.8))
        plt.plot(dd.index, dd.values)
        plt.title("Drawdown")
        plt.xlabel("Time"); plt.ylabel("DD")
        charts["drawdown"] = _png_base64(fig2)

    # html
    html = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>Optimize Report</title>",
            "<style>body{font-family:Inter,Arial,sans-serif;margin:24px;} h1{margin:0 0 12px;} ",
            "table{border-collapse:collapse;margin:12px 0;width:100%;} ",
            "th,td{border:1px solid #ddd;padding:6px 8px;font-size:13px;} ",
            "th{background:#f7f7f7;text-align:left;} ",
            ".section{margin:24px 0;} .img{margin:8px 0;} .grid{display:grid;grid-template-columns:1fr;gap:12px;} ",
            "</style></head><body>"]

    html.append("<h1>Optimization Report</h1>")

    if "equity" in charts:
        html.append("<div class='section'><h2>Final Equity</h2>")
        html.append(f"<img class='img' src='data:image/png;base64,{charts['equity']}'/>")
        html.append("</div>")

    if "drawdown" in charts:
        html.append("<div class='section'><h2>Drawdown</h2>")
        html.append(f"<img class='img' src='data:image/png;base64,{charts['drawdown']}'/>")
        html.append("</div>")

    def _tbl(df: pd.DataFrame, title: str, limit: int = 20):
        if df is None or df.empty:
            return
        sub = df.head(limit)
        html.append(f"<div class='section'><h2>{title}</h2><table><thead><tr>")
        for c in sub.columns:
            html.append(f"<th>{c}</th>")
        html.append("</tr></thead><tbody>")
        for _, row in sub.iterrows():
            html.append("<tr>")
            for c in sub.columns:
                val = row[c]
                html.append(f"<td>{val}</td>")
            html.append("</tr>")
        html.append("</tbody></table></div>")

    _tbl(sweep, "Sweep (top rows)")
    _tbl(ranked, "Robustness ranked (top rows)")
    _tbl(wf, "Walk-forward results (top rows)")

    html.append("</body></html>")
    Path(inp.out_html).write_text("\n".join(html), encoding="utf-8")
    return inp.out_html
