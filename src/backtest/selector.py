from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union, List

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Единый порядок колонок для всех выводов отбора
STANDARD_COLUMNS: List[str] = [
    "strategy",  # str: имя стратегии (ema_adx, ema_adx_atr, ...)
    "params",  # str|dict: параметры стратегии, компактный JSON
    "n_trades",  # int
    "win_rate",  # float [0..1]
    "avg_pnl",  # float per-trade avg PnL (в базовой валюте)
    "total_pnl",  # float total PnL (в базовой валюте)
    "max_dd",  # float max drawdown (в тех же единицах, что и pnl)
    "sharpe",  # float
    "calmar",  # float
    # Дополнительные (могут отсутствовать)
    "period_start",  # str|ts
    "period_end",  # str|ts
    "train_valid",  # 'train'|'valid'|'full'
    "notes",  # произвольные заметки
]

COLUMN_DESCRIPTIONS: Mapping[str, str] = {
    "strategy": "Strategy id/name.",
    "params": "Strategy parameters; JSON string or dict.",
    "n_trades": "Number of closed trades taken in the test window.",
    "win_rate": "Fraction of profitable trades (0..1).",
    "avg_pnl": "Average PnL per trade (base currency).",
    "total_pnl": "Total PnL over the period (base currency).",
    "max_dd": "Maximum drawdown (same units as PnL).",
    "sharpe": "Sharpe ratio (annualization depends on upstream calculation).",
    "calmar": "Calmar ratio (annualization depends on upstream calculation).",
    "period_start": "Start timestamp of the evaluated period (UTC).",
    "period_end": "End timestamp of the evaluated period (UTC).",
    "train_valid": "Which fold/segment the row belongs to: 'train', 'valid', or 'full'.",
    "notes": "Free-form notes.",
}


def _compact_params(params: Any) -> Any:
    """
    Приводим params к компактному и стабильному виду.
    - dict/list/tuple -> JSON без пробелов с отсортированными ключами
    - прочее -> str(params) при ошибке сериализации
    """
    if isinstance(params, (dict, list, tuple)):
        try:
            return json.dumps(params, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except Exception:
            return str(params)
    return params


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет недостающие стандартные колонки с NaN и упорядочивает их."""
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    # Компактный params
    if "params" in df.columns:
        df["params"] = df["params"].map(_compact_params)
    # Типы
    for c in ["n_trades"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in ["win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Порядок колонок: сначала стандартные, потом любые прочие
    other = [c for c in df.columns if c not in STANDARD_COLUMNS]
    ordered = STANDARD_COLUMNS + other
    return df[ordered]


def _safe_metric_series(df: pd.DataFrame, metric: str) -> pd.Series:
    """Безопасно получить серию метрики, заполнив отсутствующие -inf для корректной сортировки."""
    if metric in df.columns:
        return pd.to_numeric(df[metric], errors="coerce").fillna(-np.inf)
    log.warning("Метрика '%s' отсутствует в результатах. Сортировка будет по заглушкам.", metric)
    return pd.Series([-np.inf] * len(df), index=df.index)


@dataclass
class SelectorConfig:
    metric: str = "sharpe"
    top_n: int = 10
    min_trades: int = 1
    # Санити: отбрасывать строки, где нет числа по ключевым метрикам
    dropna_metrics: Tuple[str, ...] = ("n_trades",)


class Selector:
    """
    Единая обвязка для "отбора лучших результатов":
    - нормализация колонок,
    - фильтрация по min_trades,
    - сортировка по метрике,
    - усечение до top_n,
    - опциональный дамп схемы колонок (через dump_schema).
    """

    def __init__(self, cfg: SelectorConfig):
        self.cfg = cfg

    def run(self, results: Union[pd.DataFrame, Sequence[Mapping[str, Any]]]) -> pd.DataFrame:
        df = self._to_frame(results)
        if df.empty:
            return self._finish(df)

        df = _ensure_columns(df)

        # Санити: выбросить None/NaN в ключевых полях
        if self.cfg.dropna_metrics:
            for col in self.cfg.dropna_metrics:
                if col in df.columns:
                    df = df[df[col].notna()]

        # Фильтр по min_trades
        if "n_trades" in df.columns:
            df = df[(df["n_trades"].fillna(0) >= int(self.cfg.min_trades))]

        # Сортировка по выбранной метрике (desc)
        metric_ser = _safe_metric_series(df, self.cfg.metric)
        df = (
            df.assign(_metric_sort=metric_ser)
            .sort_values("_metric_sort", ascending=False)
            .drop(columns=["_metric_sort"])
        )

        # Усечение
        if self.cfg.top_n and self.cfg.top_n > 0:
            df = df.head(int(self.cfg.top_n))

        return self._finish(df)

    @staticmethod
    def _to_frame(results: Union[pd.DataFrame, Sequence[Mapping[str, Any]]]) -> pd.DataFrame:
        if results is None:
            return pd.DataFrame(columns=STANDARD_COLUMNS)
        if isinstance(results, pd.DataFrame):
            return results.copy()
        try:
            return pd.DataFrame(list(results))
        except Exception:
            log.exception("Не удалось привести результаты к DataFrame")
            return pd.DataFrame(columns=STANDARD_COLUMNS)

    @staticmethod
    def _finish(df: pd.DataFrame) -> pd.DataFrame:
        # Финальные косметические правки
        if df.empty:
            return df
        for col, nd in [
            ("win_rate", 4),
            ("avg_pnl", 6),
            ("total_pnl", 6),
            ("max_dd", 6),
            ("sharpe", 4),
            ("calmar", 4),
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").round(nd)
        return df.reset_index(drop=True)


def dump_schema(df: pd.DataFrame, out_path: Union[str, Path]) -> Path:
    """
    Сохраняет JSON со схемой колонок: имя, dtype, описание.
    Возвращает путь к файлу.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def dtype_to_str(dt: Any) -> str:
        try:
            return str(pd.Series([], dtype=dt).dtype)
        except Exception:
            return str(dt)

    schema = []
    for col in df.columns:
        dtype = dtype_to_str(df[col].dtype if col in df.columns else "object")
        schema.append({
            "name": col,
            "dtype": dtype,
            "description": COLUMN_DESCRIPTIONS.get(col, ""),
        })

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "columns": schema,
        "standard_order": STANDARD_COLUMNS,
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info("Schema dumped to %s", out_path)
    return out_path


def make_artifact_path(
        out_dir: Union[str, Path],
        out_prefix: Optional[str],
        pair: str,
        candles: str,
        suffix: str,
        ext: str,
        utc_now: Optional[datetime] = None,
) -> Path:
    """
    Унифицированный конструктор имени артефакта:
    out/data/{prefix_}{pair}_{candles}_{YYYYmmddTHHMMSSZ}_{suffix}.{ext}
    """
    out_dir = Path(out_dir or "out/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = (utc_now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    prefix = (out_prefix + "_") if out_prefix else ""
    filename = f"{prefix}{pair}_{candles}_{ts}_{suffix}.{ext}".replace("/", "-")
    return out_dir / filename
