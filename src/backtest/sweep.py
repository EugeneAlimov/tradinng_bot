# src/backtest/sweep.py
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

import numpy as np
import pandas as pd

# Для единожды загружаемых данных
from .vectorized_bt import (
    _fetch_exmo_candles,
    _resample_ohlcv,
)
# Быстрая симуляция на уже готовом DataFrame
from .walkforward import WFConfig, _simulate_on_df
# Полный бэктест (нужен только если просим сохранять артефакты по каждой конфигурации)
from .vectorized_bt import BtConfig, run_backtest_vectorized


def _parse_int_list(s: str) -> List[int]:
    """
    Парсит '6,8,10' -> [6,8,10] или '5:25:5' -> [5,10,15,20,25]
    Формат диапазона: start:stop:step (включительно, если попадает по шагу)
    """
    s = (s or "").strip()
    if not s:
        return []
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 3:
            raise ValueError(f"Bad range format: '{s}', expected start:stop:step")
        start, stop, step = map(int, parts)
        if step == 0:
            raise ValueError("Step cannot be 0")
        out = list(range(start, stop + (1 if (stop - start) % step == 0 else 0), step))
        if out and (step > 0 and out[-1] > stop) or (step < 0 and out[-1] < stop):
            out.pop()
        return out
    return [int(x) for x in s.split(",") if x.strip()]


def _parse_float_list(s: str) -> List[float]:
    s = (s or "").strip()
    if not s:
        return []
    return [float(x) for x in s.split(",") if x.strip()]


@dataclass
class SweepCfg:
    pair: str
    span: str
    resample: Optional[str]
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int
    out_dir: Path
    sort_by: str
    top_n: int
    # управление файлами/логами
    save_per_config_csv: bool = False         # по умолчанию не плодим файлы
    save_per_config_metrics: bool = False     # по умолчанию не плодим JSON
    quiet_runs: bool = True                   # по умолчанию не печатаем каждую конфигурацию
    # сетевой режим
    refetch_per_config: bool = False          # False = качаем свечи один раз и переиспользуем


def _row_from_wf_metrics(m: Dict[str, Any], cfg_row: Dict[str, Any]) -> Dict[str, Any]:
    """Собираем строку свип-таблицы из метрик симуляции и параметров."""
    return {
        "pair": cfg_row["pair"],
        "bars": m.get("bars"),
        "trades": m.get("trades"),
        "winrate_pct": m.get("winrate_pct"),
        "total_return_pct": m.get("total_return_pct"),
        "max_drawdown_pct": m.get("max_drawdown_pct"),
        "final_equity_eur": m.get("final_equity_eur"),
        "start_equity_eur": m.get("start_equity_eur"),
        "profit_factor": m.get("profit_factor"),
        "avg_trade_eur": m.get("avg_trade_eur"),
        "exposure_pct": m.get("exposure_pct"),
        "sharpe": m.get("sharpe"),
        "cagr_pct": m.get("cagr_pct"),
        "calmar": m.get("calmar"),
        "bars_per_year": None,  # не считаем отдельно — не критично для ранжирования
        # конфиг
        "fast": cfg_row["fast"],
        "slow": cfg_row["slow"],
        "hysteresis_bps": cfg_row["hysteresis_bps"],
        "cooldown_bars": cfg_row["cooldown_bars"],
        "qty_eur": cfg_row["qty_eur"],
        "fee_bps": cfg_row["fee_bps"],
        "slip_bps": cfg_row["slip_bps"],
        "max_daily_loss_bps": cfg_row["max_daily_loss_bps"],
        "trades_csv": None,
        "equity_csv": None,
    }


