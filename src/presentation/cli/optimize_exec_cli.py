# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Iterable


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _parse_list(s: Optional[str], cast=float) -> Optional[List]:
    if not s:
        return None
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(cast(part))
    return out or None


@dataclass
class SweepSpace:
    fill_modes: List[str]  # e.g. ["signal","next_open"]
    fee_bps: List[float]  # e.g. [0, 5, 10]
    slip_bps: List[float]  # e.g. [0, 2]
    entry_lag: List[int]  # e.g. [0, 1]
    stop_pct: Optional[List[float]] = None  # e.g. [0.01, 0.02]
    take_pct: Optional[List[float]] = None  # e.g. [0.02, 0.03]
    trail_pct: Optional[List[float]] = None  # e.g. [0.01]


@dataclass
class SweepFixed:
    initial_cash: float = 10_000.0
    risk_pct: Optional[float] = None  # позиционирование от капитала (если нужно)
    start: Optional[str] = None
    end: Optional[str] = None


@dataclass
class Context:
    db_url: str
    symbol: str
    timeframe: str
    strategy: str
    run_id: str
    outdir: Path
    max_combos: Optional[int] = None


def _iter_param_grid(space: SweepSpace) -> Iterable[Dict[str, Any]]:
    axes = [
        ("fill_mode", space.fill_modes),
        ("fee_bps", space.fee_bps),
        ("slip_bps", space.slip_bps),
        ("entry_lag", space.entry_lag),
    ]
    if space.stop_pct:
        axes.append(("stop_pct", space.stop_pct))
    if space.take_pct:
        axes.append(("take_pct", space.take_pct))
    if space.trail_pct:
        axes.append(("trail_pct", space.trail_pct))

    keys = [k for k, _ in axes]
    vals = [v for _, v in axes]
    for combo in itertools.product(*vals):
        yield dict(zip(keys, combo))


