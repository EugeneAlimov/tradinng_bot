# scripts/tg_polling.py
import asyncio
import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import List, Tuple

# ── .env ───────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv, find_dotenv
except Exception:
    load_dotenv = None
    find_dotenv = None

def load_env():
    if load_dotenv and find_dotenv:
        env_path = find_dotenv(usecwd=True)
        if env_path:
            load_dotenv(env_path, override=False)
            print(f"[env] loaded: {env_path}")
        else:
            print(f"[env] .env not found; cwd={os.getcwd()}")

load_env()

# ── TG Token ───────────────────────────────────────────────────────────────────
TG_TOKEN = (os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN") or "").strip()
if not TG_TOKEN:
    raise SystemExit("TELEGRAM_TOKEN is not set (add to .env)")

# ── Defaults (можно переопределять в .env) ─────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]  # корень проекта (из scripts/)
PYTHON = os.getenv("PYTHON", "python")      # можно поставить venv python если нужно

AUTO_MODULE = os.getenv(
    "AUTO_MODULE",
    "src.presentation.cli.auto_pipeline_cli",
)

MODE = os.getenv("AUTO_MODE", "assist")

PAPER_CLI_MODULE = os.getenv(
    "PAPER_CLI_MODULE",
    "src.presentation.cli.paper_trade_cmd",
)

SWEEP_ARGS = os.getenv(
    "SWEEP_ARGS",
    "--ohlcv data/demo_ohlcv_1m.csv "
    "--resample 5min "
    "--ema-fast 12 --ema-slow 21 --adx-len 14 "
    "--adx-on 28,32 --adx-off 18,20,22 --require-di true "
    "--htf-tf 15min,1h "
    "--stop-atr 2.0,2.5,3.0 --take-atr 1.0,1.5,2.0 --trail-atr 1.0,2.0 "
    "--cooldown-bars 0,12,24 "
    "--min-hold-bars 0,6 "
    "--breakeven-rr 0.5,1.0 "
    "--trail-activate-rr 1.5,3.0 "
    "--fee-bps 10 --slip-bps 2 --qty 1 "
    "--out reports/sweep_full.csv"
)

RANK_ARGS = os.getenv(
    "RANK_ARGS",
    "--objective net_pnl --top-k 50 --auto-min-trades "
    "--neighbor-radius 1 --robust-pos-share 0.55 "
    "--out-top reports/top_ranked.csv --out-robust reports/top_robust.csv "
    "--emit-champion-json reports/champion.json "
    "--emit-champion-cli  reports/champion_cli.sh"
)

WF_SPLITS = os.getenv("WF_SPLITS")  # например "5"
WF_MIN_TRADES = os.getenv("WF_MIN_TRADES")  # например "3"

CHAMPION_JSON = os.getenv("CHAMPION_JSON", "reports/champion.json")

# ── Bot (aiogram v3) ───────────────────────────────────────────────────────────
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ── utils ──────────────────────────────────────────────────────────────────────
def build_auto_cmd() -> List[str]:
    cmd = [
        PYTHON, "-m", AUTO_MODULE,
        "--mode", MODE,
        "--paper-cli-module", PAPER_CLI_MODULE,
        "--sweep-args", SWEEP_ARGS,
        "--rank-args", RANK_ARGS,
    ]
    # опционально — walk-forward
    if WF_SPLITS:
        cmd += ["--wf-splits", str(WF_SPLITS)]
    if WF_MIN_TRADES:
        cmd += ["--wf-min-trades", str(WF_MIN_TRADES)]
    return cmd

async def run_and_tail(cmd: List[str], cwd: Path, env: dict, tail_lines: int = 120) -> Tuple[int, str]:
    """Запускает процесс, собирает последний tail вывода и возвращает (code, tail)."""
    q = deque(maxlen=tail_lines)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout
    async for raw in proc.stdout:
        try:
            line = raw.decode("utf-8", errors="ignore").rstrip("\n")
        except Exception:
            line = str(raw)
        q.append(line)
    code = await proc.wait()
    tail = "\n".join(q)
    return code, tail

def code_block(text: str) -> str:
    # Ограничим длину сообщения Телеграма
    max_len = 3800
    if len(text) > max_len:
        text = text[-max_len:]
    return f"```\n{text}\n```"

# ── handlers ───────────────────────────────────────────────────────────────────
@dp.message(Command("start", "help"))
async def cmd_start(m: Message):
    txt = (
        "Привет! Я бот управления автопайплайном.\n\n"
        "Доступные команды:\n"
        "• /run — запустить пайплайн (sweep → rank; WF если задано)\n"
        "• /status — показать текущего чемпиона\n"
        "• /ping — проверка связи\n\n"
        "Параметры берутся из .env: SWEEP_ARGS, RANK_ARGS, PAPER_CLI_MODULE, "
        "WF_SPLITS, WF_MIN_TRADES. Их можно править без изменения кода."
    )
    await m.answer(txt)

@dp.message(Command("ping"))
async def cmd_ping(m: Message):
    await m.answer("pong ✅")

@dp.message(Command("status"))
async def cmd_status(m: Message):
    p = ROOT / CHAMPION_JSON
    if not p.exists():
        await m.answer(f"Файл чемпиона не найден: {p}")
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        await m.answer(f"Не смог прочитать {p}:\n{e}")
        return

    # Пытаемся красиво показать основные метрики
    metric_lines = []
    for k in ("net_pnl", "trades", "win_rate", "avg_pnl"):
        if k in data:
            metric_lines.append(f"{k}: {data[k]}")
    metrics = "\n".join(metric_lines) or "(метрики не найдены)"

    await m.answer(
        "Текущий чемпион:\n"
        + code_block(json.dumps(data, ensure_ascii=False, indent=2))
    )
    await m.answer("Ключевые метрики:\n" + code_block(metrics))

@dp.message(Command("run"))
async def cmd_run(m: Message):
    await m.answer("Запускаю автопайплайн… Это может занять время, пришлю хвост лога по завершении.")
    env = os.environ.copy()
    # гарантируем PYTHONPATH=.
    env["PYTHONPATH"] = env.get("PYTHONPATH") or str(ROOT)

    cmd = build_auto_cmd()
    code, tail = await run_and_tail(cmd, cwd=ROOT, env=env)

    status = "✅ Успех" if code == 0 else f"❌ Код {code}"
    await m.answer(f"{status}. Хвост лога:\n" + code_block(tail))

# ── entrypoint ─────────────────────────────────────────────────────────────────
async def main():
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
