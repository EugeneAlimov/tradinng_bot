# src/presentation/api/routes.py
import os
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from .runs_store import list_runs, get_run, create_run, VAR_DIR
from .runner import start_pipeline_run

router = APIRouter(tags=["runs"])

# ====== Схемы ======
class StartRunRequest(BaseModel):
    mode: str = Field("assist", description="manual|assist|auto (режим auto_pipeline_cli)")
    sweep_args: str = Field(..., description="Полная строка аргументов для sweep_cli (внутри кавычек).")
    rank_args: Optional[str] = Field(
        "--objective net_pnl --top-k 50 --auto-min-trades --neighbor-radius 1 --robust-pos-share 0.55",
        description="Аргументы для rank_sweep_cli."
    )
    paper_cli_module: str = Field(
        "src.presentation.cli.paper_trade_cmd",
        description="Модуль paper trade CLI."
    )
    forward_ohlcv: Optional[str] = Field(
        None, description="Через запятую (для режима auto), например: data/forward_1m_A.csv,data/forward_1m_B.csv"
    )
    forward_trades_out: Optional[str] = Field(
        None, description='Шаблон для трейдов, например: "reports/trades_{i}_{stem}.csv"'
    )
    forward_extra_args: Optional[str] = Field(
        None, description='Напр.: "--trades-out /dev/null"'
    )
    cache_all: bool = Field(False, description="--cache-all для auto_pipeline_cli")
    wf_splits: Optional[int] = Field(None, description="Сколько WF-сплитов нарезать (assist/auto-режимы).")
    wf_min_trades: Optional[int] = Field(None, description="Мин. сделок на сплит (assist/auto-режимы).")
    notify_chat_id: Optional[int] = Field(None, description="Если задан и есть TG_BOT_TOKEN — придёт уведомление.")

class RunItem(BaseModel):
    id: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    mode: str
    objective: Optional[str] = None
    artifacts: Dict[str, str] = {}
    last_lines: Optional[List[str]] = None
    extra: Dict[str, Any] = {}

# ====== Эндпойнты ======
@router.get("/runs", response_model=List[RunItem])
def api_list_runs(limit: int = 20):
    return list_runs(limit=limit)

@router.get("/runs/{run_id}", response_model=RunItem)
def api_get_run(run_id: str):
    st = get_run(run_id)
    if not st:
        raise HTTPException(status_code=404, detail="run_id not found")
    return st

@router.post("/runs", response_model=RunItem, status_code=201)
def api_start_run(req: StartRunRequest, bg: BackgroundTasks):
    run_id, status = create_run(
        mode=req.mode,
        sweep_args=req.sweep_args,
        rank_args=req.rank_args or "",
        paper_cli_module=req.paper_cli_module,
        forward_ohlcv=req.forward_ohlcv,
        forward_trades_out=req.forward_trades_out,
        forward_extra_args=req.forward_extra_args,
        cache_all=req.cache_all,
        wf_splits=req.wf_splits,
        wf_min_trades=req.wf_min_trades,
        notify_chat_id=req.notify_chat_id,
    )
    # фоновый запуск пайплайна (async subprocess)
    bg.add_task(start_pipeline_run, run_id)
    return status

@router.get("/artifacts-root")
def api_artifacts_root():
    return {"var_dir": str(VAR_DIR.resolve())}
