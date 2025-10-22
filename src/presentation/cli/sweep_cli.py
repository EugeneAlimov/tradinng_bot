#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sweep CLI — перебор параметров для paper-trade командой из указанного модуля.
Пример:
PYTHONPATH=. python -m src.presentation.cli.sweep_cli \
  --ohlcv data/demo_ohlcv_1m.csv \
  --resample 5min \
  --ema-fast 12 --ema-slow 21 \
  --adx-len 14 \
  --adx-on 28,32 --adx-off 18,20,22 \
  --require-di true \
  --htf-tf 15min,1h \
  --stop-atr 2.0,2.5,3.0 \
  --take-atr 1.0,1.5,2.0 \
  --trail-atr 1.0,2.0 \
  --cooldown-bars 0,12,24 \
  --min-hold-bars 0,6 \
  --breakeven-rr 0.5,1.0 \
  --trail-activate-rr 1.5,3.0 \
  --fee-bps 10 --slip-bps 2 --qty 1 \
  --out reports/sweep_full.csv \
  --paper-cli src.presentation.cli.paper_trade_cmd
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LOG_PREFIX = "[sweep]"


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} INFO {LOG_PREFIX} {msg}", flush=True)


def read_ohlcv_header_hint(path: str) -> None:
    # Лёгкая «подсказка» без pandas: показываем распознанное имя колонки времени
    # и что строки будут читаться в подпроцессе.
    try:
        with open(path, "r", encoding="utf-8") as f:
            header = f.readline().strip()
        cols = [c.strip().strip('"').strip("'") for c in header.split(",")]
        time_col = None
        for cand in ("timestamp", "time", "datetime", "date", "ts"):
            if cand in cols:
                time_col = cand
                break
        if time_col is None:
            time_col = "time"
        log(f"Detected time column: '{time_col}' -> normalized as 'time'. Rows: (source читается в подпроцессе)")
    except Exception:
        log("Detected time column: 'timestamp' -> normalized as 'time'. Rows: (source читается в подпроцессе)")


def parse_list(s: Optional[str], cast) -> List[Any]:
    if s is None:
        return []
    s = str(s).strip()
    if s == "":
        return []
    parts = [p.strip() for p in s.split(",")]
    out: List[Any] = []
    for p in parts:
        if cast is bool:
            if p.lower() in ("1", "true", "yes", "y", "t"):
                out.append(True)
            elif p.lower() in ("0", "false", "no", "n", "f"):
                out.append(False)
            else:
                raise ValueError(f"cannot parse bool from '{p}'")
        else:
            out.append(cast(p))
    return out


def as_single_or_many(values: List[Any], default: Optional[Any] = None) -> List[Any]:
    if not values:
        return [default] if default is not None else []
    return values


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Parameter sweep over paper-trade CLI")
    # источник и базовые
    p.add_argument("--ohlcv", required=True, help="CSV with OHLCV")
    p.add_argument("--resample", required=True, help="Target timeframe, e.g. 5min")

    # сигналы/индикаторы
    p.add_argument("--ema-fast", required=True)
    p.add_argument("--ema-slow", required=True)
    p.add_argument("--adx-len", required=True)
    p.add_argument("--adx-on", required=True)
    p.add_argument("--adx-off", required=True)
    p.add_argument("--require-di", required=True)

    p.add_argument("--htf-tf", required=True, help="Higher timeframe(s), comma-separated")

    # риск/менеджмент
    p.add_argument("--stop-atr", required=True)
    p.add_argument("--take-atr", default=None, help="Optional take profit in ATRs, supports grid")
    p.add_argument("--trail-atr", required=True)
    p.add_argument("--cooldown-bars", required=True)
    p.add_argument("--min-hold-bars", required=True)
    p.add_argument("--breakeven-rr", required=True)
    p.add_argument("--trail-activate-rr", required=True)

    # исполнение/комиссии
    p.add_argument("--fee-bps", required=True)
    p.add_argument("--slip-bps", required=True)
    p.add_argument("--qty", required=True)

    # техн.
    p.add_argument("--out", required=True, help="Output CSV file")
    p.add_argument("--max-rows", type=int, default=None, help="Cap on rows written")
    p.add_argument("--paper-cli", default="src.presentation.cli.paper_trade_cmd",
                   help="Dotted module path used with 'python -m ...' for paper trade")

    return p


