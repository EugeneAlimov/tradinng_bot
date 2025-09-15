# src/presentation/cli/run_and_report.py
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
import html  # для безопасного экранирования в HTML

from ..utils.envtools import load_env_file
from ..utils.telegram_notify import client_from_env, get_chat_id_from_env


def utc_stamp() -> str:
    # TZ-aware UTC
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def build_outdir(symbol: str, timeframe: str, strategy: str, run_id: str, base: str = "reports") -> Path:
    name = f"{symbol}_{timeframe}_{strategy}--{run_id}-{utc_stamp()}"
    p = Path(base) / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_paper_trade(db_url: str,
                    symbol: str,
                    timeframe: str,
                    strategy: str,
                    run_id: str,
                    outdir: Path,
                    fill_mode: str = "next_open",
                    entry_lag: int = 0,
                    fee_bps: float = 0.0,
                    slip_bps: float = 0.0,
                    initial_cash: float = 10_000.0) -> Path:
    trades_csv = outdir / "trades.csv"
    cmd = [
        sys.executable, "-m", "src.presentation.cli.paper_trade_cmd",
        "--db", db_url,
        "--symbol", symbol, "--timeframe", timeframe, "--strategy", strategy,
        "--run-id", run_id,
        "--fill-mode", fill_mode,
        "--entry-lag", str(entry_lag),
        "--fee-bps", str(fee_bps),
        "--slip-bps", str(slip_bps),
        "--initial-cash", str(initial_cash),
        "--export-csv", str(trades_csv),
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=False)
    return trades_csv


def run_metrics(trades_csv: Path, initial_cash: float, outdir: Path) -> Path:
    equity_png = outdir / "equity.png"
    dd_png = outdir / "drawdown.png"
    ret_png = outdir / "returns.png"
    metrics_json = outdir / "metrics.json"
    report_html = outdir / "report.html"

    cmd = [
        sys.executable, "-m", "src.presentation.cli.metrics_cli",
        "--trades-csv", str(trades_csv),
        "--initial-cash", str(initial_cash),
        "--export-equity-png", str(equity_png),
        "--export-drawdown-png", str(dd_png),
        "--export-returns-png", str(ret_png),
        "--export-metrics-json", str(metrics_json),
        "--export-report", str(report_html),
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=False)
    return metrics_json


