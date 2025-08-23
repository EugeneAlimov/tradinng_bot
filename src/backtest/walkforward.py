# src/backtest/walkforward.py
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
import pandas as pd

# Берём готовые хелперы и сигналы из векторного бэктеста
from .vectorized_bt import (
    BtConfig,
    _fetch_exmo_candles,
    _resample_ohlcv,
    _make_signals_sma_hysteresis,
    _max_drawdown,
    _normalize_resample_rule,
    _rule_to_seconds,
)

BPS = 1e-4
_SECONDS_IN_YEAR = 365.25 * 24 * 3600


@dataclass
class WFConfig:
    pair: str
    span: str
    resample: Optional[str]
    # стратегия
    fast: int
    slow: int
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    enter_on_start: bool = False
    # издержки/размер
    fee_bps: int = 10
    slip_bps: int = 0
    qty_eur: float = 50.0
    # риск
    max_daily_loss_bps: int = 0
    # walk-forward
    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100
    # выводы
    out_dir: Path = Path("data/walkforward")
    out_json: Optional[Path] = None
    out_csv: Optional[Path] = None


def _infer_bars_per_year(index: pd.DatetimeIndex, rule: Optional[str]) -> float:
    if rule:
        rn = _normalize_resample_rule(rule)
        sec = _rule_to_seconds(rn)
        if sec:
            return _SECONDS_IN_YEAR / sec
    if len(index) >= 3:
        deltas = (index[1:] - index[:-1]).to_series(index=index[1:])
        med = deltas.median().total_seconds()
        if med > 0:
            return _SECONDS_IN_YEAR / med
    return _SECONDS_IN_YEAR / 3600.0


