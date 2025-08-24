from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd

from .metrics import compute_equity_metrics, estimate_bars_per_year


@dataclass
class WFConfig:
    pair: str
    span: str
    resample: Optional[str]
    fast: int
    slow: int
    hysteresis_bps: int
    cooldown_bars: int
    enter_on_start: bool = False
    fee_bps: int = 10
    slip_bps: int = 0
    qty_eur: float = 50.0
    max_daily_loss_bps: int = 0

    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    out_dir: Optional[Path] = None
    out_json: Optional[Path] = None
    out_csv: Optional[Path] = None


# ===================== хелперы симуляции =====================

def _compute_signals(
    close: pd.Series,
    fast: int,
    slow: int,
    hysteresis_bps: int,
    cooldown_bars: int,
) -> pd.Series:
    """
    Простейшая SMA-логика с гистерезисом (в bps) и cooldown.
    Возвращает target position: 0 или 1 (long/flat).
    """
    fma = close.rolling(fast, min_periods=fast).mean()
    sma = close.rolling(slow, min_periods=slow).mean()

    # разница в bps относительно медленной
    diff_bps = (fma - sma) / sma.replace(0, np.nan) * 1e4
    diff_bps = diff_bps.fillna(0.0)

    pos = np.zeros(len(close), dtype=np.int8)
    cd = 0  # cooldown счётчик
    state = 0
    for i in range(len(close)):
        if cd > 0:
            pos[i] = state
            cd -= 1
            continue
        if state == 0 and diff_bps.iat[i] > hysteresis_bps:
            state = 1
            cd = max(cooldown_bars, 0)
        elif state == 1 and diff_bps.iat[i] < -hysteresis_bps:
            state = 0
            cd = max(cooldown_bars, 0)
        pos[i] = state
    return pd.Series(pos, index=close.index, name="position")


def _simulate_on_df(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    hysteresis_bps: int,
    cooldown_bars: int,
    fee_bps: int,
    slip_bps: int,
    qty_eur: float,
    enter_on_start: bool = False,
) -> Dict[str, Any]:
    """
    Простая векторизованная симуляция long/flat.
    - сделки по цене close, со слиппейджем и комиссией в bps на вход/выход
    - позиция 0/1; размер в EUR фиксированный (qty_eur)
    - equity — mark-to-market
    """
    close = df["close"].astype(float).copy()
    idx = close.index

    pos_target = _compute_signals(close, fast, slow, hysteresis_bps, cooldown_bars).astype(int)

    # точки смены позиции
    pos_prev = pos_target.shift(1).fillna(1 if enter_on_start and pos_target.iat[0] == 1 else 0).astype(int)
    entries = (pos_prev == 0) & (pos_target == 1)
    exits = (pos_prev == 1) & (pos_target == 0)

    fee = fee_bps / 1e4
    slip = slip_bps / 1e4

    eq = np.zeros(len(close), dtype=np.float64)
    cash = 1000.0
    qty_coin = 0.0
    in_pos = False

    trade_pnls: List[float] = []
    wins = 0

    # для экспозиции — доля баров в позиции
    pos_mask = pos_target.values.astype(bool)

    # для отслеживания входной цены/количества
    entry_price = None
    for i, px in enumerate(close.values):
        # вход
        if entries.iat[i] and not in_pos:
            buy_px = px * (1.0 + slip)
            qty_coin = qty_eur / buy_px if buy_px > 0 else 0.0
            fee_cost = qty_eur * fee
            cash -= (qty_eur + fee_cost)
            entry_price = buy_px
            in_pos = True

        # выход
        if exits.iat[i] and in_pos:
            sell_px = px * (1.0 - slip)
            gross = qty_coin * sell_px
            fee_cost = gross * fee
            cash += (gross - fee_cost)

            pnl = (sell_px - float(entry_price or sell_px)) * qty_coin - (qty_eur * fee + gross * fee)
            trade_pnls.append(pnl)
            if pnl > 0:
                wins += 1
            qty_coin = 0.0
            entry_price = None
            in_pos = False

        # mark-to-market
        pos_val = qty_coin * px
        eq[i] = cash + pos_val

    # если позиция осталась открыта — считаем её mark-to-market, но без фиксации трейда (консервативно)
    equity = pd.Series(eq, index=idx, name="equity")

    exposure_pct = 100.0 * (pos_mask.sum() / max(len(pos_mask), 1))
    metrics = compute_equity_metrics(
        equity=equity,
        trade_pnls=trade_pnls,
        n_wins=wins,
        n_trades=len(trade_pnls),
        exposure_pct=exposure_pct,
        start_equity=1000.0,
        risk_free=0.0,
        bars_per_year_hint=estimate_bars_per_year(idx),
    )

    return {
        "equity": equity,
        "trades": pd.DataFrame({
            "pnl_eur": trade_pnls
        }),
        "metrics": metrics,
        "position": pd.Series(pos_mask.astype(int), index=idx, name="position"),
    }


# ===================== walk-forward =====================

def _split_walkforward(df: pd.DataFrame, folds: int, min_train: int, min_valid: int) -> List[Tuple[slice, slice]]:
    """
    Возвращает список (train_slice, valid_slice) по индексам.
    Схема: последовательные не-перекрывающиеся валидации.
    """
    n = len(df)
    if n < (min_train + min_valid):
        return []

    # Делим равномерно хвост на 'folds' валидаций, тренируя перед каждой валидацией
    valid_len = max(min_valid, int((n - min_train) / max(folds, 1)))
    splits: List[Tuple[slice, slice]] = []
    start = 0
    while True:
        train_end = start + min_train
        valid_end = train_end + valid_len
        if valid_end > n:
            break
        splits.append((slice(start, train_end), slice(train_end, valid_end)))
        start += valid_len
        if len(splits) >= folds:
            break
    return splits