def to_product(args: argparse.Namespace) -> Tuple[List[str], Iterable[Dict[str, Any]]]:
    # Спецификация параметров сетки + типы
    grid_specs: List[Tuple[str, Any, Any]] = [
        ("resample", str, args.resample),
        ("ema_fast", int, args.ema_fast),
        ("ema_slow", int, args.ema_slow),
        ("adx_len", int, args.adx_len),
        ("adx_on", float, args.adx_on),
        ("adx_off", float, args.adx_off),
        ("require_di", bool, args.require_di),
        ("htf_tf", str, args.htf_tf),
        ("stop_atr", float, args.stop_atr),
        ("take_atr", float, args.take_atr),  # новое поле — можно не указывать
        ("trail_atr", float, args.trail_atr),
        ("cooldown_bars", int, args.cooldown_bars),
        ("min_hold_bars", int, args.min_hold_bars),
        ("breakeven_rr", float, args.breakeven_rr),
        ("trail_activate_rr", float, args.trail_activate_rr),
        ("fee_bps", float, args.fee_bps),
        ("slip_bps", float, args.slip_bps),
        ("qty", float, args.qty),
    ]

    keys: List[str] = []
    values_lists: List[List[Any]] = []

    for key, caster, raw in grid_specs:
        vals = parse_list(raw, caster)
        # Разрешаем одиночные значения
        vals = as_single_or_many(vals, default=None if key == "take_atr" else None)
        # Если «take_atr» пуст — оставим [None], чтобы вовсе не передавать ключ
        if key == "take_atr" and (not vals or vals == [None]):
            vals = [None]
        if not vals:
            # Это не должно происходить для required полей
            raise ValueError(f"Parameter '{key}' yielded empty values list")
        keys.append(key)
        values_lists.append(vals)

    # Декартово произведение
    def gen() -> Iterable[Dict[str, Any]]:
        for combo in itertools.product(*values_lists):
            yield dict(zip(keys, combo))

    return keys, gen()


def _iter_json_objects(text: str):
    """Итерируем по JSON-объектам в тексте: ищем сбалансированные {...},
    игнорируя фигурные скобки внутри строк."""
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start:i+1]
                    start = None

def extract_summary_from_stdout(stdout_text: str) -> Optional[Dict[str, Any]]:
    """Берём последний валидный JSON с нужными ключами."""
    last = None
    for raw in _iter_json_objects(stdout_text):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if all(k in obj for k in ("trades", "win_rate", "net_pnl", "avg_pnl")):
            last = obj
    return last



