# src/presentation/cli/batch_report_cli.py
from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..utils.envtools import load_env_file


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _try_load_yaml(path: Path) -> Optional[dict]:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        return None
    try:
        import yaml  # type: ignore
    except Exception:
        print("[batch] PyYAML не установлен, читаю как JSON...", file=sys.stderr)
        return None
    with path.open("rt", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_config(path: Path) -> dict:
    if path.suffix.lower() in {".yml", ".yaml"}:
        y = _try_load_yaml(path)
        if y is not None:
            return y
    # по умолчанию — JSON
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _new_batch_dir(base: Path) -> Path:
    return _ensure_dir(base / f"batch-{utc_stamp()}")


def _as_list(x: Any) -> List[dict]:
    if isinstance(x, list):
        return x
    raise SystemExit("config.runs должен быть списком")


def _find_newest_run_dir(parent: Path, symbol: str, timeframe: str, strategy: str, run_id: str) -> Optional[Path]:
    # run_and_report создаёт подкаталог вида: {symbol}_{timeframe}_{strategy}--{run_id}-{ts}
    prefix = f"{symbol}_{timeframe}_{strategy}--{run_id}-"
    candidates = [d for d in parent.glob(prefix + "*") if d.is_dir()]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _read_metrics(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _html_escape(s: Any) -> str:
    import html
    return html.escape(str(s))


def _build_index_html(rows: List[dict], out_path: Path) -> None:
    # простая таблица со ссылками на отчёты
    head = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Batch reports</title>
<style>
body{font:14px/1.35 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding:20px;}
table{border-collapse:collapse; width:100%;}
th,td{border:1px solid #ddd; padding:6px 8px; text-align:left; white-space:nowrap;}
th{background:#fafafa;}
code{background:#f3f3f3; padding:1px 4px; border-radius:4px;}
small{color:#666;}
</style>
</head><body>
<h2>Batch reports</h2>
<table>
<thead>
<tr>
  <th>symbol</th><th>timeframe</th><th>strategy</th><th>run_id</th>
  <th>trades</th><th>net PnL</th><th>final equity</th><th>max DD %</th>
  <th>report</th><th>equity</th><th>drawdown</th><th>returns</th>
</tr>
</thead><tbody>
"""
    parts = [head]
    for r in rows:
        sym = _html_escape(r.get("symbol"))
        tf = _html_escape(r.get("timeframe"))
        strat = _html_escape(r.get("strategy"))
        run_id = _html_escape(r.get("run_id"))
        trades = r.get("trades", 0)
        net_pnl = r.get("net_pnl", 0.0)
        final_eq = r.get("final_equity", "")
        max_dd_pct = r.get("max_dd_pct", "")
        rep = r.get("report_rel", "")
        eq = r.get("equity_rel", "")
        dd = r.get("dd_rel", "")
        ret = r.get("ret_rel", "")

        parts.append(
            f"<tr>"
            f"<td>{sym}</td><td>{tf}</td><td>{strat}</td><td><code>{run_id}</code></td>"
            f"<td>{trades}</td><td>{net_pnl:.6f}</td><td>{final_eq if final_eq == '' else f'{final_eq:.6f}'}</td>"
            f"<td>{max_dd_pct if max_dd_pct == '' else f'{max_dd_pct:.2f}%'}</td>"
            f"<td>{f'<a href=\"{rep}\">report</a>' if rep else ''}</td>"
            f"<td>{f'<a href=\"{eq}\">png</a>' if eq else ''}</td>"
            f"<td>{f'<a href=\"{dd}\">png</a>' if dd else ''}</td>"
            f"<td>{f'<a href=\"{ret}\">png</a>' if ret else ''}</td>"
            f"</tr>\n"
        )
    parts.append("</tbody></table>\n</body></html>")
    out_path.write_text("".join(parts), encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tb-batch",
        description="Batch runner: multiple run_and_report executions from JSON/YAML config."
    )
    p.add_argument("--config", required=True, help="Path to .json or .yaml with runs")
    p.add_argument("--outdir", default="reports", help="Base output folder (default: reports)")
    # Глобальные дефолты (могут быть перекрыты в конфиге/в run)
    p.add_argument("--notify-telegram", action="store_true",
                   help="Default: notify for all runs (can be overridden in config)")
    p.add_argument("--tg-token", default=None, help="Override TELEGRAM_TOKEN/TELEGRAM_BOT_TOKEN")
    p.add_argument("--tg-chat", default=None, help="Override TELEGRAM_CHAT_ID")
    return p


def main(argv: List[str] | None = None) -> int:
    load_env_file(".env", override=False)

    ap = build_arg_parser()
    args = ap.parse_args(argv)

    cfg = _load_config(Path(args.config))
    base_out = _ensure_dir(Path(args.outdir))
    batch_root = _new_batch_dir(base_out)

    # Конфиг-уровень дефолтов
    db_url = cfg.get("db") or os.getenv("TB_STORE_URL") or "sqlite:///data/bot.db"
    defaults = cfg.get("defaults", {}) if isinstance(cfg.get("defaults", {}), dict) else {}

    # финальные «общие» дефолты
    common = {
        "timeframe": defaults.get("timeframe"),
        "fee_bps": float(defaults.get("fee_bps", 0.0)),
        "slip_bps": float(defaults.get("slip_bps", 0.0)),
        "initial_cash": float(defaults.get("initial_cash", 10_000.0)),
        "fill_mode": defaults.get("fill_mode", "next_open"),
        "entry_lag": int(defaults.get("entry_lag", 0)),
        "notify_telegram": bool(defaults.get("notify_telegram", args.notify_telegram)),
        "tg_attach_csv": bool(defaults.get("tg_attach_csv", False)),
        "tg_attach_report": bool(defaults.get("tg_attach_report", False)),
    }

    tg_token = args.tg_token or defaults.get("tg_token")
    tg_chat = args.tg_chat or defaults.get("tg_chat")

    runs = _as_list(cfg.get("runs"))
    summary_rows: List[dict] = []

    for i, r in enumerate(runs, 1):
        symbol = r["symbol"]
        timeframe = r.get("timeframe", common["timeframe"])
        strategy = r["strategy"]
        run_id = r.get("run_id") or f"run-{utc_stamp()}"

        fee_bps = float(r.get("fee_bps", common["fee_bps"]))
        slip_bps = float(r.get("slip_bps", common["slip_bps"]))
        initial_cash = float(r.get("initial_cash", common["initial_cash"]))
        fill_mode = r.get("fill_mode", common["fill_mode"])
        entry_lag = int(r.get("entry_lag", common["entry_lag"]))
        notify = bool(r.get("notify_telegram", common["notify_telegram"]))
        attach_csv = bool(r.get("tg_attach_csv", common["tg_attach_csv"]))
        attach_report = bool(r.get("tg_attach_report", common["tg_attach_report"]))

        # Собираем команду к нашему run_and_report, направляя аутпуты в batch_root
        cmd = [
            sys.executable, "-m", "src.presentation.cli.run_and_report",
            "--db", db_url,
            "--symbol", symbol, "--timeframe", timeframe, "--strategy", strategy,
            "--run-id", run_id,
            "--fee-bps", str(fee_bps), "--slip-bps", str(slip_bps),
            "--initial-cash", str(initial_cash),
            "--fill-mode", fill_mode,
            "--entry-lag", str(entry_lag),
            "--outdir", str(batch_root),
        ]
        if notify:
            cmd.append("--notify-telegram")
        if attach_csv:
            cmd.append("--tg-attach-csv")
        if attach_report:
            cmd.append("--tg-attach-report")
        if tg_token:
            cmd += ["--tg-token", str(tg_token)]
        if tg_chat:
            cmd += ["--tg-chat", str(tg_chat)]

        print(f"\n[{i}/{len(runs)}] $", " ".join(cmd))
        subprocess.run(cmd, check=False)

        # находим свежесозданную директорию этого ран-отчёта
        run_dir = _find_newest_run_dir(batch_root, symbol, timeframe, strategy, run_id)
        if not run_dir:
            print(f"[batch] не удалось найти каталог отчёта для {symbol} {timeframe} {strategy} run_id={run_id}",
                  file=sys.stderr)
            continue

        # читаем метрики
        m = _read_metrics(run_dir / "metrics.json")
        row = {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": strategy,
            "run_id": run_id,
            "trades": m.get("trades", 0),
            "net_pnl": m.get("net_pnl", 0.0),
            "final_equity": m.get("final_equity", ""),
            "max_dd_pct": m.get("max_dd_pct", ""),
            # относительные пути для удобного открытия из index.html
            "report_rel": str((run_dir / "report.html").relative_to(batch_root)) if (
                        run_dir / "report.html").exists() else "",
            "equity_rel": str((run_dir / "equity.png").relative_to(batch_root)) if (
                        run_dir / "equity.png").exists() else "",
            "dd_rel": str((run_dir / "drawdown.png").relative_to(batch_root)) if (
                        run_dir / "drawdown.png").exists() else "",
            "ret_rel": str((run_dir / "returns.png").relative_to(batch_root)) if (
                        run_dir / "returns.png").exists() else "",
        }
        summary_rows.append(row)

    # Собираем индекс
    index_html = batch_root / "index.html"
    _build_index_html(summary_rows, index_html)
    print(f"\nBatch index: {index_html}")
    print(f"Batch folder: {batch_root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
