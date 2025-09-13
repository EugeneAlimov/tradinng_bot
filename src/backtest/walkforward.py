from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

try:
    import pandas as pd  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore
    np = None  # type: ignore

# Используем утилиты из compat (без циклических импортов)
try:
    from .compat import ensure_datetime_index, normalize_resample_rule  # type: ignore
except Exception:  # pragma: no cover
    def ensure_datetime_index(df):  # fallback на случай редких окружений
        return df


    def normalize_resample_rule(rule: str) -> str:
        return rule


@dataclass(slots=True)
class WFConfig:
    """
    Контракт конфигурации для walk-forward, ожидаемый тестами.
    """
    pair: str
    span: str
    resample: str
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


def _bars_per_year(rule: str) -> float:
    """
    Грубая оценка количества баров в год по правилу ресемплинга.
    Поддерживает 'Xm', 'Xmin', 'XH', 'XD'.
    """
    r = normalize_resample_rule(rule)
    r = r.lower()
    if r.endswith("min"):
        minutes = int(r[:-3])
        minutes = max(1, minutes)
        return 365 * 24 * 60 / minutes
    if r.endswith("h"):
        hours = int(r[:-1])
        hours = max(1, hours)
        return 365 * 24 / hours
    if r.endswith("d"):
        days = int(r[:-1]) if r[:-1].isdigit() else 1
        days = max(1, days)
        return 365 / days
    # по умолчанию считаем минутные бары
    return 365 * 24 * 60


def _ema_positions(close: "pd.Series", fast: int, slow: int) -> "pd.Series":
    """
    Позиция 1, если EMA(fast) > EMA(slow), иначе 0.
    """
    fast = max(1, int(fast))
    slow = max(2, int(slow))
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    pos = (ema_f > ema_s).astype(int)
    return pos


def _slice_metrics(
        df: "pd.DataFrame",
        oos_slice: slice,
        cfg: WFConfig,
) -> Dict[str, float]:
    """
    Считает метрики на заданном OOS-срезе.
    """
    df = ensure_datetime_index(df)
    close = pd.to_numeric(df["close"], errors="coerce").fillna(method="ffill")

    # Позиции считаем на всем ряду (как warmup), но метрики — только на OOS
    pos_full = _ema_positions(close, cfg.fast, cfg.slow)
    ret_full = close.pct_change().fillna(0.0)

    # Транзакционные издержки (на событие смены позы)
    cost_per_event = (cfg.fee_bps + cfg.slip_bps) / 10000.0

    pos = pos_full[oos_slice]
    ret = ret_full[oos_slice].copy()

    # Доходность стратегии: позиция со сдвигом на 1 бар
    strat_ret = ret * pos.shift(1).fillna(0.0)

    # Издержки — на барах смены позиции (включая входы/выходы)
    pos_change = pos.diff().fillna(0.0).abs()
    if cost_per_event > 0:
        strat_ret = strat_ret - cost_per_event * (pos_change > 0).astype(float)

    # Кумулятивная доходность
    equity = (1.0 + strat_ret).cumprod()
    total_return_pct = float((equity.iloc[-1] - 1.0) * 100.0)

    # Максимальная просадка
    roll_max = equity.cummax()
    drawdown = equity / roll_max - 1.0
    max_dd_pct = float(drawdown.min() * 100.0)

    # Profit Factor
    gains = strat_ret[strat_ret > 0].sum()
    losses = -strat_ret[strat_ret < 0].sum()
    if float(losses) > 0:
        profit_factor = float(gains / losses)
    else:
        profit_factor = float("inf") if float(gains) > 0 else 1.0

    # Sharpe (по баровым доходностям)
    r_mean = float(strat_ret.mean())
    r_std = float(strat_ret.std(ddof=0))
    ann_factor = _bars_per_year(cfg.resample) ** 0.5
    sharpe = float(r_mean / r_std * ann_factor) if r_std > 0 else 0.0

    # CAGR
    n_bars = max(1, strat_ret.shape[0])
    bpy = _bars_per_year(cfg.resample)
    cagr = float(((1.0 + strat_ret).prod()) ** (bpy / n_bars) - 1.0)

    # Calmar
    calmar = float(cagr / abs(max_dd_pct / 100.0)) if max_dd_pct < 0 else 0.0

    # Trades & exposure
    trades = int((pos_change > 0).sum())
    exposure_pct = float(pos.mean() * 100.0)

    # Средний PnL на сделку в EUR (грубая оценка)
    total_pnl_eur = cfg.qty_eur * (total_return_pct / 100.0)
    avg_trade_eur = float(total_pnl_eur / trades) if trades > 0 else 0.0

    return {
        "oos_total_return_pct": float(total_return_pct),
        "oos_max_drawdown_pct": float(max_dd_pct),
        "oos_profit_factor": float(profit_factor),
        "oos_sharpe": float(sharpe),
        "oos_cagr_pct": float(cagr * 100.0),
        "oos_calmar": float(calmar),
        "oos_trades": float(trades),
        "oos_exposure_pct": float(exposure_pct),
        "oos_avg_trade_eur": float(avg_trade_eur),
    }


