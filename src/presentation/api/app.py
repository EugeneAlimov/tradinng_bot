from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import time
from collections import deque
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CHAMPION_JSON = REPORTS_DIR / "champion.json"

API_TITLE = "Trading Bot API"
API_VERSION = "0.1.0"

def _sanitize_args(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\\\n", " ")
    s = re.sub(r"\\(?=\S)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _ensure_sweep_required_flags(s: str) -> str:
    def has(flag: str) -> bool:
        return re.search(rf"(?:^|\s){re.escape(flag)}(?:\s|$)", s) is not None
    parts = [s]
    if not has("--min-hold-bars"):
        parts.append("--min-hold-bars 0,6")
    if not has("--breakeven-rr"):
        parts.append("--breakeven-rr 0.5,1.0")
    if not has("--trail-activate-rr"):
        parts.append("--trail-activate-rr 1.5,3.0")
    return " ".join(parts)

def _now_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

class RunRequest(BaseModel):
    mode: str = Field("assist", pattern=r"^(manual|assist|auto)$")
    sweep_args: str
    rank_args: str
    wf_splits: int = 0
    wf_min_trades: int = 0
    champion_json: Optional[str] = None

class RunStatus(BaseModel):
    run_id: Optional[str] = None
    running: bool = False
    returncode: Optional[int] = None

class RunManager:
    def __init__(self) -> None:
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.buffer = deque(maxlen=2000)
        self.run_id: Optional[str] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._champion_path: Path = DEFAULT_CHAMPION_JSON

    def _champion_file(self) -> Path:
        return self._champion_path

    async def start(self, req: RunRequest) -> str:
        async with self._lock:
            if self.proc and self.proc.returncode is None:
                raise HTTPException(409, "Run already in progress")

            sweep = _sanitize_args(req.sweep_args)
            sweep = _ensure_sweep_required_flags(sweep)

            rank = _sanitize_args(req.rank_args)

            champion_path = Path(req.champion_json) if req.champion_json else DEFAULT_CHAMPION_JSON
            self._champion_path = champion_path
            if "--emit-champion-json" not in rank:
                rank += f" --emit-champion-json {champion_path.as_posix()}"
            if "--emit-champion-cli" not in rank:
                rank += f" --emit-champion-cli {(REPORTS_DIR / 'champion_cli.sh').as_posix()}"

            cmd = (
                "PYTHONPATH=. "
                "python -m src.presentation.cli.auto_pipeline_cli "
                f"--mode {req.mode} "
                "--paper-cli-module src.presentation.cli.paper_trade_cmd "
                f"--sweep-args \"{sweep}\" "
                f"--rank-args \"{rank}\" "
            )
            if req.wf_splits:
                cmd += f"--wf-splits {int(req.wf_splits)} "
            if req.wf_min_trades:
                cmd += f"--wf-min-trades {int(req.wf_min_trades)} "
            cmd += "--cache-all "

            env = os.environ.copy()
            env["PYTHONPATH"] = "."

            self.run_id = _now_id()
            await self.queue.put(f"[api] ▶ starting run {self.run_id}")
            self.proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._reader_task = asyncio.create_task(self._read_stdout())
            return self.run_id

    async def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            async for raw in self.proc.stdout:
                line = raw.decode(errors="ignore").rstrip("\n")
                self.buffer.append(line)
                await self.queue.put(line)
        finally:
            rc = await self.proc.wait()
            msg = f"[api] process finished with code {rc}"
            self.buffer.append(msg)
            await self.queue.put(msg)

    async def cancel(self) -> None:
        async with self._lock:
            if not self.proc or self.proc.returncode is not None:
                return
            self.proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            await self.queue.put("[api] cancelled")

    def status(self) -> RunStatus:
        running = self.proc is not None and self.proc.returncode is None
        return RunStatus(
            run_id=self.run_id,
            running=running,
            returncode=None if running else (None if not self.proc else self.proc.returncode),
        )

    def latest_champion(self) -> dict:
        p = self._champion_file()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {"error": f"failed to read champion: {e}", "path": p.as_posix()}

    async def sse_stream(self) -> AsyncIterator[str]:
        for line in list(self.buffer):
            yield f"data: {line}\n\n"
        while True:
            try:
                line = await asyncio.wait_for(self.queue.get(), timeout=15)
                yield f"data: {line}\n\n"
            except asyncio.TimeoutError:
                yield "data: 💓\n\n"

app = FastAPI(title=API_TITLE, version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = RunManager()

@app.get("/api/health")
def health():
    return {"ok": True, "cwd": str(ROOT), "version": API_VERSION}

@app.post("/api/run")
async def api_run(req: RunRequest):
    run_id = await manager.start(req)
    return {"ok": True, "run_id": run_id}

@app.post("/api/cancel")
async def api_cancel():
    await manager.cancel()
    return {"ok": True}

@app.get("/api/status", response_model=RunStatus)
def api_status():
    return manager.status()

@app.get("/api/champion")
def api_champion():
    return JSONResponse(manager.latest_champion())

@app.get("/api/logs")
async def api_logs():
    return StreamingResponse(manager.sse_stream(), media_type="text/event-stream")
