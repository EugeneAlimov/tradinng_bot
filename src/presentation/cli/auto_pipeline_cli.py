# src/presentation/cli/auto_pipeline_cli.py
# -*- coding: utf-8 -*-
"""
Автоматизированный пайплайн:
  1) sweep_cli (перебор конфигов)
  2) rank_sweep_cli (ранжирование, выбор чемпиона, робаст-фильтр)
  3) (опц.) walk-forward: подготовка временных сплитов исходного OHLCV
  4) (опц.) форвард-прогон чемпиона на внешних OHLCV

Примеры:
  python -m src.presentation.cli.auto_pipeline_cli \
    --mode assist \
    --paper-cli-module src.presentation.cli.paper_trade_cmd \
    --sweep-args "--ohlcv data/demo_ohlcv_1m.csv --resample 5min \
                  --ema-fast 12 --ema-slow 21 --adx-len 14 \
                  --adx-on 28,32 --adx-off 18,20,22 --require-di true \
                  --htf-tf 15min,1h \
                  --stop-atr 2.0,2.5,3.0 --take-atr 1.0,1.5,2.0 --trail-atr 1.0,2.0 \
                  --cooldown-bars 0,12,24 \
                  --fee-bps 10 --slip-bps 2 --qty 1 \
                  --out reports/sweep_full.csv \
                  --min-hold-bars 0,6 --breakeven-rr 0.5,1.0 --trail-activate-rr 1.5,3.0" \
    --rank-args  "--objective net_pnl --top-k 50 --auto-min-trades \
                  --neighbor-radius 1 --robust-pos-share 0.55 \
                  --out-top reports/top_ranked.csv --out-robust reports/top_robust.csv" \
    --artifact-champion-json reports/champion.json \
    --artifact-champion-cli  reports/champion_cli.sh \
    --wf-splits 5 --wf-min-trades 3

  python -m src.presentation.cli.auto_pipeline_cli \
    --mode auto \
    --paper-cli-module src.presentation.cli.paper_trade_cmd \
    --sweep-args "--ohlcv data/demo_ohlcv_1m.csv ... --out reports/sweep_full.csv" \
    --rank-args  "--objective net_pnl --top-k 50 --auto-min-trades" \
    --forward-ohlcv "data/forward_1m_A.csv,data/forward_1m_B.csv" \
    --forward-trades-out "reports/trades_{i}_{stem}.csv" \
    --forward-extra-args "--trades-out /dev/null"
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

PRINT_PREFIX = "[auto]"


def _print(msg: str) -> None:
    print(f"{PRINT_PREFIX} {msg}", flush=True)


def _run(cmd: List[str]) -> int:
    _print("▶ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def _tokenize(s: str) -> List[str]:
    return shlex.split(s, posix=True) if s else []


def _has_flag(tokens: List[str], flag: str) -> bool:
    try:
        idx = tokens.index(flag)
        return True
    except ValueError:
        # поддержка формата --flag=value
        return any(t.startswith(flag + "=") for t in tokens)


def _get_flag_value(tokens: List[str], flag: str) -> Optional[str]:
    # поддерживает --flag value и --flag=value
    for i, t in enumerate(tokens):
        if t == flag:
            return tokens[i + 1] if i + 1 < len(tokens) else None
        if t.startswith(flag + "="):
            return t.split("=", 1)[1]
    return None


def _inject_if_missing(tokens: List[str], flag: str, value: Optional[str]) -> None:
    if not _has_flag(tokens, flag):
        if value is None:
            tokens.append(flag)
        else:
            tokens.extend([flag, value])


def _ensure_required_sweep_flags(tokens: List[str]) -> None:
    """Гарантируем, что обязательные флаги присутствуют, иначе sweep_cli ругнётся."""
    required = [
        "--ohlcv",
        "--resample",
        "--ema-fast",
        "--ema-slow",
        "--adx-len",
        "--adx-on",
        "--adx-off",
        "--require-di",
        "--htf-tf",
        "--stop-atr",
        "--trail-atr",
        "--cooldown-bars",
        "--min-hold-bars",
        "--breakeven-rr",
        "--trail-activate-rr",
        "--fee-bps",
        "--slip-bps",
        "--qty",
        "--out",
    ]
    missing = [f for f in required if not _has_flag(tokens, f)]
    if missing:
        # Ничего не подставляем автоматически (кроме paper-cli), просто подскажем.
        _print(
            "⚠ Обнаружены отсутствующие обязательные флаги для sweep_cli: "
            + ", ".join(missing)
        )


def _maybe_attach_paper_cli(tokens: List[str], module: Optional[str]) -> None:
    """Если указали --paper-cli-module и он ещё не в sweep-args, прокинем в sweep_cli как --paper-cli."""
    if module and not _has_flag(tokens, "--paper-cli"):
        tokens.extend(["--paper-cli", module])


def _detect_time_col(df: pd.DataFrame) -> str:
    # Популярные имена
    for c in ["time", "timestamp", "datetime", "date"]:
        if c in df.columns:
            return c
    # Иначе пробуем найти первый столбец, который парсится в даты
    for c in df.columns:
        try:
            s = pd.to_datetime(df[c], errors="raise", utc=False, infer_datetime_format=True)
            return c
        except Exception:
            continue
    # Фолбек — первый столбец
    return df.columns[0]


def _split_ohlcv_for_walkforward(ohlcv_path: str, splits: int, out_dir: Path) -> List[Path]:
    """
    Режем один OHLCV-файл на K последовательных кусков по времени.
    Возвращаем список путей к сохранённым фрагментам.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(ohlcv_path)
    time_col = _detect_time_col(df)
    # сортировка во времени (на всякий случай)
    df = df.sort_values(by=time_col).reset_index(drop=True)

    n = len(df)
    if n == 0:
        _print("⚠ OHLCV пустой — walk-forward пропущен.")
        return []

    splits = max(1, min(int(splits), n))
    # Главное исправление: используем numpy.array_split вместо несуществующего .split()
    idx_chunks = np.array_split(np.arange(n), splits)

    out_paths: List[Path] = []
    for i, idx in enumerate(idx_chunks, 1):
        part = df.iloc[idx]
        if part.empty:
            continue
        stem = Path(ohlcv_path).stem
        out_path = out_dir / f"{stem}_wf_{i}.csv"
        part.to_csv(out_path, index=False)
        out_paths.append(out_path)

    _print(f"Создано WF-сплитов: {len(out_paths)} (из запрошенных {splits}).")
    return out_paths


