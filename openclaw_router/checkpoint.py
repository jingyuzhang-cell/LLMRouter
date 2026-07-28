"""Durable success-only experiment checkpoints."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any, Dict

Key = tuple[str, str, int]

def load_successful(path: Path, signature: str) -> Dict[Key, Dict[str, Any]]:
    completed: Dict[Key, Dict[str, Any]] = {}
    if not path.exists(): return completed
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try:
            item=json.loads(line); result=item.get("result")
            if item.get("signature") != signature or not isinstance(result, dict) or result.get("ok") is not True: continue
            completed[(str(item["task_id"]),str(item["model"]),int(item["repeat"]))]=result
        except Exception:
            continue
    return completed

def append_record(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as handle:
        handle.write(json.dumps(record,ensure_ascii=False)+"\n"); handle.flush(); os.fsync(handle.fileno())

def write_progress(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)
