# src/backtest/walkforward.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd

# Используем унифицированные хелперы из compat
from .compat import (
    normalize_resample_rule,
    fetch_exmo_candles_cached,
    resample_ohlc,
    SimConfig,
    simulate_on_df as _compat_simulate_on_df,  # "ядро" симуляции
)


# ----------------------------- Public API -----------------------------

@dataclass
class WFConfig:
    pair: str
    span: str                 # пример: "1m:5000"
    resample: str = "5m"      # "5m", "5T" и т.п.
    fast: int = 10
    slow: int = 20
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    fee_bps: int = 0
    slip_bps: int = 0
    qty_eur: float = 100.0
    max_daily_loss_bps: int = 0

    folds: int = 4
    min_train_bars: int = 150
    min_valid_bars: int = 100

    out_dir: Optional[str | Path] = None  # если указан — пишем CSV/JSON


def run_walkforward(
    cfg: WFConfig,
    df_override: Optional[pd.DataFrame] = None,
    print_json: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Walk-forward валидация поверх ресэмпленных свечей с фиксированной стратегией.

    Совместимый с тестами контракт:
      - принимает df_override (если передан — используем вместо fetch из EXMO);
      - имеет флаг print_json (по умолчанию True, но тесты могут выключать).
    Возвращает словарь с усредненными OOS метриками и числом фолдов.
    """
    # 1) Нормализуем правило ресэмплинга
    rr_user = cfg.resample
    rr = normalize_resample_rule(rr_user)

    # 2) Источник данных: override -> либо fetch из кеша
    if df_override is not None:
        full = _ensure_datetime_index(df_override.copy())
        # Если override уже в нужном таймфрейме — ресэмплинг не навредит, просто «переуплотнит»
        full_rs = resample_ohlc(full, rr)
    else:
        full = fetch_exmo_candles_cached(cfg.pair, cfg.span)
        full_rs = resample_ohlc(full, rr)

    # 3) Проверка достаточности данных
    min_need = cfg.min_train_bars + cfg.min_valid_bars
    if len(full_rs) < min_need:
        raise RuntimeError(
            f"Not enough bars after resample: have {len(full_rs)}, need at least {min_need}"
        )

    # 4) Формируем фолды WF
    segments = _split_folds(
        n_bars=len(full_rs),
        min_train=cfg.min_train_bars,
        min_valid=cfg.min_valid_bars,
        folds=cfg.folds,
    )
    if not segments:
        raise RuntimeError("Could not create any walk-forward segments with given parameters.")

    # 5) Прогон по каждому OOS отрезку
    oos_rows: List[Dict[str, Any]] = []
    for train_end, valid_end in segments:
        valid = full_rs.iloc[train_end:valid_end].reset_index(drop=True)

        scfg = SimConfig(
            fast=cfg.fast,
            slow=cfg.slow,
            hysteresis_bps=cfg.hysteresis_bps,
            cooldown_bars=cfg.cooldown_bars,
            fee_bps=cfg.fee_bps,
            slip_bps=cfg.slip_bps,
            qty_eur=cfg.qty_eur,
            enter_on_start=False,
            max_daily_loss_bps=cfg.max_daily_loss_bps,
            resample=rr,
        )

        trades_df, equity_df, metrics = _compat_simulate_on_df(valid, scfg)

        # Сохраняем OOS-метрики
        oos_rows.append(
            {
                "pair": cfg.pair,
                "resample": rr_user,
                "fast": cfg.fast,
                "slow": cfg.slow,
                "hysteresis_bps": cfg.hysteresis_bps,
                "cooldown_bars": cfg.cooldown_bars,
                "fee_bps": cfg.fee_bps,
                "slip_bps": cfg.slip_bps,
                "qty_eur": cfg.qty_eur,
                "max_daily_loss_bps": cfg.max_daily_loss_bps,
                "oos_total_return_pct": float(metrics.get("total_return_pct", 0.0)),
                "oos_max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0)),
                "oos_winrate_pct": float(metrics.get("winrate_pct", 0.0)),
                "oos_profit_factor": float(metrics.get("profit_factor", 0.0)),
                "oos_sharpe": float(metrics.get("sharpe", 0.0)),
                "oos_cagr_pct": float(metrics.get("cagr_pct", 0.0)),
                "oos_calmar": float(metrics.get("calmar", 0.0)),
                "oos_trades": int(metrics.get("trades", 0)),
            }
        )

    oos = pd.DataFrame(oos_rows)

    # 6) Агрегация
    def _safe_mean(col: str) -> float:
        s = pd.to_numeric(oos[col], errors="coerce").dropna()
        return float(s.mean()) if len(s) else 0.0

    def _safe_std(col: str) -> float:
        s = pd.to_numeric(oos[col], errors="coerce").dropna()
        return float(s.std(ddof=0)) if len(s) else 0.0

    summary = {
        "pair": cfg.pair,
        "resample": rr_user,
        "fast": cfg.fast,
        "slow": cfg.slow,
        "hysteresis_bps": cfg.hysteresis_bps,
        "cooldown_bars": cfg.cooldown_bars,
        "fee_bps": cfg.fee_bps,
        "slip_bps": cfg.slip_bps,
        "qty_eur": cfg.qty_eur,
        "max_daily_loss_bps": cfg.max_daily_loss_bps,
        "folds": int(len(oos_rows)),
        "oos_total_return_pct_mean": _safe_mean("oos_total_return_pct"),
        "oos_total_return_pct_std": _safe_std("oos_total_return_pct"),
        "oos_max_drawdown_pct_mean": _safe_mean("oos_max_drawdown_pct"),
        "oos_winrate_pct_mean": _safe_mean("oos_winrate_pct"),
        "oos_profit_factor_mean": _safe_mean("oos_profit_factor"),
        "oos_sharpe_mean": _safe_mean("oos_sharpe"),
        "oos_cagr_pct_mean": _safe_mean("oos_cagr_pct"),
        "oos_calmar_mean": _safe_mean("oos_calmar"),
    }

    # 7) Артефакты (по желанию)
    out_csv = None
    out_json = None
    if cfg.out_dir:
        out_root = Path(cfg.out_dir)
        out_root.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        out_csv = out_root / f"wf_{cfg.pair}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.csv"
        oos.to_csv(out_csv, index=False)

        out_json = out_root / f"wf_summary_{cfg.pair}_{cfg.fast}-{cfg.slow}_h{cfg.hysteresis_bps}_cd{cfg.cooldown_bars}.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    if print_json:
        # аккуратно печатаем только summary
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return summary


# ----------------------------- Internal helpers -----------------------------

def _split_folds(n_bars: int, min_train: int, min_valid: int, folds: int) -> List[Tuple[int, int]]:
    """
    Формирует список сегментов (train_end_idx, valid_end_idx], где валидация — (train_end; valid_end].
    Алгоритм «скользящего окна»: train фиксирован минимумом, валидируем кусками по min_valid.
    """
    segments: List[Tuple[int, int]] = []
    train_end = min_train
    for _ in range(max(0, folds)):
        valid_end = train_end + min_valid
        if valid_end > n_bars:
            break
        segments.append((train_end, valid_end))
        train_end += min_valid
    return segments


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """Убедиться, что индекс — DatetimeIndex в UTC (или конвертировать колонку time/timestamp)."""
    if isinstance(df.index, pd.DatetimeIndex):
        # нормализуем tz
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df

    # попытки найти временную колонку
    for col in ("time", "timestamp", "ts"):
        if col in df.columns:
            idx = pd.to_datetime(df[col], unit="s", utc=True, errors="coerce")
            if idx.notna().all():
                df = df.copy()
                df.index = idx
                return df

    # как есть (совместимость), но это может нарушить ресэмплинг
    return df


# ----------------------------- Legacy shims (re-exports) -----------------------------

def _normalize_resample_rule(rule: str) -> str:
    """Старое имя хелпера — сохраним совместимость."""
    return normalize_resample_rule(rule)


def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Старое имя хелпера — сохраним совместимость."""
    return resample_ohlc(df, rule)


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
    max_daily_loss_bps: int = 0,
    resample: str = "5m",
):
    """
    Legacy-совместимая обёртка под старую сигнатуру, которую ожидал sweep.py.
    Возвращает (trades_df, equity_df, metrics_dict).
    """
    scfg = SimConfig(
        fast=fast,
        slow=slow,
        hysteresis_bps=hysteresis_bps,
        cooldown_bars=cooldown_bars,
        fee_bps=fee_bps,
        slip_bps=slip_bps,
        qty_eur=qty_eur,
        enter_on_start=enter_on_start,
        max_daily_loss_bps=max_daily_loss_bps,
        resample=normalize_resample_rule(resample),
    )
    return _compat_simulate_on_df(df, scfg)