@dataclass
class Args:
    mode: str
    sweep_args: str
    rank_args: str
    paper_cli_module: Optional[str]
    artifact_champion_json: Optional[str]
    artifact_champion_cli: Optional[str]
    cache_all: bool
    wf_splits: int
    wf_min_trades: int
    forward_ohlcv: Optional[str]
    forward_trades_out: Optional[str]
    forward_extra_args: Optional[str]


def parse_args(argv: List[str]) -> Args:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["manual", "assist", "auto"], required=True)
    p.add_argument("--sweep-args", required=True, help="Строка аргументов для sweep_cli")
    p.add_argument("--rank-args", default="", help="Строка аргументов для rank_sweep_cli")
    p.add_argument("--paper-cli-module", default=None,
                   help="Модуль исполнения бумаги (например, src.presentation.cli.paper_trade_cmd)")

    # артефакты
    p.add_argument("--artifact-champion-json", default=None)
    p.add_argument("--artifact-champion-cli", default=None)

    # кэш и walk-forward
    p.add_argument("--cache-all", action="store_true")
    p.add_argument("--wf-splits", type=int, default=0,
                   help="Сколько временных сплитов подготовить из исходного OHLCV (только подготовка)")
    p.add_argument("--wf-min-trades", type=int, default=0,
                   help="Требование к min_trades для WF-подзадач (сейчас используется как инфо/лог)")

    # форвард-прогон
    p.add_argument("--forward-ohlcv", default=None, help="Список CSV через запятую для форварда")
    p.add_argument("--forward-trades-out", default=None, help="Шаблон для trades CSV: можно {i} и {stem}")
    p.add_argument("--forward-extra-args", default=None, help="Доп. аргументы для paper_trade_cmd на форварде")

    a = p.parse_args(argv)

    return Args(
        mode=a.mode,
        sweep_args=a.sweep_args,
        rank_args=a.rank_args,
        paper_cli_module=a.paper_cli_module,
        artifact_champion_json=a.artifact_champion_json,
        artifact_champion_cli=a.artifact_champion_cli,
        cache_all=bool(a.cache_all),
        wf_splits=int(a.wf_splits or 0),
        wf_min_trades=int(a.wf_min_trades or 0),
        forward_ohlcv=a.forward_ohlcv,
        forward_trades_out=a.forward_trades_out,
        forward_extra_args=a.forward_extra_args,
    )