def run_paper_once(paper_module: str, ohlcv: str, cfg: Dict[str, Any]) -> Tuple[
    Optional[Dict[str, Any]], Optional[str]]:
    # Формируем команду python -m <paper_module> <args>
    cmd = [
        sys.executable, "-m", paper_module,
        "--ohlcv", ohlcv,
        "--resample", str(cfg["resample"]),
        "--ema-fast", str(cfg["ema_fast"]),
        "--ema-slow", str(cfg["ema_slow"]),
        "--adx-len", str(cfg["adx_len"]),
        "--adx-on", str(cfg["adx_on"]),
        "--adx-off", str(cfg["adx_off"]),
        "--require-di", "true" if cfg["require_di"] else "false",
        "--htf-tf", str(cfg["htf_tf"]),
        "--stop-atr", str(cfg["stop_atr"]),
        "--trail-atr", str(cfg["trail_atr"]),
        "--cooldown-bars", str(cfg["cooldown_bars"]),
        "--min-hold-bars", str(cfg["min_hold_bars"]),
        "--breakeven-rr", str(cfg["breakeven_rr"]),
        "--trail-activate-rr", str(cfg["trail_activate_rr"]),
        "--fee-bps", str(cfg["fee_bps"]),
        "--slip-bps", str(cfg["slip_bps"]),
        "--qty", str(cfg["qty"]),
        "--trades-out", "/dev/null",
    ]
    if cfg.get("take_atr") is not None:
        cmd += ["--take-atr", str(cfg["take_atr"])]

    # Выполняем
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as e:
        return None, f"Paper CLI not found: {paper_module}: {e}"
    except Exception as e:
        return None, f"Failed to execute paper CLI: {e}"

    stdout_text = proc.stdout or ""
    stderr_text = proc.stderr or ""
    if proc.returncode != 0:
        err = f"paper-cli exit {proc.returncode}\n--- STDOUT ---\n{stdout_text}\n--- STDERR ---\n{stderr_text}"
        return None, err

    summary = extract_summary_from_stdout(stdout_text)
    if summary is None:
        # не нашли JSON — вернём stdout/stderr целиком в error для диагностики
        err = "Unable to parse JSON summary from paper-trade output.\n--- STDOUT ---\n" + stdout_text + "\n--- STDERR ---\n" + stderr_text
        return None, err
    return summary, None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)

    # Хинт по исходнику
    read_ohlcv_header_hint(args.ohlcv)

    # Готовим CSV для записи
    fieldnames: List[str] = [
        "resample", "ema_fast", "ema_slow", "adx_len", "adx_on", "adx_off", "require_di",
        "htf_tf", "htf_ema_fast", "htf_ema_slow",  # зарезервировано под будущее
        "fill_mode", "entry_lag",  # зарезервировано под будущее
        "fee_bps", "slip_bps", "qty",
        "stop_atr", "take_atr", "trail_atr", "atr_len", "priority",  # часть полей пока не используется
        "cooldown_bars", "min_hold_bars",
        "breakeven_rr", "trail_activate_rr",
        "trades", "win_rate", "net_pnl", "avg_pnl",
        "error",
    ]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    rows_written = 0

    keys, grid_iter = to_product(args)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        last_report_ts = time.time()
        count = 0

        for cfg in grid_iter:
            count += 1
            # Запускаем подпроцесс
            summary, err = run_paper_once(args.paper_cli, args.ohlcv, cfg)

            row: Dict[str, Any] = {
                "resample": cfg["resample"],
                "ema_fast": cfg["ema_fast"],
                "ema_slow": cfg["ema_slow"],
                "adx_len": cfg["adx_len"],
                "adx_on": cfg["adx_on"],
                "adx_off": cfg["adx_off"],
                "require_di": cfg["require_di"],
                "htf_tf": cfg["htf_tf"],
                "htf_ema_fast": None,
                "htf_ema_slow": None,
                "fill_mode": None,
                "entry_lag": None,
                "fee_bps": cfg["fee_bps"],
                "slip_bps": cfg["slip_bps"],
                "qty": cfg["qty"],
                "stop_atr": cfg["stop_atr"],
                "take_atr": cfg.get("take_atr"),
                "trail_atr": cfg["trail_atr"],
                "atr_len": None,
                "priority": None,
                "cooldown_bars": cfg["cooldown_bars"],
                "min_hold_bars": cfg["min_hold_bars"],
                "breakeven_rr": cfg["breakeven_rr"],
                "trail_activate_rr": cfg["trail_activate_rr"],
                "trades": None,
                "win_rate": None,
                "net_pnl": None,
                "avg_pnl": None,
                "error": None,
            }

            if err is None and summary is not None:
                try:
                    row["trades"] = int(summary.get("trades"))
                except Exception:
                    row["trades"] = summary.get("trades")
                try:
                    row["win_rate"] = float(summary.get("win_rate"))
                except Exception:
                    row["win_rate"] = summary.get("win_rate")
                try:
                    row["net_pnl"] = float(summary.get("net_pnl"))
                except Exception:
                    row["net_pnl"] = summary.get("net_pnl")
                try:
                    row["avg_pnl"] = float(summary.get("avg_pnl"))
                except Exception:
                    row["avg_pnl"] = summary.get("avg_pnl")
            else:
                row["error"] = err

            writer.writerow(row)
            rows_written += 1

            # прогресс
            if rows_written % 50 == 0:
                last_net = row["net_pnl"]
                last_tr = row["trades"]
                if last_net is None:
                    log(f"Progress: {rows_written} combos, last net=nan (trades={last_tr if last_tr is not None else 0})")
                else:
                    try:
                        log(f"Progress: {rows_written} combos, last net={float(last_net):.4f} (trades={int(last_tr) if last_tr is not None else 0})")
                    except Exception:
                        log(f"Progress: {rows_written} combos, last net={last_net} (trades={last_tr})")

            if args.max_rows is not None and rows_written >= args.max_rows:
                break

    log(f"Saved: {args.out} ({rows_written} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
