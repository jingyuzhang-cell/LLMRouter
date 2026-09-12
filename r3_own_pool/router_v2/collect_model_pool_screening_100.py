"""Collect a 100-query model-pool capability screening panel.

The screening reuses repeat_index=0 from the completed four-model 400-query
repeat panel and generates one response for each new candidate model. It is a
candidate-pool diagnostic, not a final evaluation set.
"""
import fcntl
import json
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from safetensors import safe_open

from . import run_repeat_stability as engine
from .data import load_cohort, read_rows, sha
from .rescore_glm_pilot import extract_option


ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "router_v2/mmlu_utility_panel_400"
SOURCE = ROOT / "data/repeat_compatibility_400"
OUT = ROOT / "data/model_pool_screening_100"
SLOTS = ["small", "medium", "large", "coder", "math", "reasoning"]

EXISTING = {
    "medium": "Qwen/Qwen2.5-7B-Instruct",
    "large": "Qwen/Qwen2.5-14B-Instruct",
    "coder": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "reasoning": "DeepSeek-R1-Distill-Qwen-14B",
}

NEW_MODELS = {
    "small": {
        "repo": "Qwen/Qwen2.5-1.5B-Instruct",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-1.5B-Instruct"),
    },
    "math": {
        "repo": "Qwen/Qwen2.5-Math-7B-Instruct",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-Math-7B-Instruct"),
    },
}


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def score(source, raw):
    if raw.get("status") == "failed" or not raw.get("answer"):
        return {"quality": None, "evaluation_status": "generation_failure", "parse_succeeded": False}
    option = extract_option(raw["answer"])
    return {
        "quality": float(option == str(source["ground_truth"]).strip().upper()[-1]) if option else 0.0,
        "evaluation_status": "scored" if option else "answer_parse_failed",
        "parse_succeeded": option is not None,
        "extracted_option": option,
    }


def validate_checkpoint(path):
    index_path = path / "model.safetensors.index.json"
    if not index_path.exists():
        if not any(path.glob("*.safetensors")):
            raise ValueError(f"No safetensors checkpoint found: {path}")
        return
    index = json.loads(index_path.read_text())
    found = set()
    for filename in set(index["weight_map"].values()):
        with safe_open(str(path / filename), framework="pt", device="cpu") as stream:
            found.update(stream.keys())
    if not set(index["weight_map"]) <= found:
        raise ValueError(f"Incomplete checkpoint: {path}")


def reuse_existing(panel, cohort):
    audit = {}
    for slot in EXISTING:
        src = SOURCE / f"{slot}.jsonl"
        rows = [
            r for r in read_rows(src)
            if r["query_id"] in panel and int(r["repeat_index"]) == 0
        ]
        if len(rows) != len(panel) or len({r["query_id"] for r in rows}) != len(panel):
            raise ValueError(f"Incomplete reusable rows: {slot}")
        out = OUT / f"{slot}.jsonl"
        if not out.exists():
            with out.open("x") as stream:
                for row in rows:
                    rescored = score(cohort[row["query_id"]], row)
                    if rescored["quality"] is None:
                        raise ValueError(f"Reusable generation failure: {slot}/{row['query_id']}")
                    record = {
                        **row,
                        **rescored,
                        "slot": slot,
                        "screening_repeat_index": 0,
                        "reuse_provenance": {"path": str(src), "sha256": sha(src), "source_repeat_index": 0},
                    }
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        audit[slot] = {"records": len(rows), "source_sha256": sha(src), "source_repeat_index": 0}
    atomic_json(OUT / "REUSE_AUDIT.json", audit)