def _simulate_on_df(df: pd.DataFrame, cfg: WFConfig) -> Dict[str, Any]:
    """Полная симуляция на уже подготовленном OHLVC DataFrame."""
    close = df["close"]

    trig = _make_signals_sma_hysteresis(close, cfg.fast, cfg.slow, cfg.hysteresis_bps)
    idx = df.index.to_list()
    pxs = close.to_numpy()

    cash_eur = 1000.0
    pos_qty = 0.0
    cooldown_left = 0

    fee_mult = cfg.fee_bps * BPS
    slip_mult = cfg.slip_bps * BPS

    eq = np.zeros(len(pxs), dtype=np.float64)
    eq_day_start = cash_eur
    entry_cost_eur = 0.0
    closed_pnls: List[float] = []
    in_pos_bars = 0

    last_day = None

    for i in range(len(pxs)):
        px = float(pxs[i])
        ts = idx[i]

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

        # сигналы
        do_entry = trig.iat[i] == 1
        do_exit = trig.iat[i] == -1

        if do_entry:
            if cooldown_left > 0:
                do_entry = False
            if cfg.max_daily_loss_bps and daily_bps <= -abs(float(cfg.max_daily_loss_bps)):
                do_entry = False
            if not cfg.enter_on_start and i < max(cfg.fast, cfg.slow):
                do_entry = False

        # исполнение: long/flat
        if do_entry and pos_qty <= 1e-12:
            buy_px = px * (1.0 + slip_mult)
            qty = cfg.qty_eur / max(1e-12, buy_px)
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
            cooldown_left = max(cooldown_left, cfg.cooldown_bars)

        if pos_qty > 0:
            in_pos_bars += 1

    eq0 = eq[0] if len(eq) > 0 else 1.0
    eqN = eq[-1] if len(eq) > 0 else eq0
    total_return_pct = (eqN / max(1e-12, eq0) - 1.0) * 100.0
    max_dd_pct = _max_drawdown(eq)

    wins = sum(1 for x in closed_pnls if x > 0)
    losses = sum(1 for x in closed_pnls if x <= 0)
    winrate = (wins / max(1, wins + losses)) * 100.0
    profit_sum = float(sum(x for x in closed_pnls if x > 0))
    loss_sum = float(sum(-x for x in closed_pnls if x < 0))
    profit_factor = (profit_sum / loss_sum) if loss_sum > 0 else float("inf")
    avg_trade_eur = (profit_sum - loss_sum) / max(1, (wins + losses))
    exposure_pct = in_pos_bars / max(1, len(eq)) * 100.0

    bars_per_year = _infer_bars_per_year(df.index, cfg.resample)
    rets = pd.Series(eq, index=df.index).pct_change().fillna(0.0).to_numpy()
    ret_mean = float(np.mean(rets))
    ret_std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (ret_mean / ret_std * math.sqrt(bars_per_year)) if ret_std > 0 else 0.0

    if len(df.index) >= 2:
        days = (df.index[-1] - df.index[0]).total_seconds() / 86400.0
        years = max(1e-9, days / 365.25)
        cagr = (eqN / max(1e-12, eq0)) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0
    calmar = (cagr / abs(max_dd_pct / 100.0)) if abs(max_dd_pct) > 1e-12 else float("inf")

    return {
        "bars": int(len(df)),
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


def _make_folds(df: pd.DataFrame, folds: int, min_train: int, min_valid: int) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """Rolling-origin: train = [0:i), valid = [i:i+len_fold)."""
    n = len(df)
    if n < min_train + min_valid:
        raise RuntimeError("Dataset too short for requested train/valid sizes.")
    fold_len = max(min_valid, (n - min_train) // folds)
    splits: List[Tuple[pd.DataFrame, pd.DataFrame]] = []
    start_valid = min_train
    for _ in range(folds):
        end_valid = min(n, start_valid + fold_len)
        train = df.iloc[:start_valid].copy()
        valid = df.iloc[start_valid:end_valid].copy()
        if len(valid) < min_valid:  # последний короткий — пропускаем
            break
        splits.append((train, valid))
        start_valid = end_valid
        if end_valid >= n:
            break
    return splits


def run_walkforward(cfg: WFConfig) -> Dict[str, Any]:
    # 1) Данные
    full = _fetch_exmo_candles(cfg.pair, cfg.span)
    if cfg.resample:
        full = _resample_ohlcv(full, cfg.resample)

    # 2) Разбиение
    folds = _make_folds(full, cfg.folds, cfg.min_train_bars, cfg.min_valid_bars)

    # 3) Прогоны: метрики на valid (out-of-sample)
    per_fold: List[Dict[str, Any]] = []
    for i, (train_df, valid_df) in enumerate(folds, 1):
        m_valid = _simulate_on_df(valid_df, cfg)
        m_valid["fold"] = i
        m_valid["valid_start"] = valid_df.index[0].isoformat()
        m_valid["valid_end"] = valid_df.index[-1].isoformat()
        m_valid["valid_bars"] = int(len(valid_df))
        per_fold.append(m_valid)

    # 4) Агрегация
    agg = pd.DataFrame(per_fold)
    summary = {
        "pair": cfg.pair,
        "resample": cfg.resample,
        "fast": cfg.fast,
        "slow": cfg.slow,
        "hysteresis_bps": cfg.hysteresis_bps,
        "cooldown_bars": cfg.cooldown_bars,
        "fee_bps": cfg.fee_bps,
        "slip_bps": cfg.slip_bps,
        "qty_eur": cfg.qty_eur,
        "max_daily_loss_bps": cfg.max_daily_loss_bps,
        "folds": len(per_fold),
        "oos_total_return_pct_mean": float(agg["total_return_pct"].mean()),
        "oos_total_return_pct_std": float(agg["total_return_pct"].std(ddof=1)) if len(agg) > 1 else 0.0,
        "oos_max_drawdown_pct_mean": float(agg["max_drawdown_pct"].mean()),
        "oos_winrate_pct_mean": float(agg["winrate_pct"].mean()),
        "oos_profit_factor_mean": float(agg["profit_factor"].replace(np.inf, np.nan).mean(skipna=True)),
        "oos_sharpe_mean": float(agg["sharpe"].mean()),
        "oos_cagr_pct_mean": float(agg["cagr_pct"].mean()),
        "oos_calmar_mean": float(agg["calmar"].replace(np.inf, np.nan).mean(skipna=True)),
    }

    # 5) Выгрузки
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = cfg.out_csv or (cfg.out_dir / f"wf_{cfg.pair.replace('/','_')}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.csv")
    pd.DataFrame(per_fold).to_csv(out_csv, index=False)

    out_json = cfg.out_json or (cfg.out_dir / f"wf_summary_{cfg.pair.replace('/','_')}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.json")
    # <-- фикс: PosixPath -> str с default=str
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"config": asdict(cfg), "summary": summary}, f, ensure_ascii=False, indent=2, default=str)

    # принт короткой сводки
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return {"per_fold": per_fold, "summary": summary, "out_csv": str(out_csv), "out_json": str(out_json)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("walkforward", description="Walk-forward evaluation on EXMO candles")
    # data
    p.add_argument("--exmo-pair", required=True)
    p.add_argument("--exmo-candles", required=True)
    p.add_argument("--resample", default=None)
    # strategy
    p.add_argument("--fast", required=True, type=int)
    p.add_argument("--slow", required=True, type=int)
    p.add_argument("--hysteresis-bps", default=0, type=int)
    p.add_argument("--cooldown-bars", default=0, type=int)
    p.add_argument("--enter-on-start", action="store_true")
    # frictions/sizing
    p.add_argument("--fee-bps", default=10, type=int)
    p.add_argument("--slip-bps", default=0, type=int)
    p.add_argument("--qty-eur", default=50.0, type=float)
    # risk
    p.add_argument("--max-daily-loss-bps", default=0, type=int)
    # wf
    p.add_argument("--folds", default=4, type=int)
    p.add_argument("--min-train-bars", default=150, type=int)
    p.add_argument("--min-valid-bars", default=100, type=int)
    # outputs
    p.add_argument("--out-dir", default="data/walkforward")
    p.add_argument("--out-json", default=None)
    p.add_argument("--out-csv", default=None)
    return p


def main(argv: Optional[list] = None) -> None:
    args = build_parser().parse_args(argv)
    cfg = WFConfig(
        pair=args.exmo_pair,
        span=args.exmo_candles,
        resample=args.resample,
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        enter_on_start=bool(args.enter_on_start),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        qty_eur=float(args.qty_eur),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        folds=int(args.folds),
        min_train_bars=int(args.min_train_bars),
        min_valid_bars=int(args.min_valid_bars),
        out_dir=Path(args.out_dir),
        out_json=Path(args.out_json) if args.out_json else None,
        out_csv=Path(args.out_csv) if args.out_csv else None,
    )
    run_walkforward(cfg)


if __name__ == "__main__":
    main()
