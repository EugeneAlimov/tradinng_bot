# src/backtest/report.py
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd


_HTML_CSS = """
<style>
body{font-family:Arial, sans-serif;margin:24px;max-width:1100px}
table{border-collapse:collapse;margin:12px 0}
td,th{border:1px solid #ddd;padding:6px}
h1{margin:0 0 8px 0}
h2{margin:20px 0 10px 0}
.note{color:#666;font-size:12px}
code{background:#f5f5f5;padding:2px 4px;border-radius:4px}
</style>
"""

def _df_head_html(df: Optional[pd.DataFrame], n: int = 20) -> str:
    if df is None or df.empty:
        return "<p class='note'>Нет данных.</p>"
    return df.head(n).to_html(border=1, classes="dataframe", float_format=lambda x: f"{x:.6f}")

def _png_from_equity(equity_csv: Optional[str]) -> Optional[str]:
    if not equity_csv:
        return None
    p = Path(equity_csv)
    if not p.exists():
        return None
    df = pd.read_csv(p)
    # ожидаем колонки: time, equity_eur
    time_col = None
    for c in df.columns:
        if c.lower().startswith("time"):
            time_col = c; break
    y_col = None
    for c in df.columns:
        if "equity" in c.lower():
            y_col = c; break
    if time_col is None or y_col is None:
        return None

    fig, ax = plt.subplots(figsize=(9, 3))
    ax.plot(pd.to_datetime(df[time_col]), df[y_col])
    ax.set_title("Final Backtest Equity")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("time")
    ax.set_ylabel(y_col)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"<img alt='equity' src='data:image/png;base64,{b64}'/>"

def save_optimize_report(
    out_html: str,
    *,
    sweep_csv: Optional[str] = None,
    ranked_csv: Optional[str] = None,
    wf_csv: Optional[str] = None,
    final_trades_csv: Optional[str] = None,
    final_equity_csv: Optional[str] = None,
) -> str:
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)

    sweep_df = pd.read_csv(sweep_csv) if sweep_csv and Path(sweep_csv).exists() else None
    ranked_df = pd.read_csv(ranked_csv) if ranked_csv and Path(ranked_csv).exists() else None
    wf_df = pd.read_csv(wf_csv) if wf_csv and Path(wf_csv).exists() else None
    trades_df = pd.read_csv(final_trades_csv) if final_trades_csv and Path(final_trades_csv).exists() else None
    eq_img = _png_from_equity(final_equity_csv)

    html = ["<html><head><meta charset='utf-8'><title>Optimize Report</title>", _HTML_CSS, "</head><body>"]
    html.append("<h1>Optimize Report</h1>")

    html.append("<h2>Sweep (head)</h2>")
    html.append(_df_head_html(sweep_df))

    html.append("<h2>Ranked by Robustness (head)</h2>")
    html.append(_df_head_html(ranked_df))

    html.append("<h2>Walk-Forward (top)</h2>")
    html.append(_df_head_html(wf_df))

    html.append("<h2>Final Backtest Equity</h2>")
    if eq_img:
        html.append(eq_img)
    else:
        html.append("<p class='note'>Нет графика equity (файл не найден).</p>")

    html.append("<h2>Final Trades (head)</h2>")
    html.append(_df_head_html(trades_df))

    html.append("</body></html>")
    out.write_text("".join(html), encoding="utf-8")
    return str(out)
