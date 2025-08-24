# src/report/html_report.py
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import matplotlib.pyplot as plt


@dataclass
class ReportInputs:
    sweep_csv: Path
    ranked_csv: Path
    wf_csv: Path
    final_equity_csv: Optional[Path] = None
    final_trades_csv: Optional[Path] = None
    out_html: Path = Path("report.html")


def _img_tag_from_equity(csv_path: Path) -> str:
    try:
        df = pd.read_csv(csv_path)
        if "equity" not in df.columns:
            return ""
        plt.figure(figsize=(8, 3))
        plt.plot(df["equity"].values)
        plt.title(csv_path.name)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close()
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f'<img alt="equity" src="data:image/png;base64,{b64}"/>'
    except Exception:
        return ""


def render_report(inp: ReportInputs) -> None:
    sweep = pd.read_csv(inp.sweep_csv) if inp.sweep_csv and Path(inp.sweep_csv).exists() else None
    ranked = pd.read_csv(inp.ranked_csv) if inp.ranked_csv and Path(inp.ranked_csv).exists() else None
    wf = pd.read_csv(inp.wf_csv) if inp.wf_csv and Path(inp.wf_csv).exists() else None

    html_parts = ['<html><head><meta charset="utf-8"><title>Optimize Report</title>',
                  '<style>body{font-family:Arial, sans-serif;margin:24px;} table{border-collapse:collapse;}'
                  'td,th{border:1px solid #ddd;padding:6px;} h2{margin-top:28px;}</style></head><body>']

    html_parts.append("<h1>Optimize Report</h1>")

    if sweep is not None:
        html_parts.append("<h2>Sweep (head)</h2>")
        html_parts.append(sweep.head(20).to_html(index=False))

    if ranked is not None:
        html_parts.append("<h2>Ranked by Robustness (head)</h2>")
        html_parts.append(ranked.head(20).to_html(index=False))

    if wf is not None:
        html_parts.append("<h2>Walk-Forward (top)</h2>")
        html_parts.append(wf.sort_values(by=wf.columns.tolist(), axis=0).head(20).to_html(index=False))

    if inp.final_equity_csv and Path(inp.final_equity_csv).exists():
        html_parts.append("<h2>Final Backtest Equity</h2>")
        html_parts.append(_img_tag_from_equity(Path(inp.final_equity_csv)))

    if inp.final_trades_csv and Path(inp.final_trades_csv).exists():
        try:
            trades = pd.read_csv(inp.final_trades_csv)
            html_parts.append("<h2>Final Trades (head)</h2>")
            html_parts.append(trades.head(30).to_html(index=False))
        except Exception:
            pass

    html_parts.append("</body></html>")
    out = Path(inp.out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(html_parts), encoding="utf-8")