def main() -> int:
    args = parse_args(sys.argv[1:])

    # 1) S W E E P
    sweep_tokens = _tokenize(args.sweep_args)
    _ensure_required_sweep_flags(sweep_tokens)
    _maybe_attach_paper_cli(sweep_tokens, args.paper_cli_module)

    # Убедимся, что есть --out
    out_csv = _get_flag_value(sweep_tokens, "--out")
    if not out_csv:
        # Если не задано - по умолчанию
        out_csv = "reports/sweep_full.csv"
        sweep_tokens.extend(["--out", out_csv])

    # Запомним путь к OHLCV для WF
    ohlcv_in = _get_flag_value(sweep_tokens, "--ohlcv")

    sweep_cmd = ["python", "-m", "src.presentation.cli.sweep_cli"] + sweep_tokens
    rc = _run(sweep_cmd)
    if rc != 0:
        _print("❌ sweep_cli завершился с ошибкой")
        return rc

    # 2) R A N K
    rank_tokens = _tokenize(args.rank_args)

    # Если пользователь не указал вход явно в rank-args, добавим его
    if not _has_flag(rank_tokens, "--in"):
        rank_tokens.extend(["--in", out_csv])

    # Пробросим артефакты чемпиона
    if args.artifact_champion_json and not _has_flag(rank_tokens, "--emit-champion-json"):
        rank_tokens.extend(["--emit-champion-json", args.artifact_champion_json])
    if args.artifact_champion_cli and not _has_flag(rank_tokens, "--emit-champion-cli"):
        rank_tokens.extend(["--emit-champion-cli", args.artifact_champion_cli])

    rank_cmd = ["python", "-m", "src.presentation.cli.rank_sweep_cli"] + rank_tokens
    rc = _run(rank_cmd)
    if rc != 0:
        _print("❌ rank_sweep_cli завершился с ошибкой")
        return rc

    # 3) Walk-forward (подготовка сплитов исходного OHLCV)
    if args.wf_splits and ohlcv_in:
        wf_dir = Path("reports") / "wf"
        try:
            _split_ohlcv_for_walkforward(ohlcv_in, args.wf_splits, wf_dir)
        except Exception as e:
            _print(f"⚠ Не удалось подготовить WF-сплиты: {e}")

    # 4) Форвард-прогон (auto/assist — если задан forward-ohlcv)
    if args.forward_ohlcv:
        champion_path = args.artifact_champion_json or "reports/champion.json"
        if not Path(champion_path).exists():
            _print(f"⚠ Форвард задан, но не найден champion JSON: {champion_path}")
        else:
            try:
                with open(champion_path, "r", encoding="utf-8") as f:
                    champion = json.load(f)
            except Exception as e:
                _print(f"⚠ Не удалось прочитать чемпиона: {e}")
                champion = None

            if champion:
                # Соберём общий набор аргументов для paper_trade_cmd из чемпиона
                base = [
                    "python", "-m", (args.paper_cli_module or "src.presentation.cli.paper_trade_cmd"),
                    "--resample", str(champion["resample"]),
                    "--ema-fast", str(champion["ema_fast"]),
                    "--ema-slow", str(champion["ema_slow"]),
                    "--adx-len", str(champion["adx_len"]),
                    "--adx-on", str(champion["adx_on"]),
                    "--adx-off", str(champion["adx_off"]),
                    "--require-di", str(champion["require_di"]),
                    "--htf-tf", str(champion["htf_tf"]),
                    "--stop-atr", str(champion["stop_atr"]),
                    "--take-atr", str(champion["take_atr"]),
                    "--trail-atr", str(champion["trail_atr"]),
                    "--cooldown-bars", str(champion["cooldown_bars"]),
                    "--min-hold-bars", str(champion["min_hold_bars"]),
                    "--breakeven-rr", str(champion["breakeven_rr"]),
                    "--trail-activate-rr", str(champion["trail_activate_rr"]),
                    "--fee-bps", str(champion["fee_bps"]),
                    "--slip-bps", str(champion["slip_bps"]),
                    "--qty", str(champion["qty"]),
                ]

                # Разберём доп. аргументы форварда
                extra_tokens = _tokenize(args.forward_extra_args or "")
                extra_has_trades_out = _has_flag(extra_tokens, "--trades-out")

                # Список внешних OHLCV
                fwd_files = [s.strip() for s in args.forward_ohlcv.split(",") if s.strip()]
                for i, path in enumerate(fwd_files, 1):
                    stem = Path(path).stem
                    cmd = base + ["--ohlcv", path]

                    if args.forward_trades_out:
                        # если пользователь уже явно задал --trades-out в extra, не дублируем наш шаблон
                        if not extra_has_trades_out:
                            out_trades = args.forward_trades_out.format(i=i, stem=stem)
                            cmd += ["--trades-out", out_trades]

                    # Приклеим доп. флаги (после наших базовых)
                    cmd += extra_tokens

                    rc = _run(cmd)
                    if rc != 0:
                        _print("❌ команда завершилась с кодом %s" % rc)
                        # продолжаем остальные файлы
            else:
                _print("⚠ Чемпион не загружен — форвард пропущен.")

    # 5) Кэширование результатов (минимальная реализация)
    if args.cache_all:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = Path("reports") / f"auto_run_{ts}"
            run_dir.mkdir(parents=True, exist_ok=True)
            # копируем заметные артефакты, если есть
            for p in [
                out_csv,
                _get_flag_value(rank_tokens, "--out-top") or "reports/top_ranked.csv",
                _get_flag_value(rank_tokens, "--out-robust") or "reports/top_robust.csv",
                args.artifact_champion_json or "reports/champion.json",
                args.artifact_champion_cli or "reports/champion_cli.sh",
            ]:
                if p and Path(p).exists():
                    Path(run_dir / Path(p).name).write_bytes(Path(p).read_bytes())
            _print(f"Кэш сохранён: {run_dir}")
        except Exception as e:
            _print(f"⚠ Не удалось сохранить кэш: {e}")

    if args.artifact_champion_cli and Path(args.artifact_champion_cli).exists():
        _print(f"champion CLI сохранён: {args.artifact_champion_cli}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
