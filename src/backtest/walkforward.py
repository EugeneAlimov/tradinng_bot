# src/backtest/walkforward.py
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Единая точка входа ко всему «ядру» бэктестов
from src.backtest.compat import (
    fetch_exmo_candles_cached as _fetch_exmo_candles_cached,
    resample_ohlc as _resample_ohlc,
    simulate_on_df as _simulate_on_df,
    normalize_resample_rule as _normalize_rr,
    build_bt_config,
    normalize_metrics,
)

log = logging.getLogger(__name__)


# -----------------------------
# Конфиги walk-forward запуска
# -----------------------------

@dataclass(frozen=True)
class WFConfig:
    # Источник данных
    pair: str
    span: str = "1m:3000"  # формат: "<tf>:<count>", пример: "1m:3000"
    resample: str = "5m"  # пример: "5m", "1H"
    cache_dir: Optional[str] = None  # куда класть кэш свечей (если нужно)

    # Стратегия/симуляция (extras прокидываются сквозь build_bt_config)
    strategy: str = "ema_adx_atr"
    fast: int = 12
    slow: int = 21
    adx_len: int = 14
    on: float = 23.0
    off: float = 17.0
    require_di: bool = False
    atr_len: int = 14
    atr_mult: float = 3.0

    fee_bps: int = 10
    slip_bps: int = 2
    hysteresis_bps: int = 0
    cooldown_bars: int = 5
    qty_eur: float = 100.0
    max_daily_loss_bps: int = 0

    # Разбиение на фолды
    folds: int = 4  # сколько OOS-валидаций
    min_train_bars: int = 150  # размер «истории до» первой валидации (после ресэмплинга)
    min_valid_bars: int = 100  # длина каждого OOS-участка (после ресэмплинга)

    # Вывод (при необходимости)
    out_dir: Optional[str] = None


# -----------------------------
# Вспомогательные хелперы
# -----------------------------

def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("walkforward: DataFrame must have DatetimeIndex")
    if df.index.tz is None:
        df = df.tz_localize("UTC")
    return df


def _split_folds(n_bars: int, min_train: int, min_valid: int, folds: int) -> List[Tuple[int, int]]:
    """
    Возвращает список пар индексов (train_end, valid_end) в координатах ресэмпленного df.
    Каждая следующая валидация сдвигается на длину окна валидации.
    """
    segs: List[Tuple[int, int]] = []
    pos = int(min_train)
    for _ in range(int(folds)):
        if pos + int(min_valid) > n_bars:
            break
        segs.append((pos, pos + int(min_valid)))
        pos += int(min_valid)
    return segs


# -----------------------------
# Загрузка свечей (без заглушек)
# -----------------------------

def fetch_exmo_candles_cached(pair: str, span: str, cache_dir: Optional[str] = None) -> pd.DataFrame:
    """
    Совместимая обёртка над fetch_exmo_candles_cached из exchange.exmo.
    Параметр cache_dir здесь игнорируем: низкоуровневый фетчер использует
    внутренние настройки/ENV для кэша.
    """
    df = _fetch_exmo_candles_cached(pair=pair, span=str(span))
    if not isinstance(df, pd.DataFrame):
        raise TypeError("fetch_exmo_candles_cached: expected pandas.DataFrame")
    return df


# -----------------------------
# Основной walk-forward раннер
# -----------------------------

