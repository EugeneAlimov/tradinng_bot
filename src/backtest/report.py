from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Optional


def _box(title: str, body_html: str) -> str:
    return f"""
    <section style="margin:16px 0;padding:12px 16px;border:1px solid #ddd;border-radius:10px">
      <h2 style="margin-top:0">{html.escape(title)}</h2>
      {body_html}
    </section>
    """


def write_report_html(
    html_path: Path,
    sweep_csv: Path,
    ranked_csv: Path,
    wf_csv: Path,
    best_row: dict,
    final_metrics: Optional[dict],
) -> None:
    html_path = Path(html_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    best_pre = html.escape(json.dumps(best_row, ensure_ascii=False, indent=2))

    parts = []
    parts.append(_box("Artifacts",
                      f"<ul>"
                      f"<li>Sweep CSV: <code>{html.escape(str(sweep_csv))}</code></li>"
                      f"<li>Ranked CSV: <code>{html.escape(str(ranked_csv))}</code></li>"
                      f"<li>WF CSV: <code>{html.escape(str(wf_csv))}</code></li>"
                      f"</ul>"))

    parts.append(_box("Selected config", f"<pre>{best_pre}</pre>"))

    if final_metrics:
        fm_pre = html.escape(json.dumps(final_metrics, ensure_ascii=False, indent=2))
        parts.append(_box("Final backtest", f"<pre>{fm_pre}</pre>"))

    doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <title>Optimization report</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }}
      code, pre {{ background: #f8f8f8; border-radius: 6px; padding: 8px; display:block; overflow:auto; }}
      a {{ color: #0a58ca; text-decoration: none; }}
    </style>
  </head>
  <body>
    <h1>Optimization Report</h1>
    {''.join(parts)}
  </body>
</html>
"""
    html_path.write_text(doc, encoding="utf-8")
