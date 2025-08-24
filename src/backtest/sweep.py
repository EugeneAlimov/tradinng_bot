from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
import itertools
import json
import sys
import subprocess
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = PROJECT_ROOT / "main.py"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def parse_int_list(spec: str) -> list[int]:
    """
    '5:20:5' -> [5,10,15,20] ; '0,3,5' -> [0,3,5]
    """
    spec = str(spec).strip()
    if ":" in spec:
        parts = spec.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"Bad int list spec: {spec}")
        start = int(parts[0])
        end = int(parts[1])
        step = int(parts[2]) if len(parts) == 3 else 1
        if step == 0:
            raise ValueError("step must be non-zero")
        vals = list(range(start, end + (1 if (end - start) * step >= 0 else -1), step))
        return vals
    else:
        return [int(x) for x in spec.split(",") if x.strip() != ""]


def parse_float_list(spec: str) -> list[float]:
    spec = str(spec).strip()
    if ":" in spec:
        parts = spec.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"Bad float list spec: {spec}")
        start = float(parts[0])
        end = float(parts[1])
        step = float(parts[2]) if len(parts) == 3 else 1.0
        if step == 0:
            raise ValueError("step must be non-zero")
        vals = []
        x = start
        ascending = step > 0
        eps = step / 1000.0
        if ascending:
            while x <= end + eps:
                vals.append(round(x, 10))
                x += step
        else:
            while x >= end - eps:
                vals.append(round(x, 10))
                x += step
        return vals
    else:
        return [float(x) for x in spec.split(",") if x.strip() != ""]


def _normalize_resample_tag(s: str) -> str:
    return s.lower().replace("t", "m")


@dataclass
class SweepCfg:
    pair: str
    span: str                # e.g. "1m:5000"
    resample: str            # e.g. "5m"
    fast_list: list[int]
    slow_list: list[int]
    hyst_list: list[int]
    cooldown_list: list[int]
    qty_list: list[float]
    fee_bps: int = 10
    slip_bps: int = 2
    max_daily_loss_bps: int = 0
    out_dir: Path | None = None


def _run_backtest_cli(args: list[str]) -> tuple[dict | None, str | None]:
    """
    Возвращает (json_metrics, error_message)
    """
    proc = subprocess.run(
        [sys.executable, str(MAIN_PY), "backtest", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return None, proc.stderr.strip() or f"backtest_failed (code {proc.returncode})"

    metrics = None
    for line in proc.stdout.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                metrics = obj
                break
            except Exception:
                continue
    if not metrics:
        return None, "no_json_from_backtest"
    return metrics, None


def run_sweep(cfg: SweepCfg) -> str:
    out_dir = cfg.out_dir or (PROJECT_ROOT / "data" / "sweep")
    _ensure_dir(out_dir)
    resample_tag = _normalize_resample_tag(cfg.resample)
    out_csv = out_dir / f"sweep_{cfg.pair}_{resample_tag}_{_ts()}.csv"

    rows = []
    for fast, slow, hyst, cd, qty in itertools.product(cfg.fast_list, cfg.slow_list, cfg.hyst_list, cfg.cooldown_list, cfg.qty_list):
        bt_args = [
            "--exmo-pair", cfg.pair,
            "--exmo-candles", cfg.span,
            "--resample", cfg.resample,
            "--fast", str(fast),
            "--slow", str(slow),
            "--hysteresis-bps", str(hyst),
            "--cooldown-bars", str(cd),
            "--fee-bps", str(cfg.fee_bps),
            "--slip-bps", str(cfg.slip_bps),
            "--qty-eur", str(qty),
        ]
        metrics, err = _run_backtest_cli(bt_args)
        if metrics:
            row = {
                "pair": cfg.pair,
                "bars": metrics.get("bars"),
                "trades": metrics.get("trades"),
                "winrate_pct": metrics.get("winrate_pct"),
                "total_return_pct": metrics.get("total_return_pct"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                "final_equity_eur": metrics.get("final_equity_eur"),
                "start_equity_eur": metrics.get("start_equity_eur", 1000.0),
                "profit_factor": metrics.get("profit_factor"),
                "avg_trade_eur": metrics.get("avg_trade_eur"),
                "exposure_pct": metrics.get("exposure_pct"),
                "sharpe": metrics.get("sharpe"),
                "cagr_pct": metrics.get("cagr_pct"),
                "calmar": metrics.get("calmar"),
                "bars_per_year": metrics.get("bars_per_year"),
                "fast": fast,
                "slow": slow,
                "hysteresis_bps": hyst,
                "cooldown_bars": cd,
                "qty_eur": qty,
                "fee_bps": cfg.fee_bps,
                "slip_bps": cfg.slip_bps,
                "max_daily_loss_bps": cfg.max_daily_loss_bps,
                "trades_csv": metrics.get("trades_csv"),
                "equity_csv": metrics.get("equity_csv"),
                "error": None,
            }
        else:
            row = {
                "pair": cfg.pair,
                "bars": None, "trades": None, "winrate_pct": None,
                "total_return_pct": None, "max_drawdown_pct": None, "final_equity_eur": None,
                "start_equity_eur": 1000.0, "profit_factor": None, "avg_trade_eur": None,
                "exposure_pct": None, "sharpe": None, "cagr_pct": None, "calmar": None,
                "bars_per_year": None,
                "fast": fast, "slow": slow, "hysteresis_bps": hyst, "cooldown_bars": cd,
                "qty_eur": qty, "fee_bps": cfg.fee_bps, "slip_bps": cfg.slip_bps,
                "max_daily_loss_bps": cfg.max_daily_loss_bps,
                "trades_csv": None, "equity_csv": None,
                "error": err or "unknown_error",
            }
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    return str(out_csv)