def run_sweep(cfg: SweepCfg) -> Path:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_csv = cfg.out_dir / f"sweep_{cfg.pair.replace('/','_')}_{cfg.resample or 'raw'}_{stamp}.csv"

    # 1) Готовим данные один раз (если не попросили refetch per config)
    shared_df: Optional[pd.DataFrame] = None
    if not cfg.refetch_per_config:
        base = _fetch_exmo_candles(cfg.pair, cfg.span)
        shared_df = _resample_ohlcv(base, cfg.resample) if cfg.resample else base
        if len(shared_df) < 5:
            raise RuntimeError("Too few candles received for sweep.")

    rows: List[Dict[str, Any]] = []

    grid = itertools.product(
        cfg.fast_list,
        cfg.slow_list,
        cfg.hyst_list,
        cfg.cooldown_list,
        cfg.qty_list,
    )

    for fast, slow, hyst, cooldown, qty in grid:
        if slow <= fast:
            continue

        # Ветка 1: быстрый режим без артефактов — используем одну и ту же историю
        if not cfg.refetch_per_config and not cfg.save_per_config_csv and not cfg.save_per_config_metrics:
            try:
                wfc = WFConfig(
                    pair=cfg.pair, span=cfg.span, resample=cfg.resample,
                    fast=int(fast), slow=int(slow),
                    hysteresis_bps=int(hyst), cooldown_bars=int(cooldown),
                    fee_bps=int(cfg.fee_bps), slip_bps=int(cfg.slip_bps), qty_eur=float(qty),
                    max_daily_loss_bps=int(cfg.max_daily_loss_bps),
                )
                m = _simulate_on_df(shared_df, wfc)  # метрики одной прогонки
                row = _row_from_wf_metrics(m, {
                    "pair": cfg.pair,
                    "fast": fast, "slow": slow,
                    "hysteresis_bps": hyst, "cooldown_bars": cooldown,
                    "qty_eur": qty, "fee_bps": cfg.fee_bps, "slip_bps": cfg.slip_bps,
                    "max_daily_loss_bps": cfg.max_daily_loss_bps,
                })
                rows.append(row)
            except Exception as e:
                rows.append({
                    "pair": cfg.pair, "error": str(e),
                    "fast": fast, "slow": slow,
                    "hysteresis_bps": hyst, "cooldown_bars": cooldown,
                    "qty_eur": qty,
                })
            continue

        # Ветка 2: нужно сохранять CSV/metrics ИЛИ запрошен refetch — полный бэктест с возможной записью
        bt = BtConfig(
            pair=cfg.pair, span=cfg.span, resample_rule=cfg.resample,
            fast=int(fast), slow=int(slow),
            hysteresis_bps=int(hyst), cooldown_bars=int(cooldown),
            fee_bps=int(cfg.fee_bps), slip_bps=int(cfg.slip_bps),
            qty_eur=float(qty), max_daily_loss_bps=int(cfg.max_daily_loss_bps),
            print_summary=not cfg.quiet_runs,
        )
        base_name = f"{cfg.pair.replace('/','_')}_{(cfg.resample or 'raw')}_{fast}-{slow}_h{hyst}_cd{cooldown}_q{int(qty)}"
        if cfg.save_per_config_csv:
            bt.out_trades_csv = cfg.out_dir / f"{base_name}_trades.csv"
            bt.out_equity_csv = cfg.out_dir / f"{base_name}_equity.csv"
        if cfg.save_per_config_metrics:
            bt.out_metrics_json = cfg.out_dir / f"{base_name}_metrics.json"

        try:
            res = run_backtest_vectorized(bt)
            m = res["metrics"]
            rows.append({
                "pair": m["pair"],
                "bars": m["bars"],
                "trades": m["trades"],
                "winrate_pct": m["winrate_pct"],
                "total_return_pct": m["total_return_pct"],
                "max_drawdown_pct": m["max_drawdown_pct"],
                "final_equity_eur": m["final_equity_eur"],
                "start_equity_eur": m["start_equity_eur"],
                "profit_factor": m.get("profit_factor"),
                "avg_trade_eur": m.get("avg_trade_eur"),
                "exposure_pct": m.get("exposure_pct"),
                "sharpe": m.get("sharpe"),
                "cagr_pct": m.get("cagr_pct"),
                "calmar": m.get("calmar"),
                "bars_per_year": m.get("bars_per_year"),
                # config
                "fast": fast,
                "slow": slow,
                "hysteresis_bps": hyst,
                "cooldown_bars": cooldown,
                "qty_eur": qty,
                "fee_bps": cfg.fee_bps,
                "slip_bps": cfg.slip_bps,
                "max_daily_loss_bps": cfg.max_daily_loss_bps,
                "trades_csv": (str(bt.out_trades_csv) if bt.out_trades_csv else None),
                "equity_csv": (str(bt.out_equity_csv) if bt.out_equity_csv else None),
            })
        except Exception as e:
            rows.append({
                "pair": cfg.pair, "error": str(e),
                "fast": fast, "slow": slow,
                "hysteresis_bps": hyst, "cooldown_bars": cooldown,
                "qty_eur": qty,
            })

    df = pd.DataFrame(rows)

    # чистим бесконечности (на всякий случай)
    for col in ("profit_factor", "calmar"):
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

    if cfg.sort_by in df.columns:
        df = df.sort_values(cfg.sort_by, ascending=False, na_position="last")

    df.to_csv(out_csv, index=False)
    return out_csv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("sweep", description="Grid search for vectorized backtest params")
    # data
    p.add_argument("--exmo-pair", required=True, type=str)
    p.add_argument("--exmo-candles", required=True, type=str)
    p.add_argument("--resample", default=None, type=str)

    # grids
    p.add_argument("--fast-list", default="5:15:5", type=str, help="e.g. '6,8,10' or '5:25:5'")
    p.add_argument("--slow-list", default="20:40:5", type=str)
    p.add_argument("--hyst-list", default="0,5,10,15", type=str)
    p.add_argument("--cooldown-list", default="0,3,5", type=str)
    p.add_argument("--qty-list", default="50,100", type=str)

    # trading frictions / risk
    p.add_argument("--fee-bps", default=10, type=int)
    p.add_argument("--slip-bps", default=0, type=int)
    p.add_argument("--max-daily-loss-bps", default=0, type=int)

    # output & ranking
    p.add_argument("--out-dir", default="data/sweep", type=str)
    p.add_argument("--sort-by", default="calmar", type=str)
    p.add_argument("--top-n", default=20, type=int)

    # file explosion control
    p.add_argument("--save-per-config-csv", action="store_true", help="Save trades/equity CSV for each config")
    p.add_argument("--save-per-config-metrics", action="store_true", help="Save metrics JSON for each config")
    p.add_argument("--verbose", action="store_true", help="Print per-config summaries")

    # networking
    p.add_argument("--refetch-per-config", action="store_true", help="Fetch EXMO candles for each config (not recommended)")

    return p