def run_walkforward(cfg: WFConfig, df_override: Optional[pd.DataFrame] = None, print_json: bool = True) -> Dict[str, Any]:
    """
    Запускает WF по df_override (желательно уже после единичного resample).
    Возвращает сводные средние OOS-метрики.
    """
    if df_override is None:
        raise RuntimeError("run_walkforward: df_override требуется (чтобы исключить повторные загрузки/ресэмплы).")

    df = df_override.copy()
    if "close" not in df.columns:
        raise RuntimeError("run_walkforward: в DataFrame должен быть столбец 'close'.")

    splits = _split_walkforward(df, cfg.folds, cfg.min_train_bars, cfg.min_valid_bars)
    if not splits:
        out = {
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
            "folds": 0,
            "oos_total_return_pct_mean": 0.0,
            "oos_total_return_pct_std": 0.0,
            "oos_max_drawdown_pct_mean": 0.0,
            "oos_winrate_pct_mean": 0.0,
            "oos_profit_factor_mean": 0.0,
            "oos_sharpe_mean": 0.0,
            "oos_cagr_pct_mean": 0.0,
            "oos_calmar_mean": 0.0,
            "oos_trades_mean": 0.0,
            "oos_exposure_pct_mean": 0.0,
            "oos_avg_trade_eur_mean": 0.0,
        }
        if print_json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        return out

    # собираем метрики по валидациям
    agg: Dict[str, List[float]] = {
        "ret": [], "dd": [], "wr": [], "pf": [], "sharpe": [], "cagr": [], "calmar": [],
        "trades": [], "exposure": [], "avg_trade": [],
    }

    for tr_slice, va_slice in splits:
        valid = df.iloc[va_slice]

        sim = _simulate_on_df(
            df=valid,
            fast=cfg.fast,
            slow=cfg.slow,
            hysteresis_bps=cfg.hysteresis_bps,
            cooldown_bars=cfg.cooldown_bars,
            fee_bps=cfg.fee_bps,
            slip_bps=cfg.slip_bps,
            qty_eur=cfg.qty_eur,
            enter_on_start=cfg.enter_on_start,
        )
        m = sim["metrics"]
        agg["ret"].append(m.total_return_pct)
        agg["dd"].append(m.max_drawdown_pct)
        agg["wr"].append(m.winrate_pct)
        agg["pf"].append(m.profit_factor)
        agg["sharpe"].append(m.sharpe)
        agg["cagr"].append(m.cagr_pct)
        agg["calmar"].append(m.calmar)
        agg["trades"].append(m.trades)
        agg["exposure"].append(m.exposure_pct)
        agg["avg_trade"].append(m.avg_trade_eur)

    def _mean(xs: List[float]) -> float:
        return float(np.mean(xs)) if xs else 0.0

    def _std(xs: List[float]) -> float:
        return float(np.std(xs, ddof=1)) if len(xs) > 1 else 0.0

    out = {
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
        "folds": len(splits),
        "oos_total_return_pct_mean": _mean(agg["ret"]),
        "oos_total_return_pct_std": _std(agg["ret"]),
        "oos_max_drawdown_pct_mean": _mean(agg["dd"]),
        "oos_winrate_pct_mean": _mean(agg["wr"]),
        "oos_profit_factor_mean": _mean(agg["pf"]),
        "oos_sharpe_mean": _mean(agg["sharpe"]),
        "oos_cagr_pct_mean": _mean(agg["cagr"]),
        "oos_calmar_mean": _mean(agg["calmar"]),
        "oos_trades_mean": _mean(agg["trades"]),
        "oos_exposure_pct_mean": _mean(agg["exposure"]),
        "oos_avg_trade_eur_mean": _mean(agg["avg_trade"]),
    }

    if cfg.out_dir:
        Path(cfg.out_dir).mkdir(parents=True, exist_ok=True)
    if cfg.out_csv:
        pd.DataFrame([out]).to_csv(cfg.out_csv, index=False)
    if cfg.out_json:
        with open(cfg.out_json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    if print_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))

    return out


def main():
    ap = argparse.ArgumentParser("walkforward")
    ap.add_argument("--exmo-pair", type=str, required=True)
    ap.add_argument("--exmo-candles", type=str, required=True)
    ap.add_argument("--resample", type=str, default=None)
    ap.add_argument("--fast", type=int, required=True)
    ap.add_argument("--slow", type=int, required=True)
    ap.add_argument("--hysteresis-bps", type=int, default=0)
    ap.add_argument("--cooldown-bars", type=int, default=0)
    ap.add_argument("--enter-on-start", action="store_true")
    ap.add_argument("--fee-bps", type=int, default=10)
    ap.add_argument("--slip-bps", type=int, default=0)
    ap.add_argument("--qty-eur", type=float, default=50.0)
    ap.add_argument("--max-daily-loss-bps", type=int, default=0)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--min-train-bars", type=int, default=150)
    ap.add_argument("--min-valid-bars", type=int, default=100)
    ap.add_argument("--out-dir", type=str, default=None)
    args = ap.parse_args()

    # CLI-режим модуля ожидает, что загрузка и ресэмпл сделаны снаружи (этап В у нас уже), поэтому здесь
    # просто иллюстрация: в проде вызываем через main.py
    raise SystemExit("Use via main.py walk-forward (этот модуль вызывается из CLI оболочки приложения).")


if __name__ == "__main__":
    main()
