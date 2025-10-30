# src/presentation/api/tg_bot.py
import os
from fastapi import APIRouter, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import Update, Message

from .runs_store import list_runs, get_run, create_run
from .runner import start_pipeline_run

TG_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TG_BOT_TOKEN:
    # Чтобы приложение не падало без токена, создадим "заглушку"
    class _Dummy:
        async def set_webhook(self, *_args, **_kwargs): ...
    bot = _Dummy()  # type: ignore
    dp = Dispatcher()
else:
    bot = Bot(TG_BOT_TOKEN)
    dp = Dispatcher()

router = APIRouter(prefix="/tg", tags=["telegram"])

@dp.message(F.text == "/start")
async def cmd_start(m: Message):
    await m.answer(
        "Привет! Команды:\n"
        "/runs — последние запуски\n"
        "/run <id> — статус\n"
        "/start_run — запустить пайплайн с дефолтными аргументами"
    )

@dp.message(F.text == "/runs")
async def cmd_runs(m: Message):
    items = list_runs(limit=5)
    if not items:
        return await m.answer("Запусков пока нет.")
    text = "\n".join(f"{it['id']} · {it['status']} · {it.get('objective','-')}" for it in items)
    await m.answer(text)

@dp.message(F.text.startswith("/run "))
async def cmd_run(m: Message):
    try:
        _, rid = m.text.split(maxsplit=1)
    except Exception:
        return await m.answer("Использование: /run <id>")
    st = get_run(rid)
    if not st:
        return await m.answer("Не нашёл такой run_id")
    await m.answer(
        f"Run {rid}\nstatus={st['status']}\n"
        f"mode={st.get('mode')}\n"
        f"artifacts={list((st.get('artifacts') or {}).keys())}"
    )

@dp.message(F.text == "/start_run")
async def cmd_start_run(m: Message):
    # дефолтные аргументы — отредактируй под себя
    run_id, status = create_run(
        mode="assist",
        sweep_args=(
            "--ohlcv data/demo_ohlcv_1m.csv --resample 5min "
            "--ema-fast 12 --ema-slow 21 --adx-len 14 "
            "--adx-on 28,32 --adx-off 18,20,22 --require-di true "
            "--htf-tf 15min,1h "
            "--stop-atr 2.0,2.5,3.0 --take-atr 1.0,1.5,2.0 --trail-atr 1.0,2.0 "
            "--cooldown-bars 0,12,24 "
            "--fee-bps 10 --slip-bps 2 --qty 1 --out reports/sweep_full.csv"
        ),
        rank_args=(
            "--objective net_pnl --top-k 50 --auto-min-trades "
            "--neighbor-radius 1 --robust-pos-share 0.55 "
            "--out-top reports/top_ranked.csv --out-robust reports/top_robust.csv"
        ),
        paper_cli_module="src.presentation.cli.paper_trade_cmd",
        notify_chat_id=m.chat.id,
    )
    # стартуем в фоне
    await start_pipeline_run(run_id)
    await m.answer(f"Запущено. run_id={run_id}")

@router.post("/webhook")
async def telegram_webhook(request: Request):
    if not isinstance(bot, Bot):
        return {"ok": True}
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}
