# src/presentation/api/runner.py
import asyncio
import os
import shlex
from pathlib import Path
from typing import Dict, Any

from .runs_store import (
    get_run, update_run, append_log_tail, run_dir, log_path, artifact_path
)
from .notifier import notify_safe

PY = os.getenv("PYTHON_BIN", "python")  # или "python3"
PYTHONPATH_PREFIX = "PYTHONPATH=." if os.name != "nt" else ""  # для Linux/macOS

async def _stream_process(cmd: str, cwd: Path, log_file: Path, run_id: str) -> int:
    """Запускает процесс и стримит stdout->лог и в статус (хвост)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as lf:
        lf.write(f"$ {cmd}\n")
        lf.flush()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": "."},
        )
        lines_buf = []
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            lf.write(text)
            if text.strip():
                lines_buf.append(text.rstrip("\n"))
            if len(lines_buf) >= 10:
                append_log_tail(run_id, lines_buf)
                lines_buf = []
        if lines_buf:
            append_log_tail(run_id, lines_buf)
        rc = await proc.wait()
        lf.write(f"\n[exit {rc}]\n")
        return rc

def _ensure_defaults_for_artifacts(rd: Path) -> Dict[str, str]:
    """Заранее договоримся, куда складывать ключевые файлы."""
    return {
        "champion.json": str(artifact_path(rd.name, "champion.json")),
        "champion_cli.sh": str(artifact_path(rd.name, "champion_cli.sh")),
        "top_ranked.csv": str(artifact_path(rd.name, "top_ranked.csv")),
        "top_robust.csv": str(artifact_path(rd.name, "top_robust.csv")),
        "sweep_full.csv": str(artifact_path(rd.name, "sweep_full.csv")),
    }

async def start_pipeline_run(run_id: str):
    st = get_run(run_id)
    if not st:
        return
    rd = run_dir(run_id)
    artifacts = _ensure_defaults_for_artifacts(rd)
    update_run(run_id, {"status": "running", "artifacts": artifacts})

    # формируем команду auto_pipeline_cli
    extra = st.get("extra", {})
    mode = extra.get("mode", "assist")
    sweep_args = extra.get("sweep_args", "")
    rank_args = extra.get("rank_args", "")
    paper_cli_module = extra.get("paper_cli_module", "src.presentation.cli.paper_trade_cmd")
    forward_ohlcv = extra.get("forward_ohlcv")
    forward_trades_out = extra.get("forward_trades_out")
    forward_extra_args = extra.get("forward_extra_args")
    cache_all = extra.get("cache_all", False)
    wf_splits = extra.get("wf_splits")
    wf_min_trades = extra.get("wf_min_trades")
    notify_chat_id = extra.get("notify_chat_id")

    cmd_parts = [
        f"{PYTHONPATH_PREFIX} {PY} -m src.presentation.cli.auto_pipeline_cli",
        f"--mode {shlex.quote(str(mode))}",
        f"--paper-cli-module {shlex.quote(paper_cli_module)}",
        f"--sweep-args {shlex.quote(sweep_args)}",
        f"--rank-args {shlex.quote(rank_args)}",
        f"--artifact-champion-json {shlex.quote(artifacts['champion.json'])}",
        f"--artifact-champion-cli {shlex.quote(artifacts['champion_cli.sh'])}",
        f"--artifact-top-csv {shlex.quote(artifacts['top_ranked.csv'])}",
        f"--artifact-robust-csv {shlex.quote(artifacts['top_robust.csv'])}",
    ]
    if cache_all:
        cmd_parts.append("--cache-all")
    if wf_splits:
        cmd_parts += ["--wf-splits", str(wf_splits)]
    if wf_min_trades:
        cmd_parts += ["--wf-min-trades", str(wf_min_trades)]
    if forward_ohlcv:
        cmd_parts += ["--forward-ohlcv", shlex.quote(forward_ohlcv)]
    if forward_trades_out:
        cmd_parts += ["--forward-trades-out", shlex.quote(forward_trades_out)]
    if forward_extra_args:
        cmd_parts += ["--forward-extra-args", shlex.quote(forward_extra_args)]

    cmd = " ".join(cmd_parts)

    rc = await _stream_process(cmd=cmd, cwd=Path("."), log_file=log_path(run_id), run_id=run_id)
    finished = {"finished_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z"}

    # прочитаем немного контекста из champion.json (если появился)
    champ_path = Path(artifacts["champion.json"])
    if champ_path.exists():
        try:
            import json
            data = json.loads(champ_path.read_text(encoding="utf-8"))
            objective = data.get("objective")
            finished["objective"] = objective
        except Exception:
            pass

    if rc == 0:
        finished["status"] = "finished"
        await notify_safe(
            notify_chat_id,
            f"✅ Run {run_id} завершён. Артефакты: {artifacts.get('champion.json')}"
        )
    else:
        finished["status"] = "failed"
        await notify_safe(notify_chat_id, f"❌ Run {run_id} упал. См. лог: {log_path(run_id)}")

    update_run(run_id, finished)