def _run_paper_trade(ctx: Context, fixed: SweepFixed, params: Dict[str, Any], workdir: Path) -> Path:
    """
    Запускает paper_trade_cmd для конкретной комбинации параметров.
    Возвращает путь к CSV со сделками.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    trades_csv = workdir / "trades.csv"

    cmd = [
        sys.executable, "-m", "src.presentation.cli.paper_trade_cmd",
        "--db", ctx.db_url,
        "--symbol", ctx.symbol,
        "--timeframe", ctx.timeframe,
        "--strategy", ctx.strategy,
        "--run-id", ctx.run_id,
        "--export-csv", str(trades_csv),
        "--fill-mode", str(params.get("fill_mode", "signal")),
        "--entry-lag", str(params.get("entry_lag", 0)),
        "--fee-bps", str(float(params.get("fee_bps", 0.0))),
        "--slip-bps", str(float(params.get("slip_bps", 0.0))),
        "--initial-cash", str(float(fixed.initial_cash)),
    ]
    if fixed.risk_pct is not None:
        cmd += ["--risk-pct", str(float(fixed.risk_pct))]
    if fixed.start:
        cmd += ["--start", fixed.start]
    if fixed.end:
        cmd += ["--end", fixed.end]

    # риск-менеджмент
    if "stop_pct" in params:
        cmd += ["--stop-pct", str(float(params["stop_pct"]))]
    if "take_pct" in params:
        cmd += ["--take-pct", str(float(params["take_pct"]))]
    if "trail_pct" in params:
        cmd += ["--trail-pct", str(float(params["trail_pct"]))]

    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(r.returncode)
    return trades_csv


def _run_metrics(trades_csv: Path, initial_cash: float, workdir: Path) -> Path:
    metrics_json = workdir / "metrics.json"
    cmd = [
        sys.executable, "-m", "src.presentation.cli.metrics_cli",
        "--trades-csv", str(trades_csv),
        "--initial-cash", str(float(initial_cash)),
        "--export-metrics-json", str(metrics_json),
    ]
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(r.returncode)
    return metrics_json


def _score_key(m: Dict[str, Any]) -> tuple:
    """
    Ключ сортировки результатов:
      1) по final_equity DESC
      2) по profit_factor DESC (если есть, иначе 0)
      3) по max_dd_pct ASC (меньше просадка лучше)
    """
    return (
        float(m.get("final_equity", 0.0)),
        float(m.get("profit_factor", 0.0)),
        -float(m.get("max_dd_pct", 0.0)),
    )


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tb-optimize-exec",
        description="Перебор параметров исполнения по уже записанным сигналам (run_id) с расчётом метрик.",
    )
    # что оптимизируем (источник сигналов)
    p.add_argument("--db", required=True, help="sqlite:///... или duckdb://...")
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True)
    p.add_argument("--strategy", required=True)
    p.add_argument("--run-id", required=True, help="Идентификатор серии сигналов в БД.")

    # пространство перебора
    p.add_argument("--fill-modes", default="signal,next_open")
    p.add_argument("--fee-bps-list", default="0,5,10")
    p.add_argument("--slip-bps-list", default="0,2")
    p.add_argument("--entry-lag-list", default="0,1")
    p.add_argument("--stop-pct-list", default="")
    p.add_argument("--take-pct-list", default="")
    p.add_argument("--trail-pct-list", default="")

    # фикс. параметры
    p.add_argument("--initial-cash", type=float, default=10_000.0)
    p.add_argument("--risk-pct", type=float, default=None)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)

    # вывод
    p.add_argument("--outdir", required=True, help="Папка для результатов перебора.")
    p.add_argument("--max-combos", type=int, default=None, help="Ограничить число комбинаций.")
    p.add_argument("--top", type=int, default=20, help="Сколько лучших показать в консоли.")
    p.add_argument("--export-csv", default=None, help="Путь к сводному CSV со всеми комбинациями.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    ap = _build_parser()
    ns = ap.parse_args(argv)

    space = SweepSpace(
        fill_modes=[s.strip() for s in ns.fill_modes.split(",") if s.strip()],
        fee_bps=_parse_list(ns.fee_bps_list, float) or [0.0],
        slip_bps=_parse_list(ns.slip_bps_list, float) or [0.0],
        entry_lag=_parse_list(ns.entry_lag_list, int) or [0],
        stop_pct=_parse_list(ns.stop_pct_list, float),
        take_pct=_parse_list(ns.take_pct_list, float),
        trail_pct=_parse_list(ns.trail_pct_list, float),
    )
    fixed = SweepFixed(
        initial_cash=ns.initial_cash,
        risk_pct=ns.risk_pct,
        start=ns.start,
        end=ns.end,
    )
    outdir = Path(ns.outdir) / f"sweep-{_now_tag()}"
    outdir.mkdir(parents=True, exist_ok=True)

    ctx = Context(
        db_url=ns.db,
        symbol=ns.symbol,
        timeframe=ns.timeframe,
        strategy=ns.strategy,
        run_id=ns.run_id,
        outdir=outdir,
        max_combos=ns.max_combos,
    )

    rows: List[Dict[str, Any]] = []
    for i, params in enumerate(_iter_param_grid(space), start=1):
        if ctx.max_combos and i > ctx.max_combos:
            print(f"[limit] reached max_combos={ctx.max_combos}, stop.")
            break
        w = outdir / f"comb-{i:04d}"
        trades_csv = _run_paper_trade(ctx, fixed, params, w)
        metrics_json = _run_metrics(trades_csv, fixed.initial_cash, w)
        m = _load_json(metrics_json)

        row = dict(params)
        row.update(
            {
                "comb": i,
                "trades_csv": str(trades_csv),
                **{k: m.get(k) for k in [
                    "trades", "net_pnl", "final_equity", "profit_factor",
                    "max_dd_abs", "max_dd_pct", "win_rate_pct"
                ]},
            }
        )
        rows.append(row)

    # сортировка и вывод ТОПа
    rows_sorted = sorted(rows, key=_score_key, reverse=True)
    top = rows_sorted[: ns.top]

    print("\n=== TOP RESULTS ===")
    if not top:
        print("Нет результатов.")
    else:
        hdr = f"{'#':>3} {'fill':<10} {'fee':>6} {'slip':>6} {'lag':>4} {'stop':>7} {'take':>7} {'trail':>7}  {'trades':>6} {'P/L':>12} {'equity':>12} {'PF':>6} {'maxDD%':>8} {'win%':>7}"
        print(hdr)
        print("-" * len(hdr))
        for r in top:
            print(
                f"{r['comb']:>3} {str(r.get('fill_mode')):<10} "
                f"{float(r.get('fee_bps', 0)):>6.1f} {float(r.get('slip_bps', 0)):>6.1f} "
                f"{int(r.get('entry_lag', 0)):>4d} "
                f"{str(r.get('stop_pct', '-')):>7} {str(r.get('take_pct', '-')):>7} {str(r.get('trail_pct', '-')):>7}  "
                f"{(r.get('trades') or 0):>6} {float(r.get('net_pnl') or 0):>12.6f} {float(r.get('final_equity') or 0):>12.6f} "
                f"{float(r.get('profit_factor') or 0):>6.3f} {float(r.get('max_dd_pct') or 0):>8.3f} {float(r.get('win_rate_pct') or 0):>7.2f}"
            )

    if ns.export_csv:
        csv_path = Path(ns.export_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        import csv as _csv
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(
                f,
                fieldnames=list(rows_sorted[0].keys()) if rows_sorted else [],
            )
            if rows_sorted:
                w.writeheader()
                for r in rows_sorted:
                    w.writerow(r)
        print(f"\nSaved sweep CSV: {csv_path}")

    print(f"Artifacts: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
