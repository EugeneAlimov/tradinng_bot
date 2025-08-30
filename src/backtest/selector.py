# src/backtest/selector.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence

import pandas as pd

# Единый порядок колонок для табличных результатов
PREFERRED_COL_ORDER: Sequence[str] = (
    "strategy", "params",
    "size", "fees_bps", "slippage_bps",
    "n_trades", "win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar",
)


@dataclass
class SelectorConfig:
    metric: str = "sharpe"
    top_n: int = 3
    min_trades: int = 1
    # Если None — выбираем направление сортировки автоматически (обычно по убыванию)
    ascending: bool | None = None


class Selector:
    """
    Единая логика отбора лучших строк по метрике + фильтры.
    """

    def __init__(self, cfg: SelectorConfig):
        self.cfg = cfg

    def run(self, rows: List[Dict[str, Any]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(columns=list(PREFERRED_COL_ORDER))

        df = pd.DataFrame(rows)

        # Параметры в JSON-строку для стабильного вывода/CSV
        if "params" in df.columns:
            df["params"] = df["params"].apply(
                lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x)

        # Фильтр по min_trades (если поле присутствует)
        if "n_trades" in df.columns:
            df = df.loc[df["n_trades"].fillna(0).astype(int) >= int(self.cfg.min_trades)].copy()

        # Если пусто после фильтра — вернуть пустую таблицу, но с заголовками
        if df.empty:
            return pd.DataFrame(columns=self._ordered_cols(df))

        # Определяем направление сортировки
        asc = self._choose_ascending(df, self.cfg.metric, self.cfg.ascending)

        # Если метрика отсутствует — не падаем, просто не сортируем
        if self.cfg.metric in df.columns:
            df = df.sort_values(self.cfg.metric, ascending=asc, kind="mergesort")  # стабильная сортировка

        # Обрезаем top_n
        df = df.head(int(self.cfg.top_n)).reset_index(drop=True)

        # Переупорядочиваем колонки
        cols = self._ordered_cols(df)
        return df.loc[:, cols]

    @staticmethod
    def _choose_ascending(_df: pd.DataFrame, metric: str, user_flag: bool | None) -> bool:
        if user_flag is not None:
            return bool(user_flag)
        m = str(metric).lower()
        # Для метрик вида "loss"/RMSE/MSE/MAE — меньше лучше → сортируем по возрастанию.
        if m in {"loss", "rmse", "mse", "mae"}:
            return True

        # В остальных случаях (sharpe, calmar, win_rate, total_pnl, max_dd<=0 и т.д.)
        # больше лучше → сортируем по убыванию.
        return False

    @staticmethod
    def _ordered_cols(df: pd.DataFrame) -> List[str]:
        pref = [c for c in PREFERRED_COL_ORDER if c in df.columns]
        rest = [c for c in df.columns if c not in pref]
        return pref + rest


# ---------------------------- Артефакты ---------------------------- #

_TS_FMT = "%Y%m%d_%H%M%S"
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FMT)


def _sanitize(s: str) -> str:
    return _SANITIZE_RE.sub("_", s.strip())


def make_artifact_path(out_dir: str, out_prefix: str, pair: str, candles: str, stem: str, ext: str) -> str:
    """
    Единый формат имени файла:
      {out_dir}/{out_prefix}{pair}_{candles}_{stem}_{UTC}.ext
    Папка создаётся при необходимости.
    """
    os.makedirs(out_dir, exist_ok=True)
    prefix = f"{_sanitize(out_prefix)}_" if out_prefix else ""
    fname = f"{prefix}{_sanitize(pair)}_{_sanitize(candles)}_{_sanitize(stem)}_{_utc_now_str()}.{_sanitize(ext)}"
    return os.path.join(out_dir, fname)


def dump_schema(df: pd.DataFrame, path: str) -> None:
    """
    Сохраняет JSON-схему результата для downstream-инструментов:
      - фиксированный порядок и типы колонок
      - версию схемы
      - отметку времени UTC
    """
    schema = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "columns": [
            {
                "name": str(col),
                "dtype": str(df[col].dtype) if col in df.columns else "unknown",
            }
            for col in df.columns
        ],
        "preferred_order": list(PREFERRED_COL_ORDER),
        "primary_metric": getattr(df, "primary_metric", None),
        "rows": int(df.shape[0]),
    }
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(schema, ensure_ascii=False, indent=2))
