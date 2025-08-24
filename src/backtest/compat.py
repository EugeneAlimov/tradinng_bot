# src/backtest/compat.py
from __future__ import annotations

"""
Совместимый слой для backtest/walkforward/sweep.

Экспортирует стабильные имена, которые ожидают другие модули:
  - fetch_exmo_candles_cached
  - resample_ohlc
  - simulate_on_df
  - normalize_resample_rule
  - build_bt_config
  - SimConfig
  - normalize_metrics
  - run_backtest_compat
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


def _sweep() -> Any:
    # Ленивый импорт, чтобы избежать циклических зависимостей при загрузке модулей
    from . import sweep  # type: ignore
    return sweep


def _metrics_mod() -> Any:
    try:
        from . import metrics  # type: ignore
        return metrics
    except Exception:
        return None


# ---------- Публичные фасады к хелперам из sweep.py ----------

def fetch_exmo_candles_cached(pair: str, span: str, cache_dir: Optional[str] = None) -> Any:
    s = _sweep()
    return s._fetch_exmo_candles_cached(pair=pair, span=span, cache_dir=cache_dir)


def resample_ohlc(df: Any, rule: str) -> Any:
    s = _sweep()
    return s._resample_ohlc(df, rule)


def simulate_on_df(df: Any, bt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    s = _sweep()
    return s._simulate_on_df(df, bt_cfg)


def normalize_resample_rule(rule: str) -> str:
    s = _sweep()
    return s._normalize_resample_rule(rule)


# ---------- Конфиг симуляции и сборка bt-конфига ----------

@dataclass(frozen=True)
class SimConfig:
    """
    Унифицированный конфиг для симуляции/бэктеста.
    Список полей покрывает потребности sweep/optimize/walkforward.
    """
    pair: str
    resample: str = "5m"
    fee_bps: int = 10
    slip_bps: int = 2
    max_daily_loss_bps: int = 0
    fast: int = 10
    slow: int = 20
    hysteresis_bps: int = 0
    cooldown_bars: int = 0
    qty_eur: float = 100.0

    def to_bt_config(self) -> Dict[str, Any]:
        return build_bt_config(**asdict(self))


def build_bt_config(
    *,
    pair: str,
    resample: str = "5m",
    fee_bps: int = 10,
    slip_bps: int = 2,
    max_daily_loss_bps: int = 0,
    fast: int = 10,
    slow: int = 20,
    hysteresis_bps: int = 0,
    cooldown_bars: int = 0,
    qty_eur: float = 100.0,
    **extras: Any,
) -> Dict[str, Any]:
    """
    Собирает dict-конфиг бэктеста в формате, который ожидают наши симуляторы.
    Любые дополнительные поля из **extras пролетают сквозь — это безопасно.
    """
    # Нормализуем правило ресемплинга через общий хелпер (поддержка '5m'/'5T' и т.п.)
    rule = normalize_resample_rule(resample)

    bt_cfg: Dict[str, Any] = {
        "pair": pair,
        "resample": rule,
        "fee_bps": int(fee_bps),
        "slip_bps": int(slip_bps),
        "max_daily_loss_bps": int(max_daily_loss_bps),
        "fast": int(fast),
        "slow": int(slow),
        "hysteresis_bps": int(hysteresis_bps),
        "cooldown_bars": int(cooldown_bars),
        "qty_eur": float(qty_eur),
    }

    if extras:
        bt_cfg.update(extras)

    return bt_cfg


# ---------- Нормализация метрик ----------

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def normalize_metrics(metrics: Any, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """
    Унифицированная нормализация метрик.

    Поведение:
      - если есть src.backtest.metrics.normalize_metrics — делегируем туда (с теми же аргументами);
      - иначе используем безопасный fallback, который:
          * принимает dict (или объект с .get);
          * приводит известные числовые поля к float/int;
          * не падает при отсутствии полей;
          * возвращает новый dict (исходный не мутируется).

    Сигнатура поддерживает *args/**kwargs для совместимости с разными вызовами.
    """
    mmod = _metrics_mod()
    if mmod and hasattr(mmod, "normalize_metrics"):
        # отдадим управление «настоящей» реализации, если она есть
        return mmod.normalize_metrics(metrics, *args, **kwargs)  # type: ignore

    # --- fallback: мягкая нормализация словаря метрик ---
    src = dict(metrics or {}) if isinstance(metrics, dict) else {}

    out: Dict[str, Any] = dict(src)  # скопируем всё как есть и поправим известные поля

    # список ожидаемых полей и конвертеров
    float_fields = [
        "winrate_pct", "total_return_pct", "max_drawdown_pct",
        "final_equity_eur", "start_equity_eur",
        "profit_factor", "avg_trade_eur", "exposure_pct",
        "sharpe", "cagr_pct", "calmar",
    ]
    int_fields = ["bars", "trades", "bars_per_year"]

    for f in float_fields:
        if f in src:
            out[f] = _to_float(src.get(f))

    for f in int_fields:
        if f in src:
            out[f] = _to_int(src.get(f))

    # гарантия наличия пары/ресемплинга — если известны
    if "pair" in src:
        out["pair"] = str(src.get("pair"))
    if "resample" in src:
        out["resample"] = str(src.get("resample"))

    return out


# ---------- Совместимый вызов бэктеста (для optimize/sweep) ----------

def run_backtest_compat(bt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Унифицированный бэктест:
      - берёт готовый df из bt_cfg['df'] (если уже получен upstream),
      - иначе сам скачивает свечи через EXMO-кашер,
      - нормализует правило ресемплинга и ресемплит,
      - считает метрики через simulate_on_df.
    Возвращает dict с метриками (совместим с существующим пайплайном).
    """
    # 1) исходный df, если передали заранее
    df = bt_cfg.get("df")

    # 2) иначе — подтянем свечи
    if df is None:
        pair = str(bt_cfg.get("pair"))
        if not pair:
            raise ValueError("run_backtest_compat: 'pair' is required in bt_cfg")

        # Поддерживаем несколько ключей для источника свечей
        span = bt_cfg.get("span") or bt_cfg.get("exmo_candles") or "1m:2000"
        cache_dir = bt_cfg.get("cache_dir")

        df = fetch_exmo_candles_cached(pair=pair, span=str(span), cache_dir=cache_dir)

    # 3) нормализуем правило ресемплинга и ресемплим
    rule = normalize_resample_rule(str(bt_cfg.get("resample", "5m")))
    df_rs = resample_ohlc(df, rule) if rule else df

    # 4) считаем метрики
    metrics = simulate_on_df(df_rs, bt_cfg)

    # 5) перестраховка: вернуть нормализованные метрики
    return normalize_metrics(metrics)


__all__ = [
    "fetch_exmo_candles_cached",
    "resample_ohlc",
    "simulate_on_df",
    "normalize_resample_rule",
    "build_bt_config",
    "SimConfig",
    "normalize_metrics",
    "run_backtest_compat",
]
