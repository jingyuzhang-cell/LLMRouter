"""Reuse large/R1 repeats and collect bounded local medium/Coder repeats."""
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
PANEL_DIR = ROOT / "router_v2/repeat_compatibility_115"
OUT = ROOT / "data/repeat_compatibility_115"
SOURCE = ROOT / "data/mmlu_utility_repeats_400_recovered_b"
MODELS = {
    "medium": {
        "repo": "Qwen/Qwen2.5-7B-Instruct",
        "revision": "a09a35458c702b33eeacc393d103063234e8bc28",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-7B-Instruct"),
    },
    "coder": {
        "repo": "Qwen/Qwen2.5-Coder-7B-Instruct",
        "revision": "c03e6d358207e414f1eca0bb1891e29f1db0e242",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct"),
    },
}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


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
    index = json.loads((path / "model.safetensors.index.json").read_text())
    found = set()
    for filename in set(index["weight_map"].values()):
        with safe_open(str(path / filename), framework="pt", device="cpu") as stream:
            found.update(stream.keys())
    if not set(index["weight_map"]) <= found:
        raise ValueError(f"Incomplete checkpoint: {path}")


def reuse(panel, cohort):
    source_status = json.loads((SOURCE / "DISTRIBUTION_STATUS.json").read_text())
    if not source_status["complete"] or source_status["n_complete"] != 400:
        raise ValueError("Prior repeats incomplete")
    audit = {}
    for slot in ("large", "reasoning"):
        source_path = SOURCE / f"{slot}.jsonl"
        if sha(source_path) != source_status["raw_sha256"][slot]:
            raise ValueError(f"Prior {slot} changed")
        rows = [r for r in read_rows(source_path) if r["query_id"] in panel]
        keys = {(r["query_id"], int(r["repeat_index"])) for r in rows}
        if len(rows) != len(keys) or len(rows) != 5 * len(panel):
            raise ValueError(f"Incomplete/duplicate reusable {slot}")
        output = OUT / f"{slot}.jsonl"
        if not output.exists():
            with output.open("x") as stream:
                for row in rows:
                    rescored = score(cohort[row["query_id"]], row)
                    if rescored["quality"] is None:
                        raise ValueError(f"Reusable failure: {slot}/{row['query_id']}")
                    stream.write(json.dumps({**row, **rescored, "reuse_provenance": {
                        "path": str(source_path), "sha256": sha(source_path)
                    }}, ensure_ascii=False) + "\n")
        audit[slot] = {"records": len(rows), "queries": len(panel), "source_sha256": sha(source_path)}
    atomic_json(OUT / "REUSE_AUDIT.json", audit)