def main(argv: Optional[list] = None) -> None:
    args = build_parser().parse_args(argv)

    scfg = SweepCfg(
        pair=args.exmo_pair,
        span=args.exmo_candles,
        resample=args.resample,
        fast_list=_parse_int_list(args.fast_list),
        slow_list=_parse_int_list(args.slow_list),
        hyst_list=_parse_int_list(args.hyst_list),
        cooldown_list=_parse_int_list(args.cooldown_list),
        qty_list=_parse_float_list(args.qty_list),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        out_dir=Path(args.out_dir),
        sort_by=str(args.sort_by),
        top_n=int(args.top_n),
        save_per_config_csv=bool(args.save_per_config_csv),
        save_per_config_metrics=bool(args.save_per_config_metrics),
        quiet_runs=(not bool(args.verbose)),
        refetch_per_config=bool(args.refetch_per_config),
    )

    out_csv = run_sweep(scfg)

    # Печатаем топ-N строк по метрике sort_by
    df = pd.read_csv(out_csv)
    if scfg.sort_by in df.columns:
        df = df.sort_values(scfg.sort_by, ascending=False, na_position="last")
    top = df.head(scfg.top_n)
    print(f"\nTop {scfg.top_n} by '{scfg.sort_by}':\n")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(top.to_string(index=False))
    print(f"\nSaved all results to: {out_csv}")


if __name__ == "__main__":
    main()