def run_walkforward(
        cfg: WFConfig,
        df_override: Optional[pd.DataFrame] = None,
        print_json: bool = False,  # флаг оставлен для обратной совместимости
        **kwargs: Any,
) -> Dict[str, Any]:
    """
    Выполняет walk-forward без оптимизации параметров:
      - загружает/принимает df, нормализует индекс и таймзону;
      - ресэмплит;
      - режет на фолды (train|valid), но «обучения» не делает — OOS-метрики считаются на валидации;
      - для каждой валидации запускает симуляцию через совместимый слой;
      - возвращает пофолдовые метрики и агрегат.

    Важно: все параметры стратегии/торговли прокидываются в bt_cfg сквозь build_bt_config.
    """
    # 1) Нормализуем правило ресэмплинга
    rr = _normalize_rr(cfg.resample)  # поддержка '5m'/'5T' и т.п.

    # 2) Получаем исходные свечи
    if df_override is not None:
        raw = _ensure_datetime_index(df_override.copy())
    else:
        raw = fetch_exmo_candles_cached(cfg.pair, cfg.span, cache_dir=cfg.cache_dir)
        raw = _ensure_datetime_index(raw)

    if len(raw) == 0:
        raise RuntimeError("walkforward: empty source DataFrame")

    # 3) Ресэмплим единообразно со всем пайплайном
    df_rs = _resample_ohlc(raw, rr)
    if df_rs is None or len(df_rs) == 0:
        raise RuntimeError("walkforward: empty DataFrame after resample")

    # 4) Минимальные требования на размер ряда
    min_need = int(cfg.min_train_bars) + int(cfg.min_valid_bars)
    if len(df_rs) < min_need:
        raise RuntimeError(
            f"walkforward: not enough bars after resample: have={len(df_rs)}, need>={min_need}"
        )

    # 5) Режем на фолды
    segments = _split_folds(
        n_bars=len(df_rs),
        min_train=int(cfg.min_train_bars),
        min_valid=int(cfg.min_valid_bars),
        folds=int(cfg.folds),
    )
    if not segments:
        raise RuntimeError("walkforward: could not create any segments with given parameters")

    # 6) Подготовим общий bt_cfg (extras сквозные)
    extras = dict(
        strategy=cfg.strategy,
        fast=int(cfg.fast),
        slow=int(cfg.slow),
        adx_len=int(cfg.adx_len),
        on=float(cfg.on),
        off=float(cfg.off),
        require_di=bool(cfg.require_di),
        atr_len=int(cfg.atr_len),
        atr_mult=float(cfg.atr_mult),
    )
    bt_cfg_base = build_bt_config(
        pair=cfg.pair,
        resample=rr,
        fee_bps=int(cfg.fee_bps),
        slip_bps=int(cfg.slip_bps),
        max_daily_loss_bps=int(cfg.max_daily_loss_bps),
        hysteresis_bps=int(cfg.hysteresis_bps),
        cooldown_bars=int(cfg.cooldown_bars),
        qty_eur=float(cfg.qty_eur),
        **extras,
    )

    # 7) Пробегаем фолды, считаем OOS-метрики
    oos_rows: List[Dict[str, Any]] = []
    for k, (i_train_end, i_valid_end) in enumerate(segments, start=1):
        df_valid = df_rs.iloc[i_train_end:i_valid_end]
        if len(df_valid) <= 1:
            log.warning("walkforward: fold #%d validation window too small, skip", k)
            continue

        bt_cfg = dict(bt_cfg_base)
        # Передаём df напрямую: симулятор обрабатывает уже ресэмпленный фрейм
        bt_cfg["df"] = df_valid

        # Посчитаем метрики через унифицированный симулятор
        try:
            metrics = _simulate_on_df(df_valid, bt_cfg)
            m = normalize_metrics(metrics)  # мягкая нормализация ключей/типов
        except Exception as e:
            log.exception("walkforward: simulation error on fold #%d: %s", k, e)
            continue

        row: Dict[str, Any] = {
            "fold": k,
            "pair": cfg.pair,
            "resample": rr,
            "train_bars": int(i_train_end),
            "valid_bars": int(i_valid_end - i_train_end),
            "valid_start": df_valid.index[0].isoformat(),
            "valid_end": df_valid.index[-1].isoformat(),
        }
        # Доберём популярные метрики, если симулятор их вернул
        for key in [
            "sharpe",
            "total_return_pct",
            "winrate_pct",
            "max_drawdown_pct",
            "trades",
            "final_equity_eur",
            "start_equity_eur",
            "profit_factor",
            "avg_trade_eur",
            "exposure_pct",
            "bars",
            "bars_per_year",
        ]:
            if key in m:
                row[key] = m[key]
        oos_rows.append(row)

    # 8) Простая сводка
    summary: Dict[str, Any] = {
        "pair": cfg.pair,
        "resample": rr,
        "folds": len(oos_rows),
        "rows": len(df_rs),
        "params": {k: v for k, v in asdict(cfg).items() if k not in {"cache_dir", "out_dir"}},
    }

    return {
        "summary": summary,
        "oos": oos_rows,
    }


# Алиас для совместимости с названием, которое ты упоминал
def run_walk_forward(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return run_walkforward(*args, **kwargs)


__all__ = [
    "WFConfig",
    "fetch_exmo_candles_cached",
    "run_walkforward",
    "run_walk_forward",
]
