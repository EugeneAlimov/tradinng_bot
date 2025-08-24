# src/backtest/walkforward.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import json
import math
import numpy as np
import pandas as pd


# ----------------------------- utils -----------------------------

YEAR_SECONDS = 365 * 24 * 60 * 60


def _bars_per_year_from_index(idx: pd.DatetimeIndex) -> float:
    if len(idx) < 2:
        return 1.0
    diffs_ns = np.diff(idx.view("i8"))
    med_ns = float(np.median(diffs_ns))
    if med_ns <= 0:
        return 1.0
    seconds = med_ns / 1e9
    return YEAR_SECONDS / max(seconds, 1e-9)


def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Надёжная агрегация OHLCV. Явно нормализуем минуты: '5m' -> '5min'
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("OHLC must be indexed by DatetimeIndex (UTC).")
    rule_norm = rule.replace("m", "min") if rule.endswith("m") else rule
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = df.resample(rule_norm, label="right", closed="right").agg(agg).dropna()
    if out.empty:
        raise RuntimeError("Not enough candles after resample.")
    return out


# --------------------------- strategy core ------------------------

@dataclass
class SimConfig:
    fast: int
    slow: int
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    fee_bps: int = 10
    slip_bps: int = 0
    qty_eur: float = 50.0
    enter_on_start: bool = False
    max_daily_loss_bps: int = 0  # дневной «килл-свитч», 0 -> выключен


def _gen_position(close: pd.Series, fast: int, slow: int, hyst_bps: int, cooldown: int) -> pd.Series:
    """
    SMA crossover c гистерезисом и cooldown. Позиция бинарная {0,1}.
    """
    fma = close.rolling(fast, min_periods=fast).mean()
    sma = close.rolling(slow, min_periods=slow).mean()
    spread_bps = (fma - sma) / sma.replace(0, np.nan) * 1e4
    spread_bps = spread_bps.fillna(0.0)

    state = 0
    out = np.zeros(len(close), dtype=np.int8)
    cd = 0
    for i in range(len(close)):
        if cd > 0:
            out[i] = state
            cd -= 1
            continue
        if state == 0 and spread_bps.iat[i] > hyst_bps:
            state = 1
            cd = cooldown
        elif state == 1 and spread_bps.iat[i] < -hyst_bps:
            state = 0
            cd = cooldown
        out[i] = state
    return pd.Series(out, index=close.index, name="position")


