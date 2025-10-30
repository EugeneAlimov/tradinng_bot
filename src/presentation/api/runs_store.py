# src/presentation/api/runs_store.py
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

VAR_DIR = Path(os.getenv("VAR_DIR", "var")) / "runs"
VAR_DIR.mkdir(parents=True, exist_ok=True)

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _json_dump(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def _json_load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def new_run_id() -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{stamp}-{short}"

def run_dir(run_id: str) -> Path:
    return VAR_DIR / run_id

def status_path(run_id: str) -> Path:
    return run_dir(run_id) / "status.json"

def log_path(run_id: str) -> Path:
    return run_dir(run_id) / "pipeline.log"

def artifact_path(run_id: str, name: str) -> Path:
    return run_dir(run_id) / name

def create_run(**kwargs) -> (str, Dict[str, Any]):
    run_id = new_run_id()
    rd = run_dir(run_id)
    rd.mkdir(parents=True, exist_ok=True)
    status = {
        "id": run_id,
        "status": "queued",
        "started_at": _now_iso(),
        "finished_at": None,
        "mode": kwargs.get("mode", "assist"),
        "objective": None,
        "artifacts": {},
        "last_lines": [],
        "extra": kwargs,
    }
    _json_dump(status_path(run_id), status)
    return run_id, status

def update_run(run_id: str, patch: Dict[str, Any]):
    st = get_run(run_id) or {}
    st.update(patch)
    _json_dump(status_path(run_id), st)

def append_log_tail(run_id: str, lines: List[str], tail_keep: int = 30):
    st = get_run(run_id) or {}
    tail = (st.get("last_lines") or []) + lines
    st["last_lines"] = tail[-tail_keep:]
    _json_dump(status_path(run_id), st)

def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    return _json_load(status_path(run_id))

def list_runs(limit: int = 20) -> List[Dict[str, Any]]:
    items = []
    for p in sorted(VAR_DIR.glob("*/status.json"), reverse=True):
        st = _json_load(p)
        if st:
            items.append(st)
        if len(items) >= limit:
            break
    return items
