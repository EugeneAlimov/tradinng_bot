#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Immediate actions & production pipeline runner for our trading bot.
- Day 1: sweep + анализ результатов
- Day 2: robustness + walk-forward + анализ
- Day 3: настройка paper trading и тест
Совместим с текущим CLI (src.presentation.cli.app).
"""

import os
import sys
import json
import time
import csv
import subprocess
from pathlib import Path


# --------- утилиты ---------

def _ensure_dirs():
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("config").mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)
    Path("out").mkdir(parents=True, exist_ok=True)


def _run_cmd(args_list, env_extra=None):
    """
    Безопасный запуск CLI. Возвращает (rc, stdout, stderr).
    """
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    # важное: для нашего проекта нужен PYTHONPATH=.
    env.setdefault("PYTHONPATH", ".")
    proc = subprocess.run(args_list, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def _read_csv_rows(path):
    """
    Возвращает список словарей из CSV или [].
    """
    if not Path(path).exists():
        return []
    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def _to_float_safe(v, default=0.0):
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return default
        return float(v)
    except Exception:
        return default


def _rank_key(row):
    """
    Универсальный ключ сортировки, если нет Calmar внутри CSV.
    Комбинируем score, sharpe, totalPnL и maxDD (меньше по модулю — лучше).
    """
    score = _to_float_safe(row.get("score"), 0.0)
    sharpe = _to_float_safe(row.get("sharpe"), 0.0)
    total = _to_float_safe(row.get("totalPnL"), 0.0)
    maxdd = _to_float_safe(row.get("maxDD"), 0.0)  # обычно отрицательное
    dd_penalty = -abs(maxdd)  # ближе к 0 — лучше
    # взвешенная сумма:
    return (score * 1.0) + (sharpe * 0.8) + (total * 0.5) + (dd_penalty * 0.2)


def _print_table(rows, fields, title=None, limit=None):
    if title:
        print(title)
        print("=" * len(title))
    if limit:
        rows = rows[:limit]
    if not rows:
        print("(no rows)")
        return
    # вычислим ширины
    widths = []
    for f in fields:
        w = max(len(f), max((len(str(r.get(f, ""))) for r in rows), default=0))
        widths.append(w)
    # заголовки
    header = " | ".join(f.ljust(widths[i]) for i, f in enumerate(fields))
    print(header)
    print("-" * len(header))
    # строки
    for r in rows:
        line = " | ".join(str(r.get(f, "")).ljust(widths[i]) for i, f in enumerate(fields))
        print(line)


# --------- День 1 ---------

def execute_day1_plan():
    """
    День 1: полный sweep всех стратегий (авто-реестр) + анализ результатов.
    """
    _ensure_dirs()
    out_csv = "data/comprehensive_sweep.csv"
    cmd = [
        "python", "-m", "src.presentation.cli.app", "sweep",
        "--strategies", "auto",
        "--exmo-pair", "DOGE_EUR",
        "--exmo-candles", "5m:27000",  # ~3 месяца; увеличь при желании
        "--metric", "score",
        "--top-n", "50",
        "--min-trades", "30",
        "--csv-results", out_csv,
    ]
    print("🚀 DAY 1: Running comprehensive sweep...")
    rc, out, err = _run_cmd(cmd)
    if rc != 0:
        print("❌ Sweep failed.")
        print(err.strip())
        return False
    print("✅ Sweep finished. Results ->", out_csv)
    # анализ
    analyze_sweep_results(out_csv)
    return True


def analyze_sweep_results(csv_path="data/comprehensive_sweep.csv"):
    """
    Сортируем результаты sweep, печатаем топ и сохраняем топ-3 в data/top3_strategies.csv.
    """
    rows = _read_csv_rows(csv_path)
    if not rows:
        print("❌ Sweep CSV not found or empty:", csv_path)
        return []

    # нормализуем имена ключевых полей
    for r in rows:
        # иногда колонка 'strategy' называется по-другому — но в нашем CLI это именно 'strategy'
        pass

    # ранжируем
    rows_sorted = sorted(rows, key=_rank_key, reverse=True)

    fields = ["strategy", "trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score"]
    _print_table(rows_sorted, fields, title="🏆 TOP 10 STRATEGIES (by composite rank)", limit=10)

    # сохранение топ-3
    top3 = rows_sorted[:3]
    top3_path = "data/top3_strategies.csv"
    if top3:
        with open(top3_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows_sorted[0].keys())
            writer.writeheader()
            writer.writerows(top3)
        print("✅ Saved top-3 strategies ->", top3_path)
    else:
        print("⚠️ No strategies to save as top-3")

    # Отдельно печать кратко
    print("\n🎯 SELECTED FOR DETAILED ANALYSIS:")
    for r in top3:
        print(" •", r.get("strategy"), "| score:", r.get("score"), "| sharpe:", r.get("sharpe"))
    return [r.get("strategy") for r in top3]


# --------- День 2 ---------

def execute_day2_plan():
    """
    День 2: запускаем robustness для топ-3 и общий walk-forward по выбранным стратегиям.
    """
    _ensure_dirs()
    top3_path = "data/top3_strategies.csv"
    top3 = _read_csv_rows(top3_path)
    if not top3:
        print("❌ No top3_strategies.csv. Run Day 1 first.")
        return False

    strategies = []
    for r in top3:
        sname = r.get("strategy")
        if sname:
            strategies.append(sname)

    # уберём дубликаты и отсортируем по встречаемости
    strategies = list(dict.fromkeys(strategies))
    print("🔍 Day 2 strategies:", ", ".join(strategies))

    # 1) Robustness для каждой
    for s in strategies:
        out_csv = f"data/robustness_{s}.csv"
        cmd = [
            "python", "-m", "src.presentation.cli.app", "robustness",
            "--strategy", s,
            "--exmo-pair", "DOGE_EUR",
            "--exmo-candles", "5m:27000",
            "--robust", "--robust-level", "std", "--samples", "25",
            "--csv-results", out_csv,
        ]
        print(f"🛡️  Running robustness for {s} ...")
        rc, out, err = _run_cmd(cmd)
        if rc != 0:
            print(f"❌ Robustness failed for {s}")
            print(err.strip())
        else:
            print(f"✅ Robustness finished for {s} -> {out_csv}")

    # 2) Walk-Forward для всех выбранных сразу
    wf_csv = "data/wf_results.csv"
    wf_cmd = [
        "python", "-m", "src.presentation.cli.app", "walk-forward",
        "--strategies", ",".join(strategies),
        "--exmo-pair", "DOGE_EUR",
        "--exmo-candles", "5m:27000",
        "--metric", "sharpe",
        "--min-trades", "30",
        "--wf-folds", "6",
        "--wf-train-frac", "0.7",
        "--csv-results", wf_csv
    ]
    print("📈 Running Walk-Forward ...")
    rc, out, err = _run_cmd(wf_cmd)
    if rc != 0:
        print("❌ Walk-Forward failed.")
        print(err.strip())
    else:
        print("✅ Walk-Forward finished ->", wf_csv)

    # анализ robustness-файлов
    analyze_robustness_results()
    return True


def analyze_robustness_results():
    """
    По robustness_* CSV выводим грубую “стабильность” на базе доступных колонок.
    """
    print("\n📊 ROBUSTNESS ANALYSIS")
    print("======================")
    from glob import glob
    files = sorted(glob("data/robustness_*.csv"))
    if not files:
        print("(no robustness CSV files found)")
        return

    summary = []
    for fp in files:
        rows = _read_csv_rows(fp)
        if not rows:
            continue
        sname = Path(fp).stem.replace("robustness_", "")
        # используем 'score' или 'sharpe' если нет score
        vals = []
        for r in rows:
            v = r.get("score")
            if v is None:
                v = r.get("sharpe")
            vals.append(_to_float_safe(v, 0.0))
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        vmin = min(vals)
        vmax = max(vals)
        vmean = sum(vals) / len(vals) if vals else 0.0
        stability = (vmin / vmean) if vmean > 0 else 0.0  # простая эвристика
        summary.append({
            "strategy": sname,
            "mean": f"{vmean:.3f}",
            "min": f"{vmin:.3f}",
            "max": f"{vmax:.3f}",
            "stability": f"{stability:.3f}",
            "samples": len(vals)
        })

    fields = ["strategy", "mean", "min", "max", "stability", "samples"]
    _print_table(summary, fields, title="🛡️  Robustness summary (proxy)")

    if summary:
        out_csv = "data/robust_strategies.csv"
        with open(out_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(summary)
        print("✅ Saved robustness summary ->", out_csv)


# --------- День 3 ---------

def execute_day3_plan():
    """
    День 3: создаём конфиг для paper trading и запускаем тест на час (по желанию).
    """
    _ensure_dirs()
    create_paper_trading_config()
    print("🧪 You can now run a short paper test:")
    print("    python tools/immediate_actions.py --paper-test")
    return True


def create_paper_trading_config():
    """
    Создаём config/paper_trading.json на базе лучшей стратегии из robustness summary
    (или fallback на ema_adx 12/21 если файла нет).
    """
    best_strategy = "ema_adx"
    strat_params = {
        "ema-fast": 12,
        "ema-slow": 21,
        "adx-len": 14,
        "adx-on": 25,
        "adx-off": 16,
        "require-di": True
    }

    rb_csv = "data/robust_strategies.csv"
    rb_rows = _read_csv_rows(rb_csv)
    if rb_rows:
        # сортируем по stability (по убыванию)
        rb_sorted = sorted(rb_rows, key=lambda r: _to_float_safe(r.get("stability"), 0.0), reverse=True)
        cand = rb_sorted[0]
        if cand and cand.get("strategy"):
            best_strategy = cand["strategy"]

    conf = {
        "strategy": best_strategy,
        "pair": "DOGE_EUR",
        "timeframe": "5m",
        "params": strat_params,  # если стратегия иная — CLI всё равно примет только релевантные флаги
        "initial_balance": 1000.0,
        "fee_bps": 10,
        "slip_bps": 2,
        "max_position_pct": 0.25,
        "stop_loss_bps": 300,
        "max_daily_loss_bps": 400,
        "poll_sec": 10,
        "candles_spec": "5m:2500",
        "state_file": "out/paper_state.json",
        "trades_csv": "out/paper_trades.csv",
        "equity_csv": "out/paper_equity.csv",
        "summary_alert": True,
        "debug": False
    }
    with open("config/paper_trading.json", "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)
    print("✅ Created config/paper_trading.json with strategy:", best_strategy)


def run_paper_trading_from_config(cfg_path="config/paper_trading.json", duration_minutes=None):
    """
    Запуск paper-торговли на базе конфига (можно указать duration_minutes для авто-стопа).
    """
    if not Path(cfg_path).exists():
        print("❌ Config not found:", cfg_path)
        return False
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    args = [
        "python", "-m", "src.presentation.cli.app", "trade-live",
        "--mode", "paper",
        "--strategy", cfg.get("strategy", "ema_adx"),
        "--exmo-pair", cfg.get("pair", "DOGE_EUR"),
        "--exmo-candles", cfg.get("candles_spec", "5m:2500"),
        "--initial-balance", str(cfg.get("initial_balance", 1000.0)),
        "--fee-bps", str(cfg.get("fee_bps", 10)),
        "--slip-bps", str(cfg.get("slip_bps", 2)),
        "--max-position-pct", str(cfg.get("max_position_pct", 0.25)),
        "--stop-loss-bps", str(cfg.get("stop_loss_bps", 300)),
        "--max-daily-loss-bps", str(cfg.get("max_daily_loss_bps", 400)),
        "--state-file", cfg.get("state_file", "out/paper_state.json"),
        "--csv-trades", cfg.get("trades_csv", "out/paper_trades.csv"),
        "--csv-equity", cfg.get("equity_csv", "out/paper_equity.csv"),
        "--poll-sec", str(cfg.get("poll_sec", 10)),
    ]

    # Параметры стратегии (EMA/ADX)
    params = cfg.get("params", {})
    if params.get("ema-fast") is not None:
        args += ["--ema-fast", str(params.get("ema-fast"))]
    if params.get("ema-slow") is not None:
        args += ["--ema-slow", str(params.get("ema-slow"))]
    if params.get("adx-len") is not None:
        args += ["--adx-len", str(params.get("adx-len"))]
    if params.get("adx-on") is not None:
        args += ["--adx-on", str(params.get("adx-on"))]
    if params.get("adx-off") is not None:
        args += ["--adx-off", str(params.get("adx-off"))]
    if params.get("require-di") is True:
        args += ["--require-di"]

    if cfg.get("summary_alert"):
        args += ["--summary-alert"]
    if cfg.get("debug"):
        args += ["--debug"]

    print("🚀 Starting paper trading via CLI...")
    print("   ", " ".join(args))

    if duration_minutes is None:
        rc, out, err = _run_cmd(args)
        if rc != 0:
            print("❌ Paper trading failed.")
            print(err.strip())
            return False
        print("✅ Paper trading finished.")
        return True

    # режим с таймером: запускаем и спустя N минут посылаем SIGINT
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        end = time.time() + duration_minutes * 60
        while time.time() < end:
            line = proc.stdout.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
            time.sleep(0.2)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n⏱️  Paper trading stopped by timer.")
    except KeyboardInterrupt:
        proc.terminate()
        print("\n⏹️  Paper trading interrupted by user.")
    return True


# --------- Health check / мастер-план ---------

def quick_health_check():
    """
    Простая проверка: доступность EXMO HTTP, базовые модули, директории.
    """
    _ensure_dirs()
    ok = True

    # 1) модуль CLI
    try:
        __import__("src.presentation.cli.app")
        print("✅ CLI module present")
    except Exception as e:
        print("❌ CLI module import failed:", e)
        ok = False

    # 2) стратегии в реестре (через CLI sweep на 5 баров как smoke?)
    smoke_cmd = [
        "python", "-m", "src.presentation.cli.app", "sweep",
        "--strategies", "auto",
        "--exmo-pair", "DOGE_EUR",
        "--exmo-candles", "5m:200",
        "--metric", "score",
        "--top-n", "3",
        "--min-trades", "1",
        "--csv-results", "data/health_sweep.csv",
    ]
    rc, out, err = _run_cmd(smoke_cmd)
    if rc == 0:
        print("✅ Smoke sweep ok")
    else:
        print("❌ Smoke sweep failed:", err.strip())
        ok = False

    # 3) запись в файлы
    try:
        Path("out/_health_test.txt").write_text("ok", encoding="utf-8")
        print("✅ FS write ok")
    except Exception as e:
        print("❌ FS write failed:", e)
        ok = False

    print("\n🏥 HEALTH:", "GOOD" if ok else "NEEDS ATTENTION")
    return ok


def print_quick_commands():
    print(r"""
