# src/presentation/cli/auto_pipeline_cli.py
# -*- coding: utf-8 -*-
"""
Стриминговый раннер для длинных задач (sweep_cli / paper_trade_cmd и пр.):
- потоковый stdout/stderr;
- корректная обработка SIGINT/SIGTERM (мягкая остановка, затем SIGKILL);
- heartbeat, чтобы фронт не думал, что задача зависла;
- pass-through: всё после `--` идёт в дочерний процесс;
- auto-detect модулей: `python -m <module>` если нужно;
- НОВОЕ: умный режим shell. Если обнаружены «склеенные» аргументы в кавычках
  (например, `'--ohlcv ... --resample ...'`) или включён TB_SHELL_MODE=1,
  раннер запустит команду через оболочку (create_subprocess_shell), сохранив
  все гарантии (process group, сигналы, таймаут, heartbeat).

Переменные окружения:
  TB_TIME_BUDGET_SEC  — мягкий таймаут в секундах (если не задан флагом)
  TB_KILL_GRACE_SEC   — грация перед SIGKILL (по умолчанию 15)
  TB_HEARTBEAT_SEC    — период heartbeat (по умолчанию 25)
  TB_DEFAULT_MODULE   — модуль по умолчанию, если команда не распознана
                        (дефолт: 'src.presentation.cli.paper_trade_cmd')
  TB_SHELL_MODE       — '1'/'true'/'yes' — всегда через shell; '0' — всегда exec;
                        'auto' (по умолчанию) — включать shell при «склеенных» аргументах
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import signal
import sys
import threading
import time
from datetime import datetime
from typing import List, Optional


HEART_ICON = "💓"


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class GracefulTerminator:
    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self._install()

    def _install(self) -> None:
        def _handler(signum, frame):
            self.cancel_event.set()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except Exception:
                pass

    def requested(self) -> bool:
        return self.cancel_event.is_set()


class Heartbeat:
    def __init__(self, interval_sec: int = 25) -> None:
        self.interval = max(1, int(interval_sec))
        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thr.start()

    def stop(self) -> None:
        self._stop.set()
        self._thr.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                sys.stdout.write(f"{HEART_ICON}\n")
                sys.stdout.flush()
            except Exception:
                pass


async def _read_stream(stream: asyncio.StreamReader, sink) -> None:
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            try:
                decoded = line.decode(errors="replace")
            except Exception:
                decoded = str(line)
            sink.write(decoded)
            sink.flush()
    except asyncio.CancelledError:
        pass


def _is_python_executable(s: str) -> bool:
    base = os.path.basename(s).lower()
    if s == sys.executable:
        return True
    return base in ("python", "python3") or base.startswith("python3.")


def _looks_like_module(s: str) -> bool:
    if not s:
        return False
    if any(sep in s for sep in ("/", "\\")):
        return False
    if s.endswith((".py", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".exe")):
        return False
    return ("." in s) or (":" in s)


def _token_looks_like_option(token: str) -> bool:
    if not token:
        return False
    t = token.strip()
    return t.startswith("--") or t.startswith("-") or t.startswith("'--") or t.startswith('"--')


def _normalize_cmd(cmd: List[str]) -> List[str]:
    if not cmd:
        return cmd
    first = cmd[0]

    if _is_python_executable(first):
        return cmd

    try:
        if os.path.exists(first):
            return cmd
    except Exception:
        pass

    if _looks_like_module(first):
        module = first
        norm = [sys.executable, "-m", module] + cmd[1:]
        sys.stdout.write(
            f"{_now_ts()} INFO [runner] Executing as module: "
            f"{shlex.join([sys.executable, '-m', module] + cmd[1:])}\n"
        )
        sys.stdout.flush()
        return norm

    return cmd


def _needs_shell(cmd: List[str]) -> bool:
    """Эвристика: если встречаем токены, начинающиеся/заканчивающиеся кавычками
    или явные «склейки» с пробелами, которые должны интерпретироваться оболочкой,
    то включаем shell. Также учитываем TB_SHELL_MODE."""
    mode = os.getenv("TB_SHELL_MODE", "auto").strip().lower()
    if mode in ("1", "true", "yes"):
        return True
    if mode in ("0", "false", "no"):
        return False

    # auto
    for t in cmd:
        st = t.strip()
        if not st:
            continue
        # Если токен уже содержит внешние кавычки (типичный случай с '--ohlcv ...')
        if (st.startswith("'") and st.endswith("'")) or (st.startswith('"') and st.endswith('"')):
            return True
        # Если токен содержит пробелы И выглядит как один аргумент (например значение опции),
        # лучше отдать это на разбор shell (особенно для вложенных командных строк).
        if " " in st and not st.startswith("-"):
            return True
    return False


async def run_streaming(
    cmd: List[str],
    time_budget_sec: Optional[int] = None,
    kill_grace_sec: int = 15,
    env: Optional[dict] = None,
) -> int:
    terminator = GracefulTerminator()

    hb_interval = int(os.getenv("TB_HEARTBEAT_SEC", "25"))
    hb = Heartbeat(interval_sec=hb_interval)
    hb.start()

    start = time.monotonic()
    budget = None if not time_budget_sec or time_budget_sec <= 0 else int(time_budget_sec)

    sys.stdout.write(f"[api] ▶ starting run {datetime.now().strftime('%Y%m%d-%H%M%S')}\n")
    sys.stdout.flush()

    # Нормализация (python -m ...)
    cmd = _normalize_cmd(cmd)

    use_shell = _needs_shell(cmd)
    if use_shell:
        # В shell-ветке собираем строку так, чтобы сохранить уже переданные кавычки.
        # Используем простое объединение через пробел — фронт уже поставил нужные кавычки.
        cmdline = " ".join(cmd)
        sys.stdout.write(f"{_now_ts()} INFO [runner] Using shell mode\n")
        sys.stdout.flush()
        proc = await asyncio.create_subprocess_shell(
            cmdline,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env or os.environ.copy(),
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env or os.environ.copy(),
        )

    tasks = []
    if proc.stdout:
        tasks.append(asyncio.create_task(_read_stream(proc.stdout, sys.stdout)))
    if proc.stderr:
        tasks.append(asyncio.create_task(_read_stream(proc.stderr, sys.stderr)))

    async def _grace_stop(sig: int) -> None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        except Exception:
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                return

    retcode: int
    try:
        while True:
            if terminator.requested():
                sys.stdout.write("[api] cancelled\n")
                sys.stdout.flush()
                await _grace_stop(signal.SIGINT)
                try:
                    retcode = await asyncio.wait_for(proc.wait(), timeout=kill_grace_sec)
                except asyncio.TimeoutError:
                    await _grace_stop(signal.SIGKILL)
                    retcode = -2
                break

            if budget is not None and (time.monotonic() - start) >= budget:
                sys.stdout.write(f"{_now_ts()} INFO [runner] Time budget reached. Stopping child...\n")
                sys.stdout.flush()
                await _grace_stop(signal.SIGTERM)
                try:
                    retcode = await asyncio.wait_for(proc.wait(), timeout=kill_grace_sec)
                except asyncio.TimeoutError:
                    await _grace_stop(signal.SIGKILL)
                    retcode = -2
                break

            try:
                ret = await asyncio.wait_for(proc.wait(), timeout=0.25)
                retcode = int(ret)
                break
            except asyncio.TimeoutError:
                pass

        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        hb.stop()

    return retcode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto_pipeline_cli",
        description="Streaming runner with graceful cancellation/time budget.",
        add_help=True,
    )
    parser.add_argument(
        "--time-budget-sec",
        type=int,
        default=int(os.getenv("TB_TIME_BUDGET_SEC", "0")),
        help="Мягкий лимит по времени (сек). 0 — без лимита.",
    )
    parser.add_argument(
        "--kill-grace-sec",
        type=int,
        default=int(os.getenv("TB_KILL_GRACE_SEC", "15")),
        help="Секунды ожидания после SIGTERM/SIGINT перед SIGKILL.",
    )
    parser.add_argument(
        "--heartbeat-sec",
        type=int,
        default=int(os.getenv("TB_HEARTBEAT_SEC", "25")),
        help="Период сердцебиения в секундах.",
    )

    # Для совместимости — просто съедаем и игнорируем
    parser.add_argument("--mode", default=None, help="Совместимость со старыми лаунчерами. Игнорируется.")
    parser.add_argument("--paper-cli-module", default=None, help="Совместимость. Игнорируется.")

    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help=("Команда для запуска. Передайте через `--`.\n"
              "Пример: -- python -m src.presentation.cli.sweep_cli --ohlcv ...\n"
              "Или только высокоуровневые флаги: -- --sweep-args '...' --rank-args '...'"),
    )
    return parser


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = _build_parser()
    args, unknown = parser.parse_known_args(argv)

    if args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]

    # Сохраним unknown (флаги до `--`), чтобы приклеить их к дочерней команде
    setattr(args, "_unknown", unknown)
    return args


def _compose_child_cmd(args: argparse.Namespace) -> List[str]:
    """
    Если явной команды нет или первый токен выглядит как опция — подставим модуль по умолчанию
    и приклеим unknown + cmd. Это покрывает кейс, когда фронт шлёт:
      <наш раннер> -- --sweep-args '...' --rank-args '...' ...
    """
    default_module = os.getenv("TB_DEFAULT_MODULE", "src.presentation.cli.paper_trade_cmd")
    tokens = list(args.cmd)
    unknown = list(getattr(args, "_unknown", []))

    def _has_executable(ts: List[str]) -> bool:
        if not ts:
            return False
        first = ts[0]
        if _is_python_executable(first):
            return True
        try:
            if os.path.exists(first):
                return True
        except Exception:
            pass
        if _looks_like_module(first):
            return True
        return False

    if _has_executable(tokens) and not (_token_looks_like_option(tokens[0])):
        return tokens + unknown

    sys.stdout.write(
        f"{_now_ts()} INFO [runner] No explicit command detected. Defaulting to module: {default_module}\n"
    )
    sys.stdout.flush()
    return [default_module] + unknown + tokens


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    child_cmd = _compose_child_cmd(args)

    # Покажем, что пришло от фронта и что реально побежит
    if args.cmd:
        sys.stdout.write(f"[auto] ▶ {' '.join(shlex.quote(x) for x in args.cmd)}\n")
    else:
        sys.stdout.write("[auto] ▶ <empty>\n")
    sys.stdout.write(f"{_now_ts()} INFO [runner] Child command: {shlex.join(child_cmd)}\n")
    sys.stdout.flush()

    env = os.environ.copy()
    env["TB_HEARTBEAT_SEC"] = str(args.heartbeat_sec)
    if args.time_budget_sec and args.time_budget_sec > 0:
        env["TB_TIME_BUDGET_SEC"] = str(args.time_budget_sec)

    try:
        ret = asyncio.run(
            run_streaming(
                cmd=child_cmd,
                time_budget_sec=args.time_budget_sec,
                kill_grace_sec=args.kill_grace_sec,
                env=env,
            )
        )
    except KeyboardInterrupt:
        ret = -2

    return int(ret)


if __name__ == "__main__":
    raise SystemExit(main())