def _wf_slices(n: int, cfg: WFConfig) -> List[slice]:
    """
    Формирует OOS-срезы подряд после initial train окна.
    Каждый срез длиной min_valid_bars, количество — до cfg.folds.
    """
    slices: List[slice] = []
    start = cfg.min_train_bars
    for f in range(cfg.folds):
        oos_start = start + f * cfg.min_valid_bars
        oos_end = oos_start + cfg.min_valid_bars
        if oos_end > n:
            break
        slices.append(slice(oos_start, oos_end))
    return slices


def run_walkforward(
        cfg: WFConfig,
        *,
        df_override: Optional["pd.DataFrame"] = None,
        print_json: bool = True,
) -> Dict[str, Any]:
    """
    Минимальная реализация Walk-Forward с расчётом ожидаемых метрик.
    Возвращает словарь со средними значениями по OOS-фолдам.
    """
    if pd is None:
        raise RuntimeError("pandas is required for walkforward")

    # Данные
    if df_override is not None:
        df = df_override.copy()
    else:
        # На крайний случай — синтетика (редко потребуется в тестах)
        idx = pd.date_range("2020-01-01", periods=cfg.min_train_bars + cfg.folds * cfg.min_valid_bars, freq="1min")
        df = pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0 + np.linspace(0, 1, len(idx)),
                "volume": 0.0,
            },
            index=idx,
        )

    # Безопасная подготовка
    if "close" not in df.columns:
        raise ValueError("DataFrame must contain 'close' column")
    df = ensure_datetime_index(df)

    n = len(df)
    oos_slices = _wf_slices(n, cfg)
    if not oos_slices:
        # Нет валидных фолдов — возвращаем нули, но со всеми ключами.
        return {
            "pair": cfg.pair,
            "resample": cfg.resample,
            "folds": 0,
            "oos_total_return_pct_mean": 0.0,
            "oos_max_drawdown_pct_mean": 0.0,
            "oos_profit_factor_mean": 0.0,
            "oos_sharpe_mean": 0.0,
            "oos_cagr_pct_mean": 0.0,
            "oos_calmar_mean": 0.0,
            "oos_trades_mean": 0.0,
            "oos_exposure_pct_mean": 0.0,
            "oos_avg_trade_eur_mean": 0.0,
            "printed": False if print_json else False,
            "config": cfg,
        }

    # Считаем метрики по каждому OOS-срезу
    per_fold = [_slice_metrics(df, s, cfg) for s in oos_slices]

    def mean_of(key: str) -> float:
        vals = [m[key] for m in per_fold]
        # безопасное среднее
        arr = np.array(vals, dtype=float)
        if arr.size == 0:
            return 0.0
        return float(np.nanmean(arr))

    out: Dict[str, Any] = {
        "pair": cfg.pair,
        "resample": cfg.resample,
        "folds": len(per_fold),
        "oos_total_return_pct_mean": mean_of("oos_total_return_pct"),
        "oos_max_drawdown_pct_mean": mean_of("oos_max_drawdown_pct"),
        "oos_profit_factor_mean": mean_of("oos_profit_factor"),
        "oos_sharpe_mean": mean_of("oos_sharpe"),
        "oos_cagr_pct_mean": mean_of("oos_cagr_pct"),
        "oos_calmar_mean": mean_of("oos_calmar"),
        "oos_trades_mean": mean_of("oos_trades"),
        "oos_exposure_pct_mean": mean_of("oos_exposure_pct"),
        "oos_avg_trade_eur_mean": mean_of("oos_avg_trade_eur"),
        "printed": False if print_json else False,
        "config": cfg,
    }
    return out


# Алиас, который также используется в проекте.
def run_walk_forward(
        cfg: WFConfig,
        *,
        df_override: Optional["pd.DataFrame"] = None,
        print_json: bool = True,
) -> Dict[str, Any]:
    return run_walkforward(cfg, df_override=df_override, print_json=print_json)


__all__ = ["WFConfig", "run_walkforward", "run_walk_forward"]