def _read_metrics(metrics_json: Path) -> dict:
    if not metrics_json.exists():
        return {}
    try:
        return json.loads(metrics_json.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _summary_text_html(symbol: str, timeframe: str, strategy: str, run_id: str, m: dict) -> str:
    e = html.escape

    trades = m.get("trades", 0)
    net_pnl = m.get("net_pnl", 0.0)
    final_eq = m.get("final_equity")
    max_dd_pct = m.get("max_dd_pct")
    max_dd_abs = m.get("max_dd_abs")
    wr = m.get("win_rate_pct")

    lines = [
        f"📊 Report for <b>{e(symbol)} {e(timeframe)}</b> — <b>{e(strategy)}</b>",
        f"run_id: <code>{e(str(run_id))}</code>",
        f"trades: <b>{trades}</b>",
        f"net PnL: <b>{net_pnl:.6f}</b>",
    ]
    if final_eq is not None:
        lines.append(f"final equity: <b>{final_eq:.6f}</b>")
    if max_dd_pct is not None and max_dd_abs is not None:
        lines.append(f"max DD: <b>{max_dd_pct:.2f}%</b> (abs {max_dd_abs:.6f})")
    if wr is not None:
        lines.append(f"win rate: <b>{wr:.1f}%</b>")
    return "\n".join(lines)


def maybe_notify_telegram(do_notify: bool,
                          tg_token: str | None,
                          tg_chat: str | None,
                          outdir: Path,
                          summary_text_html: str,
                          attach_csv: bool,
                          attach_report: bool) -> None:
    if not do_notify:
        return

    client = client_from_env(tg_token)
    chat_id = tg_chat or get_chat_id_from_env()
    if not client or not chat_id:
        print("[telegram] telegram helpers not available or no token/chat; skip")
        return

    me = client.get_me()
    if not me.get("ok"):
        print("[telegram] getMe failed:", me)
    else:
        bot = me.get("result", {}).get("username") or me.get("result", {}).get("first_name")
        print(f"[telegram] bot @{bot} ready")

    # 1) безопасный HTML
    r1 = client.send_message(chat_id, summary_text_html, parse_mode="HTML")
    print("[telegram] message:", r1)

    # 2) картинки (без parse_mode)
    for name in ("equity.png", "drawdown.png", "returns.png"):
        p = outdir / name
        if p.exists():
            r = client.send_photo(chat_id, str(p), caption=name)
            print(f"[telegram] photo {name}:", r)

    # 3) документы (опционально)
    if attach_csv:
        csvp = outdir / "trades.csv"
        if csvp.exists():
            r = client.send_document(chat_id, str(csvp), caption="trades.csv")
            print("[telegram] document trades.csv:", r)
    if attach_report:
        rp = outdir / "report.html"
        if rp.exists():
            r = client.send_document(chat_id, str(rp), caption="report.html")
            print("[telegram] document report.html:", r)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tb-run-and-report",
                                description="Run paper trade + metrics + (optional) Telegram notify")
    p.add_argument("--db", required=True, help="DB URL, e.g. sqlite:///data/bot.db")

    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True)
    p.add_argument("--strategy", required=True)
    p.add_argument("--run-id", required=False, default=None, help="Run id to use")
    p.add_argument("--auto-run-id", action="store_true",
                   help="If specified and run-id has no trades, fallback to latest available run id")

    p.add_argument("--fee-bps", type=float, default=0.0)
    p.add_argument("--slip-bps", type=float, default=0.0)
    p.add_argument("--initial-cash", type=float, default=10_000.0)

    p.add_argument("--fill-mode", default="next_open", choices=["next_open", "signal"])
    p.add_argument("--entry-lag", type=int, default=0)

    p.add_argument("--outdir", default="reports")

    p.add_argument("--notify-telegram", action="store_true", help="Send message + images to Telegram")

    p.add_argument("--tg-token", default=None, help="Override TELEGRAM_TOKEN/TELEGRAM_BOT_TOKEN")
    p.add_argument("--tg-chat", default=None, help="Override TELEGRAM_CHAT_ID")

    p.add_argument("--tg-attach-csv", action="store_true", help="Also attach trades.csv to Telegram")
    p.add_argument("--tg-attach-report", action="store_true", help="Also attach report.html to Telegram")

    return p


def main(argv: list[str] | None = None) -> int:
    # автозагрузка .env
    load_env_file(".env", override=False)

    ap = build_arg_parser()
    args = ap.parse_args(argv)

    run_id = args.run_id or "run-" + utc_stamp()
    outdir = build_outdir(args.symbol, args.timeframe, args.strategy, run_id, base=args.outdir)

    # шаг 1: сделки
    trades_csv = run_paper_trade(
        db_url=args.db,
        symbol=args.symbol,
        timeframe=args.timeframe,
        strategy=args.strategy,
        run_id=run_id,
        outdir=outdir,
        fill_mode=args.fill_mode,
        entry_lag=args.entry_lag,
        fee_bps=args.fee_bps,
        slip_bps=args.slip_bps,
        initial_cash=args.initial_cash,
    )

    # шаг 2: метрики
    metrics_json = run_metrics(trades_csv, args.initial_cash, outdir)
    metrics = _read_metrics(metrics_json)

    # шаг 3: телеграм (HTML-сообщение)
    summary_html = _summary_text_html(args.symbol, args.timeframe, args.strategy, run_id, metrics)
    maybe_notify_telegram(
        do_notify=args.notify_telegram,
        tg_token=args.tg_token,
        tg_chat=args.tg_chat,
        outdir=outdir,
        summary_text_html=summary_html,
        attach_csv=args.tg_attach_csv,
        attach_report=args.tg_attach_report,
    )

    print(f"\nArtifacts saved to: {outdir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
