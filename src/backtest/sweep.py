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

# Единожды загружаем данные и ресемплим
from .vectorized_bt import (
    _fetch_exmo_candles,
    _resample_ohlcv,
    _make_signals_sma_hysteresis,
    _infer_bars_per_year,
    BPS,
)
# Полный бэктест (если нужно писать артефакты по каждой конфигурации)
from .vectorized_bt import BtConfig, run_backtest_vectorized


# ------------------------ utils: парсеры списков ------------------------

def _parse_int_list(s: str) -> List[int]:
    """
    '6,8,10' -> [6,8,10]
    '5:25:5' -> [5,10,15,20,25]
    Формат диапазона: start:stop:step (включительно, если попадает по шагу).
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
        if out and ((step > 0 and out[-1] > stop) or (step < 0 and out[-1] < stop)):
            out.pop()
        return out
    return [int(x) for x in s.split(",") if x.strip()]


def _parse_float_list(s: str) -> List[float]:
    s = (s or "").strip()
    if not s:
        return []
    return [float(x) for x in s.split(",") if x.strip()]


# ------------------------ быстрый симулятор для свипа ------------------------

def _simulate_full_series(
    df: pd.DataFrame,
    *,
    resample_rule: Optional[str],
    fast: int,
    slow: int,
    hysteresis_bps: int,
    cooldown_bars: int,
    fee_bps: int,
    slip_bps: int,
    qty_eur: float,
    enter_on_start: bool = False,
    max_daily_loss_bps: int = 0,
) -> Dict[str, float]:
    """
    Однопроходная симуляция на всей серии (без WF и без записи файлов).
    df: OHLCV с DatetimeIndex(UTC), колонки: open,high,low,close,volume
    Возвращает метрики как в run_backtest_vectorized.
    """
    n = len(df)
    if n < max(fast, slow) + 5:
        return {
            "bars": n, "trades": 0, "winrate_pct": 0.0, "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "final_equity_eur": 1000.0, "start_equity_eur": 1000.0,
            "profit_factor": 0.0, "avg_trade_eur": 0.0, "exposure_pct": 0.0,
            "sharpe": 0.0, "cagr_pct": 0.0, "calmar": 0.0,
        }

    trig = _make_signals_sma_hysteresis(df["close"], fast, slow, hysteresis_bps)

    idx = df.index.to_list()
    close = df["close"].to_numpy(dtype=np.float64)

    fee_mult = fee_bps * BPS
    slip_mult = slip_bps * BPS

    cash_eur = 1000.0
    pos_qty = 0.0
    cooldown_left = 0
    entry_cost_eur = 0.0
    in_pos_bars = 0

    eq = np.zeros(n, dtype=np.float64)
    closed_pnls: List[float] = []

    # для дневного лимита
    eq_day_start = cash_eur
    last_day = None

    for i in range(n):
        px = float(close[i])
        ts = idx[i]

        # дневной PnL
        day = ts.date()
        if last_day is None:
            last_day = day
            eq_day_start = cash_eur + pos_qty * px
        elif day != last_day:
            eq_day_start = cash_eur + pos_qty * px
            last_day = day

        eq_i = cash_eur + pos_qty * px
        eq[i] = eq_i
        daily_bps = ((eq_i - eq_day_start) / max(1e-12, eq_day_start)) * 1e4

        if cooldown_left > 0 and pos_qty == 0.0:
            cooldown_left -= 1

        do_entry = (trig.iat[i] == 1)
        do_exit = (trig.iat[i] == -1)

        # запреты на вход
        if do_entry:
            if cooldown_left > 0:
                do_entry = False
            if max_daily_loss_bps and daily_bps <= -abs(float(max_daily_loss_bps)):
                do_entry = False
            if not enter_on_start and i < max(fast, slow):
                do_entry = False

        if do_entry and pos_qty <= 1e-12:
            buy_px = px * (1.0 + slip_mult)
            qty = qty_eur / max(1e-12, buy_px)
            notional = qty * buy_px
            fee_eur = notional * fee_mult
            cash_eur -= (notional + fee_eur)
            pos_qty += qty
            entry_cost_eur = notional + fee_eur

        elif do_exit and pos_qty > 1e-12:
            sell_px = px * (1.0 - slip_mult)
            notional = pos_qty * sell_px
            fee_eur = notional * fee_mult
            cash_eur += (notional - fee_eur)
            closed = (notional - fee_eur) - entry_cost_eur
            closed_pnls.append(closed)
            pos_qty = 0.0
            entry_cost_eur = 0.0
            cooldown_left = max(cooldown_left, cooldown_bars)

        if pos_qty > 0:
            in_pos_bars += 1

    # метрики по всей серии
    eq0 = eq[0] if n else 1.0
    eqN = eq[-1] if n else eq0
    total_return_pct = (eqN / max(1e-12, eq0) - 1.0) * 100.0

    peak = -np.inf
    max_dd_pct = 0.0
    for x in eq:
        peak = max(peak, x)
        dd = (x / peak - 1.0) * 100.0
        max_dd_pct = min(max_dd_pct, dd)

    wins = sum(1 for x in closed_pnls if x > 0)
    losses = sum(1 for x in closed_pnls if x <= 0)
    winrate = (wins / max(1, wins + losses)) * 100.0
    profit_sum = float(sum(x for x in closed_pnls if x > 0))
    loss_sum = float(sum(-x for x in closed_pnls if x < 0))
    profit_factor = (profit_sum / loss_sum) if loss_sum > 0 else (float("inf") if profit_sum > 0 else 0.0)
    avg_trade_eur = (profit_sum - loss_sum) / max(1, (wins + losses))
    exposure_pct = in_pos_bars / max(1, n) * 100.0

    bars_per_year = _infer_bars_per_year(df.index, resample_rule)
    rets = (pd.Series(eq, index=df.index).pct_change().fillna(0.0)).to_numpy()
    ret_mean = float(np.mean(rets))
    ret_std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (ret_mean / ret_std * np.sqrt(bars_per_year)) if ret_std > 0 else 0.0

    if n >= 2:
        days = (df.index[-1] - df.index[0]).total_seconds() / 86400.0
        years = max(1e-9, days / 365.25)
        cagr = (eqN / max(1e-12, eq0)) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0
    calmar = (cagr / abs(max_dd_pct / 100.0)) if abs(max_dd_pct) > 1e-12 else float("inf")

    return {
        "bars": int(n),
        "trades": int(wins + losses),
        "winrate_pct": winrate,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_dd_pct,
        "final_equity_eur": float(eqN),
        "start_equity_eur": float(eq0),
        "profit_factor": profit_factor,
        "avg_trade_eur": avg_trade_eur,
        "exposure_pct": exposure_pct,
        "sharpe": sharpe,
        "cagr_pct": cagr * 100.0,
        "calmar": calmar,
    }


# ------------------------ конфиг и основной раннер свипа ------------------------

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


def _row_from_metrics(m: Dict[str, Any], cfg_row: Dict[str, Any]) -> Dict[str, Any]:
    """Собираем строку свип-таблицы из метрик и параметров."""
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
        "bars_per_year": None,
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
        if len(shared_df) < max(3, (max(cfg.fast_list or [1], default=1), max(cfg.slow_list or [1], default=1))[1]):
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

        # БЫСТРЫЙ РЕЖИМ (по умолчанию): одна история, без файлов на конфигурацию
        if not cfg.refetch_per_config and not cfg.save_per_config_csv and not cfg.save_per_config_metrics:
            try:
                m = _simulate_full_series(
                    shared_df,
                    resample_rule=cfg.resample,
                    fast=int(fast), slow=int(slow),
                    hysteresis_bps=int(hyst), cooldown_bars=int(cooldown),
                    fee_bps=int(cfg.fee_bps), slip_bps=int(cfg.slip_bps),
                    qty_eur=float(qty),
                    enter_on_start=False,
                    max_daily_loss_bps=int(cfg.max_daily_loss_bps),
                )
                row = _row_from_metrics(m, {
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

        # МЕДЛЕННЫЙ РЕЖИМ: нужен рефетч или артефакты — используем полноценный бэктест
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

    # Чистим бесконечности (на всякий случай)
    for col in ("profit_factor", "calmar"):
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

    if cfg.sort_by in df.columns:
        df = df.sort_values(cfg.sort_by, ascending=False, na_position="last")

    df.to_csv(out_csv, index=False)
    return out_csv


# ------------------------ CLI ------------------------

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
