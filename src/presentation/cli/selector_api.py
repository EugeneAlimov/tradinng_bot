# src/presentation/cli/selector_api.py
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Tuple

import pandas as pd


# -----------------------------
# Публичные функции модуля
# -----------------------------

def select_and_format(
        rows: Iterable[Dict[str, Any]],
        metric: str = "sharpe",
        top_n: int = 10,
        min_trades: int = 1,
) -> pd.DataFrame:
    """
    Превращает список словарей rows в единый Selected-DataFrame
    с жёстким порядком колонок и одинаковой схемой.

    rows: элементы вида {"strategy": str, "params": dict, **metrics}
    метрики ожидаем минимум: n_trades, win_rate, avg_pnl, total_pnl, max_dd, sharpe, calmar
    (если чего-то нет — заполним NaN/0 по необходимости, но лучше передавать всё).
    """
    df = pd.DataFrame(list(rows)) if not isinstance(rows, pd.DataFrame) else rows.copy()
    if df.empty:
        return _empty_selected_df()

    # гарантируем наличие нужных колонок
    for k, default in _REQUIRED_DEFAULTS.items():
        if k not in df.columns:
            df[k] = default

    # params -> строка JSON (для читабельности в CSV), но оставим и raw-столбец, если он уже есть
    if "params" in df.columns:
        df["params_json"] = df["params"].apply(_json_compact)
        # основной столбец по политике — "params" строкой
        df["params"] = df["params_json"]
    else:
        df["params"] = "{}"

    # приведение типов / наполнение NaN
    df["strategy"] = df["strategy"].astype(str)
    for col in ["n_trades"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
    for col in ["win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # фильтр по min_trades
    df = df[df["n_trades"] >= int(min_trades)].copy()

    # сортировка по метрике
    ascending = metric.lower() in {"max_dd"}  # для max_dd меньше лучше
    metric_col = metric if metric in df.columns else "sharpe"
    df = df.sort_values(by=metric_col, ascending=ascending, na_position="last")

    # top-n
    if top_n and top_n > 0:
        df = df.head(int(top_n)).copy()

    # финальный порядок колонок
    df = df[_SELECTED_ORDER.intersection(df.columns).tolist()]  # пересечение на случай расширений
    # дополнительно: гарантируем полный порядок (добавим отсутствующие справа)
    for c in _SELECTED_ORDER:
        if c not in df.columns:
            df[c] = pd.Series([None] * len(df))
    df = df[_SELECTED_ORDER]

    return df.reset_index(drop=True)


def print_selected(df: pd.DataFrame) -> None:
    """
    Печать отформатированной таблицы выбранных результатов.
    """
    if df is None or df.empty:
        print("Selected: <empty>")
        return

    # немного округлим числовые поля для таблички
    disp = df.copy()
    for c in ["win_rate", "avg_pnl", "total_pnl", "max_dd", "sharpe", "calmar"]:
        if c in disp.columns:
            disp[c] = pd.to_numeric(disp[c], errors="coerce").round(6)
    print(disp.to_string(index=False))


def write_artifacts(
        df: pd.DataFrame,
        out_dir: str,
        out_prefix: str,
        pair: str,
        candles: str,
        cmd: str,
        jsonl: bool = False,
        no_csv: bool = False,
        schema_only: bool = False,
) -> Dict[str, str]:
    """
    Пишет файлы артефактов:
      - CSV (если не запретили)
      - JSONL (опционально)
      - _schema.json (в любом случае, чтобы Selector API был единообразен)
    Имена файлов: <out_prefix><PAIR>_<TF>_<COUNT>_<cmd>_<UTC>.{csv|jsonl|json}
    Возвращает словарь с путями.
    """
    _safe_mkdirs(out_dir)

    tf, cnt = _split_candles(candles)
    ts = _utc_stamp()
    base = f"{_prefix(out_prefix)}{pair}_{tf}_{cnt}_{cmd}_{ts}"

    paths: Dict[str, str] = {}

    # схема
    schema = schema_for(df)
    schema_path = os.path.join(out_dir, f"{base}_schema.json")
    _write_json(schema_path, schema)
    paths["schema"] = schema_path

    if schema_only:
        return paths

    # csv
    if not no_csv:
        csv_path = os.path.join(out_dir, f"{base}.csv")
        # гарантируем порядок колонок, даже если df пуст
        csv_df = df if not df.empty else _empty_selected_df()
        csv_df.to_csv(csv_path, index=False)
        paths["csv"] = csv_path

    # jsonl
    if jsonl:
        jsonl_path = os.path.join(out_dir, f"{base}.jsonl")
        _write_jsonl(jsonl_path, df if not df.empty else _empty_selected_df())
        paths["jsonl"] = jsonl_path

    return paths


def schema_for(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Возвращает JSON-схему селектора: порядок, типы, краткое описание.
    """
    cols = list(_SELECTED_ORDER)
    types = {}
    for c in cols:
        if c not in df.columns:
            types[c] = "unknown"
            continue
        dt = str(df[c].dtype)
        if c in ("strategy", "params"):
            types[c] = "string"
        elif "int" in dt:
            types[c] = "integer"
        elif any(k in dt for k in ("float", "double")):
            types[c] = "number"
        else:
            types[c] = "string"

    return {
        "name": "selector_api.selected",
        "version": 1,
        "columns": cols,
        "types": types,
        "description": "Unified selection output for sweep/optimize/robustness/walk-forward",
    }


# -----------------------------
# Внутренние детали
# -----------------------------

# Жёсткий порядок колонок селектора
_SELECTED_ORDER = pd.Index([
    "strategy",
    "n_trades",
    "win_rate",
    "avg_pnl",
    "total_pnl",
    "max_dd",
    "sharpe",
    "calmar",
    "params",
])

# Запасные значения, если чего-то не хватает
_REQUIRED_DEFAULTS: Dict[str, Any] = {
    "strategy": "",
    "n_trades": 0,
    "win_rate": 0.0,
    "avg_pnl": 0.0,
    "total_pnl": 0.0,
    "max_dd": 0.0,
    "sharpe": 0.0,
    "calmar": 0.0,
    "params": {},
}


def _empty_selected_df() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in _SELECTED_ORDER}).assign(
        strategy=pd.Series(dtype="object"),
        n_trades=pd.Series(dtype="int64"),
        params=pd.Series(dtype="object"),
    )[_SELECTED_ORDER]


def _json_compact(x: Any) -> str:
    try:
        return json.dumps(x if x is not None else {}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


def _safe_mkdirs(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _prefix(p: str) -> str:
    if not p:
        return ""
    # не добавляем подчёркивание — в проекте префикс вставляется как есть
    return p


def _split_candles(candles: str) -> Tuple[str, str]:
    if ":" not in candles:
        return candles, "0"
    tf, cnt = candles.split(":", 1)
    return tf.replace(":", "_"), cnt


def _write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_jsonl(path: str, df: pd.DataFrame) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in df.to_dict(orient="records"):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