🚀 QUICK COMMANDS

# Day 1
python tools/immediate_actions.py --day1

# Day 2
python tools/immediate_actions.py --day2

# Day 3 (create paper config)
python tools/immediate_actions.py --day3

# Paper test from config for 60 minutes
python tools/immediate_actions.py --paper-test --minutes 60

# Full master plan (Day1 -> Day2 -> Day3)
python tools/immediate_actions.py --master

# Health check
python tools/immediate_actions.py --health
""")


def execute_master_plan():
    print("🎯 MASTER PLAN START")
    if not execute_day1_plan():
        print("❌ Day 1 failed. Abort.")
        return
    if not execute_day2_plan():
        print("❌ Day 2 failed. Abort.")
        return
    if not execute_day3_plan():
        print("❌ Day 3 failed.")
        return
    print("✅ MASTER PLAN FINISHED")


# --------- CLI ---------

def _parse_args(argv):
    # минимальный парсер без внешних зависимостей
    flags = {
        "--day1": False,
        "--day2": False,
        "--day3": False,
        "--paper-test": False,
        "--minutes": None,
        "--master": False,
        "--health": False,
        "--help": False,
        "-h": False,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in flags:
            if a == "--minutes":
                if i + 1 < len(argv):
                    flags[a] = int(argv[i + 1])
                    i += 1
                else:
                    flags[a] = 60
            else:
                flags[a] = True
        elif a in ("--help", "-h"):
            flags["--help"] = True
        i += 1
    return flags


def main():
    _ensure_dirs()
    args = _parse_args(sys.argv[1:])
    if args.get("--help") or not any(args.values()):
        print_quick_commands()
        return 0
    if args.get("--health"):
        ok = quick_health_check()
        return 0 if ok else 2
    if args.get("--master"):
        execute_master_plan()
        return 0
    if args.get("--day1"):
        return 0 if execute_day1_plan() else 2
    if args.get("--day2"):
        return 0 if execute_day2_plan() else 2
    if args.get("--day3"):
        return 0 if execute_day3_plan() else 2
    if args.get("--paper-test"):
        minutes = args.get("--minutes") or 60
        return 0 if run_paper_trading_from_config("config/paper_trading.json", minutes) else 2
    print_quick_commands()
    return 0


if __name__ == "__main__":
    sys.exit(main())
