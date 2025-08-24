from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
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


def _run_cli(args: list[str]) -> str:
    """
    Запускает CLI-команду и возвращает stdout (text).
    Бросает CalledProcessError, если возврат не 0.
    """
    proc = subprocess.run(
        [sys.executable, str(MAIN_PY), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)
    return proc.stdout


def _find_json_lines(text: str) -> list[dict]:
    objs = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            try:
                objs.append(json.loads(line))
            except Exception:
                pass
    return objs


def _latest_file(dir_: Path, pattern: str) -> Path | None:
    files = sorted(dir_.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _normalize_resample_tag(s: str) -> str:
    """Стабильный тег интервальной метки в именах файлов (5m вместо 5T)."""
    s = s.strip()
    return s.lower().replace("t", "m")


@dataclass
class OptimizeInput:
    pair: str
    span: str
    resample: str
    fast_list: str
    slow_list: str
    hyst_list: str
    cooldown_list: str
    qty_list: str
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int
    metric: str
    min_trades: int
    d_fast: int
    d_slow: int
    d_hyst: int
    d_cd: int
    wf_top_n: int
    folds: int
    min_train_bars: int
    min_valid_bars: int
    wf_min_pf: float
    wf_min_return: float
    wf_max_dd: float
    wf_min_folds: int
    rank_by: str
    final_backtest: bool
    out_dir: Path
    report_html: Path | None


def _sweep(inp: OptimizeInput, out_root: Path) -> Path:
    _ensure_dir(out_root)
    resample_tag = _normalize_resample_tag(inp.resample)
    sweep_dir = out_root
    sweep_args = [
        "sweep",
        "--exmo-pair", inp.pair,
        "--exmo-candles", inp.span,
        "--resample", inp.resample,
        "--fast-list", inp.fast_list,
        "--slow-list", inp.slow_list,
        "--hyst-list", inp.hyst_list,
        "--cooldown-list", inp.cooldown_list,
        "--qty-list", inp.qty_list,
        "--fee-bps", str(inp.fee_bps),
        "--slip-bps", str(inp.slip_bps),
        "--out-dir", str(sweep_dir),
    ]
    _run_cli(sweep_args)
    sweep_csv = _latest_file(sweep_dir, f"sweep_{inp.pair}_{resample_tag}_*.csv")
    if not sweep_csv:
        sweep_csv = _latest_file(sweep_dir, "sweep_*.csv")
    if not sweep_csv:
        raise RuntimeError("Sweep did not produce a CSV.")
    return sweep_csv


def _robustness(inp: OptimizeInput, sweep_csv: Path, out_root: Path) -> Path:
    ranked_csv = out_root / f"ranked_{sweep_csv.name.replace('sweep_', '')}"
    args = [
        "robustness",
        "--sweep-csv", str(sweep_csv),
        "--metric", inp.metric,
        "--min-trades", str(inp.min_trades),
        "--d-fast", str(inp.d_fast),
        "--d-slow", str(inp.d_slow),
        "--d-hyst", str(inp.d_hyst),
        "--d-cd", str(inp.d_cd),
        "--top-n", str(inp.wf_top_n),
        "--out-csv", str(ranked_csv),
    ]
    _run_cli(args)
    if not ranked_csv.exists():
        candidate = _latest_file(out_root, "ranked_*.csv") or _latest_file(out_root, "sweep_ranked*.csv")
        if candidate:
            ranked_csv = candidate
    if not ranked_csv.exists():
        raise RuntimeError("Robustness did not produce a ranked CSV.")
    return ranked_csv


def _walkforward_for_rows(inp: OptimizeInput, ranked: pd.DataFrame, out_root: Path) -> Path | None:
    if ranked.empty:
        return None

    rows = ranked.copy()
    required = ["fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur"]
    for c in required:
        if c not in rows.columns:
            if c == "hysteresis_bps" and "hysteresis-bps" in rows.columns:
                rows["hysteresis_bps"] = rows["hysteresis-bps"]
            else:
                raise RuntimeError(f"Ranked CSV lacks column '{c}'")

    wf_records = []
    for _, r in rows.iterrows():
        args = [
            "walk-forward",
            "--exmo-pair", inp.pair,
            "--exmo-candles", inp.span,
            "--resample", inp.resample,
            "--fast", str(int(r["fast"])),
            "--slow", str(int(r["slow"])),
            "--hysteresis-bps", str(int(r["hysteresis_bps"])),
            "--cooldown-bars", str(int(r["cooldown_bars"])),
            "--fee-bps", str(inp.fee_bps),
            "--slip-bps", str(inp.slip_bps),
            "--qty-eur", str(float(r["qty_eur"])),
            "--folds", str(inp.folds),
            "--min-train-bars", str(inp.min_train_bars),
            "--min-valid-bars", str(inp.min_valid_bars),
        ]
        text = _run_cli(args)
        objs = _find_json_lines(text)
        if not objs:
            continue
        wf = objs[-1]
        wf.update({
            "fast": int(r["fast"]),
            "slow": int(r["slow"]),
            "hysteresis_bps": int(r["hysteresis_bps"]),
            "cooldown_bars": int(r["cooldown_bars"]),
            "qty_eur": float(r["qty_eur"]),
        })
        wf_records.append(wf)

    if not wf_records:
        return None

    df = pd.DataFrame(wf_records)
    wf_csv = out_root / f"wf_{inp.pair}_{_normalize_resample_tag(inp.resample)}_{_ts()}.csv"
    df.to_csv(wf_csv, index=False)
    return wf_csv


def _filter_and_pick(df: pd.DataFrame, inp: OptimizeInput) -> dict | None:
    if df is None or df.empty:
        return None
    keep = df.copy()
    if "oos_profit_factor_mean" in keep.columns:
        keep = keep[keep["oos_profit_factor_mean"] >= inp.wf_min_pf]
    if "oos_total_return_pct_mean" in keep.columns:
        keep = keep[keep["oos_total_return_pct_mean"] >= inp.wf_min_return]
    if "oos_max_drawdown_pct_mean" in keep.columns:
        keep = keep[keep["oos_max_drawdown_pct_mean"] >= -inp.wf_max_dd]  # DD отрицательная
    if "folds" in keep.columns:
        keep = keep[keep["folds"] >= inp.wf_min_folds]

    if keep.empty:
        keep = df

    rank_key = inp.rank_by if inp.rank_by in keep.columns else None
    if not rank_key:
        for k in ["oos_total_return_pct_mean", "oos_calmar_mean", "oos_profit_factor_mean", "oos_sharpe_mean"]:
            if k in keep.columns:
                rank_key = k
                break

    winner = keep.sort_values(rank_key, ascending=False).iloc[0].to_dict()
    return winner


def _final_backtest(inp: OptimizeInput, winner: dict, out_root: Path) -> dict | None:
    if not winner:
        return None
    args = [
        "backtest", "--vectorized",
        "--exmo-pair", inp.pair,
        "--exmo-candles", inp.span,
        "--resample", inp.resample,
        "--fast", str(int(winner["fast"])),
        "--slow", str(int(winner["slow"])),
        "--hysteresis-bps", str(int(winner["hysteresis_bps"])),
        "--cooldown-bars", str(int(winner["cooldown_bars"])),
        "--fee-bps", str(inp.fee_bps),
        "--slip-bps", str(inp.slip_bps),
        "--qty-eur", str(float(winner["qty_eur"])),
        "--out-dir", str(out_root),
    ]
    text = _run_cli(args)
    objs = _find_json_lines(text)
    return objs[-1] if objs else None


def run_optimize(
    pair: str,
    span: str,
    resample: str,
    fast_list: str,
    slow_list: str,
    hyst_list: str,
    cooldown_list: str,
    qty_list: str,
    fee_bps: int,
    slip_bps: int,
    max_daily_loss_bps: int,
    metric: str,
    min_trades: int,
    d_fast: int,
    d_slow: int,
    d_hyst: int,
    d_cd: int,
    wf_top_n: int,
    folds: int,
    min_train_bars: int,
    min_valid_bars: int,
    wf_min_pf: float,
    wf_min_return: float,
    wf_max_dd: float,
    wf_min_folds: int,
    rank_by: str,
    final_backtest: bool,
    out_dir: Path,
    report_html: Path | None = None,
) -> dict:
    """
    Оркестрация: sweep -> robustness -> WF top-N -> выбор -> (опц.) финальный бэктест -> отчёт.
    """
    opt_root = out_dir
    _ensure_dir(opt_root)

    inp = OptimizeInput(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list,
        cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        metric=metric, min_trades=min_trades, d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        wf_top_n=wf_top_n, folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        wf_min_pf=wf_min_pf, wf_min_return=wf_min_return, wf_max_dd=wf_max_dd, wf_min_folds=wf_min_folds,
        rank_by=rank_by, final_backtest=final_backtest, out_dir=opt_root, report_html=report_html,
    )

    sweep_csv = _sweep(inp, opt_root)

    ranked_csv = _robustness(inp, sweep_csv, opt_root)
    ranked_df = pd.read_csv(ranked_csv)
    if "error" in ranked_df.columns:
        ranked_df = ranked_df[ranked_df["error"].isna() | (ranked_df["error"] == "")]
    ranked_df = ranked_df.dropna(subset=["fast", "slow", "hysteresis_bps", "cooldown_bars", "qty_eur"], how="any")
    ranked_df = ranked_df.head(wf_top_n)

    if ranked_df.empty:
        result = {
            "sweep_csv": str(sweep_csv),
            "ranked_csv": str(ranked_csv),
            "wf_csv": None,
            "report_html": str(report_html) if report_html else None,
            "message": "Ranked table is empty or contains only errors; stopping before WF.",
        }
        if report_html:
            _ensure_dir(report_html.parent)
            (report_html).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    wf_csv = _walkforward_for_rows(inp, ranked_df, opt_root)
    wf_df = pd.read_csv(wf_csv) if wf_csv and wf_csv.exists() else pd.DataFrame()

    winner = _filter_and_pick(wf_df, inp)

    final_bt = None
    if final_backtest and winner:
        final_bt = _final_backtest(inp, winner, opt_root)

    report = {
        "pair": pair,
        "resample": resample,
        "sweep_csv": str(sweep_csv),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv) if wf_csv else None,
        "report_html": str(report_html) if report_html else None,
        "wf_rank_by": rank_by,
        "selected": winner,
        "final_metrics": final_bt,
    }
    if report_html:
        _ensure_dir(report_html.parent)
        Path(report_html).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    return report