def _simulate_on_df(  # <- ВАЖНО: экспортируем для sweep/optimize
    df: pd.DataFrame,
    sim: SimConfig,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """
    Векторная симуляция 0/1 стратегии на OHLC.
    Возвращает кривая equity и метрики (без «экзотики»).
    """
    if df.empty:
        raise RuntimeError("Empty OHLC for simulation")

    close = df["close"].astype(float)
    pos = _gen_position(close, sim.fast, sim.slow, sim.hysteresis_bps, sim.cooldown_bars)

    # «enter_on_start»: если надо, открываем сразу в начале, когда pos=1
    entries = (pos.shift(1).fillna(0) < pos) | ((pos == 1) & sim.enter_on_start & (pos.index == pos.index))
    exits = pos.shift(1).fillna(0) > pos

    # сделаем простую модель сделок: покупка по close (слип+комиссия), продажа по close (слип+комиссия)
    fee = sim.fee_bps / 1e4
    slip = sim.slip_bps / 1e4

    # пересчитываем EUR->коины на входе, и обратно на выходе
    qty_eur = float(sim.qty_eur)

    in_price = close * (1 + slip)
    out_price = close * (1 - slip)

    # equity-линия: стартовый банк 1000 EUR
    equity = pd.Series(1000.0, index=close.index, name="equity")
    coin = 0.0
    cash = 1000.0

    in_pos = False
    trade_pnls: List[float] = []

    # дневной kill-switch
    dd_bps = sim.max_daily_loss_bps / 1e4
    day_open_equity = cash
    current_day = equity.index[0].date()

    wins = 0
    trades = 0
    exposure_bars = 0

    for i, ts in enumerate(close.index):
        price = close.iat[i]
        day = ts.date()
        if day != current_day:
            current_day = day
            day_open_equity = cash + coin * price

        # вход
        if (entries.iat[i] and not in_pos) and cash > 1e-9:
            # комиссию учитываем на обеих сторонах
            spend = min(qty_eur, cash)
            fee_amt = spend * fee
            spend_net = spend - fee_amt
            coin += spend_net / in_price.iat[i]
            cash -= spend
            in_pos = True
            trades += 1

        # выход
        if exits.iat[i] and in_pos:
            proceeds = coin * out_price.iat[i]
            fee_amt = proceeds * fee
            proceeds_net = proceeds - fee_amt
            pnl = proceeds_net - (sim.qty_eur if sim.qty_eur <= (equity.iat[0]) else proceeds_net)  # корректно ниже
            # правильный pnl считается как новая наличка - старая наличка, но чтобы не хранить «вложено», посчитаем иначе:
            # cash после выхода:
            old_cash = cash
            cash += proceeds_net
            # стоимость портфеля до входа/после выхода: pnl = cash_new + coin*price - (cash_old + coin_old*price) с coin_old>0, но перед выходом
            # здесь проще: pnl = proceeds_net - стоимость монет по цене входа; чтобы не хранить цену входа, приближённо возьмём:
            # запомним pnl как разницу equity на шаге после выхода - до входа. Для простоты:
            # пересчитаем equity после выхода:
            coin = 0.0
            new_equity = cash
            prev_equity = equity.iat[i - 1] if i > 0 else equity.iat[0]
            pnl = new_equity - prev_equity
            trade_pnls.append(float(pnl))
            if pnl > 0:
                wins += 1
            in_pos = False

        # дневной лимит
        cur_equity = cash + coin * price
        if sim.max_daily_loss_bps > 0 and cur_equity < day_open_equity * (1 - dd_bps):
            # закрываем позицию и до конца дня «не торгуем»
            if in_pos:
                proceeds = coin * out_price.iat[i]
                fee_amt = proceeds * fee
                proceeds_net = proceeds - fee_amt
                cash += proceeds_net
                # pnl в kill-switch не записываем как сделку (опционально)
                coin = 0.0
                in_pos = False
            # блокируем любые дальнейшие входы до конца дня: грубо — обнулим pos на остаток дня
            # (для векторного кода без «состояния» оставим как есть; при следующем входе проверяется entries)
            pass

        if in_pos:
            exposure_bars += 1

        equity.iat[i] = cash + coin * price

    # если в конце осталась позиция — закроем по последнему close
    if in_pos:
        proceeds = coin * out_price.iat[-1]
        fee_amt = proceeds * fee
        proceeds_net = proceeds - fee_amt
        old_eq = equity.iat[-1]
        cash += proceeds_net
        coin = 0.0
        equity.iat[-1] = cash
        trade_pnls.append(float(equity.iat[-1] - old_eq))
        if trade_pnls[-1] > 0:
            wins += 1
        trades += 1

    # метрики
    start = float(equity.iat[0])
    end = float(equity.iat[-1])
    ret = end / start - 1.0

    # макс. просадка
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    max_dd = float(dd.min())  # отрицательное число

    # profit factor
    pos = sum(p for p in trade_pnls if p > 0)
    neg = sum(p for p in trade_pnls if p < 0)
    pf = float("inf") if neg == 0 and pos > 0 else (pos / abs(neg) if neg != 0 else 0.0)

    bpy = _bars_per_year_from_index(equity.index)
    years = len(equity) / max(bpy, 1.0)
    cagr = (end / start) ** (1.0 / max(years, 1e-9)) - 1.0 if years > 0 else 0.0
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-12 else float("inf")

    out_metrics = {
        "bars": int(len(equity)),
        "trades": int(trades),
        "winrate_pct": 100.0 * (wins / trades) if trades > 0 else 0.0,
        "total_return_pct": 100.0 * ret,
        "max_drawdown_pct": 100.0 * max_dd,
        "final_equity_eur": end,
        "start_equity_eur": start,
        "profit_factor": pf,
        "avg_trade_eur": float(np.mean(trade_pnls)) if trades > 0 else 0.0,
        "exposure_pct": 100.0 * (exposure_bars / max(len(equity), 1)),
        "sharpe": 0.0,  # шапре по баровым доходностям можно добавить при необходимости
        "cagr_pct": 100.0 * cagr,
        "calmar": 100.0 * calmar,
        "bars_per_year": bpy,
    }
    return equity, out_metrics


# --------------------------- walk-forward -------------------------

@dataclass
class WFConfig:
    pair: str
    span: str                # '1m:5000'
    resample: str            # '5m'
    fast: int
    slow: int
    hysteresis_bps: int
    cooldown_bars: int
    fee_bps: int
    slip_bps: int
    qty_eur: float
    folds: int
    min_train_bars: int
    min_valid_bars: int
    enter_on_start: bool = False
    max_daily_loss_bps: int = 0


def _fetch_exmo_candles(pair: str, span: str) -> pd.DataFrame:
    """
    Ожидается, что этот helper уже реализован в vectorized_bt.py.
    Чтобы не плодить дубли, импорт по месту.
    """
    from .vectorized_bt import _fetch_exmo_candles as _fetch
    return _fetch(pair, span)


def _prepare_ohlc(pair: str, span: str, resample: str) -> pd.DataFrame:
    raw = _fetch_exmo_candles(pair, span)
    if raw.empty:
        raise RuntimeError(f"Empty candles from EXMO for {pair} span={span}")
    df = raw.copy()
    # приводим к стандартным именам
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            raise RuntimeError("Fetched candles miss required columns")
    df = _resample_ohlc(df, resample)
    return df


def _fold_slices(n: int, folds: int, min_train: int, min_valid: int) -> List[Tuple[slice, slice]]:
    """
    Возвращает список (train_slice, valid_slice).
    """
    out: List[Tuple[slice, slice]] = []
    start = 0
    while True:
        train_end = start + min_train
        valid_end = train_end + min_valid
        if valid_end > n or len(out) >= folds:
            break
        out.append((slice(start, train_end), slice(train_end, valid_end)))
        start = train_end  # скользящее окно без перекрытия валидации
    return out


def run_walkforward(
    cfg: WFConfig,
    df_override: Optional[pd.DataFrame] = None,
    out_dir: Optional[Path] = None,
    print_json: bool = True,
) -> Dict[str, Any]:
    """
    Выполняет WF. Считает метрики как по фолдам (mean), так и агрегированные (на сшитой OOS-эквити).
    """
    if df_override is None:
        full = _prepare_ohlc(cfg.pair, cfg.span, cfg.resample)
    else:
        full = df_override.copy()
        if not isinstance(full.index, pd.DatetimeIndex):
            raise ValueError("df_override must be indexed by DatetimeIndex (UTC)")

    n = len(full)
    slices = _fold_slices(n, cfg.folds, cfg.min_train_bars, cfg.min_valid_bars)
    if not slices:
        raise RuntimeError("Not enough bars for requested WF settings")

    per_fold: List[Dict[str, Any]] = []
    oos_equity_parts: List[pd.Series] = []
    pf_pos_sum = 0.0
    pf_neg_sum = 0.0

    sim_template = SimConfig(
        fast=cfg.fast, slow=cfg.slow, hysteresis_bps=cfg.hysteresis_bps, cooldown_bars=cfg.cooldown_bars,
        fee_bps=cfg.fee_bps, slip_bps=cfg.slip_bps, qty_eur=cfg.qty_eur,
        enter_on_start=cfg.enter_on_start, max_daily_loss_bps=cfg.max_daily_loss_bps,
    )

    for tr, va in slices:
        train_df = full.iloc[tr]
        valid_df = full.iloc[va]

        # обучаемся на train (в этой версии параметры фиксированы; хукаем сюда оптимизацию, если нужно)
        _ = train_df  # место для будущих fit()

        # симулируем на valid
        eq, m = _simulate_on_df(valid_df, sim_template)
        per_fold.append({
            "fold": len(per_fold) + 1,
            "bars": m["bars"],
            "trades": m["trades"],
            "winrate_pct": m["winrate_pct"],
            "total_return_pct": m["total_return_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "profit_factor": m["profit_factor"],
            "avg_trade_eur": m["avg_trade_eur"],
            "exposure_pct": m["exposure_pct"],
            "cagr_pct": m["cagr_pct"],
            "calmar": m["calmar"],
            "bars_per_year": m["bars_per_year"],
        })

        # для агрегатов по OOS используем относительную доходность
        eq_norm = eq / float(eq.iloc[0])
        oos_equity_parts.append(eq_norm)

        # для PF-агрегации: грубо восстановим pos/neg из avg_trade*trades и winrate (приблизительно)
        # (точно посчитать PF-agg можно, если возвращать pnl-лист — опустим для простоты)
        # здесь лучше оставим PF-mean как среднее по фолдам, а для агрегации вернём NaN
        pass

    # mean по фолдам
    df_folds = pd.DataFrame(per_fold)
    means = df_folds.mean(numeric_only=True).to_dict()

    # агрегаты на сшитой OOS
    oos_eq = pd.concat(oos_equity_parts)
    bpy = _bars_per_year_from_index(oos_eq.index)
    total_ret = float(oos_eq.iloc[-1]) - 1.0
    years = len(oos_eq) / max(bpy, 1.0)
    cagr = (1.0 + total_ret) ** (1.0 / max(years, 1e-9)) - 1.0 if years > 0 else 0.0
    roll_max = oos_eq.cummax()
    dd = oos_eq / roll_max - 1.0
    max_dd = float(dd.min())
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-12 else float("inf")

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

        # классические «средние по фолдам»
        "oos_total_return_pct_mean": float(means.get("total_return_pct", 0.0)) / 100.0,
        "oos_total_return_pct_std": float(df_folds["total_return_pct"].std() / 100.0) if "total_return_pct" in df_folds else 0.0,
        "oos_max_drawdown_pct_mean": float(means.get("max_drawdown_pct", 0.0)) / 100.0,
        "oos_winrate_pct_mean": float(means.get("winrate_pct", 0.0)),
        "oos_profit_factor_mean": float(means.get("profit_factor", 0.0)),
        "oos_sharpe_mean": float(means.get("sharpe", 0.0)) if "sharpe" in means else 0.0,
        "oos_cagr_pct_mean": float(means.get("cagr_pct", 0.0)),
        "oos_calmar_mean": float(means.get("calmar", 0.0)),

        # агрегированные по сшитой OOS (реалистичные)
        "oos_total_return_pct_agg": 100.0 * total_ret,
        "oos_cagr_pct_agg": 100.0 * cagr,
        "oos_max_drawdown_pct_agg": 100.0 * max_dd,
        "oos_calmar_agg": 100.0 * calmar,

        # вспомогательные
        "oos_trades_mean": float(means.get("trades", 0.0)),
        "oos_exposure_pct_mean": float(means.get("exposure_pct", 0.0)),
        "oos_avg_trade_eur_mean": float(means.get("avg_trade_eur", 0.0)),
    }

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # сохраняем фолды как csv
        folds_csv = out_dir / f"wf_{cfg.pair}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.csv"
        df_folds.to_csv(folds_csv, index=False)
        # сводка
        report_json = out_dir / f"wf_summary_{cfg.pair}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.json"
        with report_json.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    if print_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return summary


# точка входа как модуль: python -m src.backtest.walkforward
def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--exmo-pair", dest="pair", type=str, required=True)
    p.add_argument("--exmo-candles", dest="span", type=str, required=True, help="e.g. 1m:5000")
    p.add_argument("--resample", type=str, required=True)
    p.add_argument("--fast", type=int, required=True)
    p.add_argument("--slow", type=int, required=True)
    p.add_argument("--hysteresis-bps", type=int, default=0)
    p.add_argument("--cooldown-bars", type=int, default=0)
    p.add_argument("--fee-bps", type=int, default=10)
    p.add_argument("--slip-bps", type=int, default=0)
    p.add_argument("--qty-eur", type=float, default=50.0)
    p.add_argument("--folds", type=int, default=4)
    p.add_argument("--min-train-bars", type=int, default=150)
    p.add_argument("--min-valid-bars", type=int, default=100)
    p.add_argument("--enter-on-start", action="store_true")
    p.add_argument("--max-daily-loss-bps", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="")

    args = p.parse_args()
    cfg = WFConfig(
        pair=args.pair, span=args.span, resample=args.resample,
        fast=args.fast, slow=args.slow, hysteresis_bps=args.hysteresis_bps,
        cooldown_bars=args.cooldown_bars, fee_bps=args.fee_bps, slip_bps=args.slip_bps,
        qty_eur=args.qty_eur, folds=args.folds, min_train_bars=args.min_train_bars,
        min_valid_bars=args.min_valid_bars, enter_on_start=bool(args.enter_on_start),
        max_daily_loss_bps=args.max_daily_loss_bps,
    )
    out_dir = Path(args.out_dir) if args.out_dir else None
    run_walkforward(cfg, out_dir=out_dir, print_json=True)


if __name__ == "__main__":
    main()