def collect(slot, panel, cohort):
    config = MODELS[slot]
    target_count = 5 * len(panel)
    validate_checkpoint(config["path"])
    output_path = OUT / f"{slot}.jsonl"
    attempts_path = OUT / f"{slot}_ATTEMPTS.jsonl"
    rows = read_rows(output_path) if output_path.exists() else []
    spent = {(r["query_id"], int(r["repeat_index"])) for r in rows}
    if attempts_path.exists():
        spent.update((r["query_id"], int(r["repeat_index"])) for r in read_rows(attempts_path))
    targets = [(row, repeat) for row in panel.values() for repeat in range(5)
               if (row["query_id"], repeat) not in spent]
    status_path = OUT / f"{slot}_STATUS.json"
    if not targets:
        atomic_json(status_path, {"phase": "FINISHED", "records": len(rows), "target": target_count})
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
                atomic_json(status_path, {"phase": "LOADING", "records": len(rows), "target": target_count})
                engine.wait_healthy(proc)
                client = {"base_url": "http://127.0.0.1:8127/v1", "api_key": "local", "local": True, "timeout": 600}
                iterator = iter(targets)
                errors = 0
                with output_path.open("a") as output, attempts_path.open("a") as attempts, ThreadPoolExecutor(max_workers=4) as pool:
                    pending = {}

                    def submit():
                        item = next(iterator, None)
                        if item is None:
                            return
                        row, repeat = item
                        attempts.write(json.dumps({"query_id": row["query_id"], "repeat_index": repeat,
                                                   "max_requests": 2, "ts": time.time()}) + "\n")
                        attempts.flush()
                        future = pool.submit(engine.generate, client, config["repo"], row, 0.7, 1.0, 2)
                        pending[future] = (row, repeat)

                    for _ in range(4):
                        submit()
                    while pending:
                        ready, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in ready:
                            row, repeat = pending.pop(future)
                            raw = future.result()
                            scored = score(cohort[row["query_id"]], raw)
                            record = {**raw, **scored, "query_id": row["query_id"], "slot": slot,
                                      "repeat_index": repeat, "model": config["repo"], "revision": config["revision"],
                                      "panel_index": row["panel_index"], "panel_sha256": sha(PANEL_DIR / "PANEL.jsonl"),
                                      "temperature": 0.7, "top_p": 1.0, "ts": time.time(), "transport_budget_spent": 2}
                            output.write(json.dumps(record, ensure_ascii=False) + "\n")
                            output.flush()
                            rows.append(record)
                            errors = errors + 1 if scored["quality"] is None else 0
                            atomic_json(status_path, {"phase": "COLLECTING", "records": len(rows), "target": target_count,
                                                      "consecutive_errors": errors,
                                                      "parse_failures": sum(r.get("parse_succeeded") is False and r.get("quality") is not None for r in rows)})
                            if errors >= 3:
                                raise RuntimeError(f"{slot} circuit opened after three failures")
                            submit()
                atomic_json(status_path, {"phase": "FINISHED", "records": len(rows), "target": target_count,
                                          "parse_failures": sum(r.get("parse_succeeded") is False for r in rows)})
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
    for slot in ("medium", "large", "coder", "reasoning"):
        path = OUT / f"{slot}.jsonl"
        rows = read_rows(path)
        keys = {(r["query_id"], int(r["repeat_index"])) for r in rows}
        target_count = 5 * len(panel)
        if len(rows) != len(keys) or len(rows) != target_count:
            raise ValueError(f"Incomplete aggregate input: {slot}")
        if any(r.get("quality") not in (0, 1) for r in rows):
            raise ValueError(f"Invalid quality: {slot}")
        hashes[slot] = sha(path)
        for qid in panel:
            values = [r["quality"] for r in rows if r["query_id"] == qid]
            if len(values) != 5:
                raise ValueError(f"Expected five values: {slot}/{qid}")
            labels.setdefault(qid, {})[slot] = {"values": values, "mean": sum(values) / 5}
    path = OUT / "EXPECTED_UTILITY_LABELS.jsonl"
    path.write_text("".join(json.dumps({"query_id": qid, "models": labels[qid]}, ensure_ascii=False) + "\n"
                            for qid in sorted(labels)))
    all_rows = [r for slot in ("medium", "large", "coder", "reasoning")
                for r in read_rows(OUT / f"{slot}.jsonl")]
    new_local = sum(r["slot"] in ("medium", "coder") and "reuse_provenance" not in r for r in all_rows)
    atomic_json(OUT / "STATUS.json", {"phase": "REPEAT_LABELS_COMPLETE", "queries": len(panel),
                                      "records": len(all_rows), "raw_sha256": hashes,
                                      "labels_sha256": sha(path), "new_local_generations": new_local,
                                      "reused_generations": len(all_rows) - new_local})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    metadata_path = PANEL_DIR / ("PROTOCOL.json" if (PANEL_DIR / "PROTOCOL.json").exists() else "MANIFEST.json")
    protocol = json.loads(metadata_path.read_text())
    expected_panel_sha = protocol.get("panel_sha256", protocol.get("files", {}).get("PANEL.jsonl"))
    if sha(PANEL_DIR / "PANEL.jsonl") != expected_panel_sha:
        raise ValueError("Panel changed")
    cohort, _ = load_cohort(ROOT / "data/cohort_full_v2")
    panel = {r["query_id"]: {**r, "ground_truth": cohort[r["query_id"]]["ground_truth"]}
             for r in read_rows(PANEL_DIR / "PANEL.jsonl")}
    reuse(panel, cohort)
    collect("medium", panel, cohort)
    collect("coder", panel, cohort)
    aggregate(panel)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        atomic_json(OUT / "STATUS.json", {"phase": "BLOCKED_ERROR", "error": f"{type(exc).__name__}: {exc}"})
        raise