def collect(slot, panel, cohort):
    config = NEW_MODELS[slot]
    validate_checkpoint(config["path"])
    output_path = OUT / f"{slot}.jsonl"
    attempts_path = OUT / f"{slot}_ATTEMPTS.jsonl"
    rows = read_rows(output_path) if output_path.exists() else []
    spent = {r["query_id"] for r in rows}
    if attempts_path.exists():
        spent.update(r["query_id"] for r in read_rows(attempts_path))
    targets = [row for row in panel.values() if row["query_id"] not in spent]
    status_path = OUT / f"{slot}_STATUS.json"
    if not targets:
        atomic_json(status_path, {"phase": "FINISHED", "records": len(rows), "target": len(panel)})
        return
    with (ROOT / "collect/logs/local_gpu.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (OUT / f"{slot}_VLLM.log").open("a") as log:
            proc = subprocess.Popen([
                "/root/autodl-tmp/r3_venv/bin/vllm", "serve", str(config["path"]),
                "--served-model-name", config["repo"], "--port", "8127",
                "--max-model-len", "8192", "--max-num-seqs", "4",
                "--gpu-memory-utilization", ".92", "--generation-config", "vllm",
            ], stdout=log, stderr=subprocess.STDOUT)
            try:
                atomic_json(status_path, {"phase": "LOADING", "records": len(rows), "target": len(panel)})
                engine.wait_healthy(proc)
                client = {"base_url": "http://127.0.0.1:8127/v1", "api_key": "local", "local": True, "timeout": 600}
                iterator = iter(targets)
                errors = 0
                with output_path.open("a") as output, attempts_path.open("a") as attempts, ThreadPoolExecutor(max_workers=4) as pool:
                    pending = {}

                    def submit():
                        row = next(iterator, None)
                        if row is None:
                            return
                        attempts.write(json.dumps({"query_id": row["query_id"], "screening_repeat_index": 0, "ts": time.time()}) + "\n")
                        attempts.flush()
                        pending[pool.submit(engine.generate, client, config["repo"], row, 0.7, 1.0, 2)] = row

                    for _ in range(4):
                        submit()
                    while pending:
                        ready, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in ready:
                            row = pending.pop(future)
                            raw = future.result()
                            scored = score(cohort[row["query_id"]], raw)
                            record = {
                                **raw,
                                **scored,
                                "query_id": row["query_id"],
                                "slot": slot,
                                "screening_repeat_index": 0,
                                "model": config["repo"],
                                "panel_index": row["panel_index"],
                                "panel_sha256": sha(OUT / "PANEL.jsonl"),
                                "temperature": 0.7,
                                "top_p": 1.0,
                                "ts": time.time(),
                                "transport_budget_spent": 2,
                            }
                            output.write(json.dumps(record, ensure_ascii=False) + "\n")
                            output.flush()
                            rows.append(record)
                            errors = errors + 1 if scored["quality"] is None else 0
                            atomic_json(status_path, {
                                "phase": "COLLECTING",
                                "records": len(rows),
                                "target": len(panel),
                                "consecutive_errors": errors,
                                "parse_failures": sum(r.get("parse_succeeded") is False and r.get("quality") is not None for r in rows),
                            })
                            if errors >= 3:
                                raise RuntimeError(f"{slot} circuit opened after three failures")
                            submit()
                atomic_json(status_path, {
                    "phase": "FINISHED",
                    "records": len(rows),
                    "target": len(panel),
                    "parse_failures": sum(r.get("parse_succeeded") is False for r in rows),
                })
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def aggregate(panel):
    labels = {}
    hashes = {}
    for slot in SLOTS:
        path = OUT / f"{slot}.jsonl"
        rows = read_rows(path)
        if len(rows) != len(panel) or len({r["query_id"] for r in rows}) != len(panel):
            raise ValueError(f"Incomplete aggregate input: {slot}")
        if any(r.get("quality") not in (0, 1) for r in rows):
            raise ValueError(f"Invalid quality: {slot}")
        hashes[slot] = sha(path)
        for row in rows:
            labels.setdefault(row["query_id"], {})[slot] = row["quality"]
    path = OUT / "SCREENING_LABELS.jsonl"
    path.write_text("".join(
        json.dumps({"query_id": qid, "models": labels[qid]}, ensure_ascii=False) + "\n"
        for qid in sorted(labels)
    ))
    atomic_json(OUT / "STATUS.json", {
        "phase": "SCREENING_LABELS_COMPLETE",
        "queries": len(panel),
        "records": len(panel) * len(SLOTS),
        "raw_sha256": hashes,
        "labels_sha256": sha(path),
    })


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cohort, split = load_cohort(ROOT / "data/cohort_full_v2")
    panel_rows = read_rows(PANEL_DIR / "PANEL.jsonl")[:100]
    panel = {r["query_id"]: {**r, "ground_truth": cohort[r["query_id"]]["ground_truth"]} for r in panel_rows}
    if any(qid in split["test"] for qid in panel):
        raise ValueError("Screening panel contains held-out test ids")
    panel_path = OUT / "PANEL.jsonl"
    if not panel_path.exists():
        panel_path.write_text("".join(json.dumps(panel[q], ensure_ascii=False) + "\n" for q in panel))
    elif sha(panel_path) != sha(OUT / "PANEL.jsonl"):
        raise ValueError("Panel changed")
    protocol = {
        "role": "model pool capability screening; not final test",
        "selection": "first 100 queries from frozen MMLU opportunity panel, excluding held-out test ids",
        "models": SLOTS,
        "repeats": 1,
        "reuse": "medium/large/coder/reasoning reuse repeat_index=0 from completed 400-query repeat panel",
        "new_generation": "small/math generated once per query with temperature=0.7",
        "panel_sha256": sha(panel_path),
        "cohort_sha256": sha(ROOT / "data/cohort_full_v2/queries.jsonl"),
        "split_sha256": sha(ROOT / "data/cohort_full_v2/split.json"),
    }
    atomic_json(OUT / "PROTOCOL.json", protocol)
    reuse_existing(panel, cohort)
    collect("small", panel, cohort)
    collect("math", panel, cohort)
    aggregate(panel)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        atomic_json(OUT / "STATUS.json", {"phase": "BLOCKED_ERROR", "error": f"{type(exc).__name__}: {exc}"})
        raise
