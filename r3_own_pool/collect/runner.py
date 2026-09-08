"""R3 collection runner (protocol v1.1).

Usage (r3 venv):
  python runner.py --pilot --collect small        # one local slot at a time
  python runner.py --pilot --collect reasoning    # DashScope API slot
  python runner.py --pilot --assemble --metrics   # merge 4 slots + auto quality
  python judge.py --pilot                         # arenahard judge (qwen-max)
  python freeze.py --pilot                        # difficulty/split/utility freeze

Local slots are served one vLLM server at a time (sequential, same GPU); every slot
must complete ALL queries before the next server starts (protocol: no contention).
"""
import argparse
import fcntl
import os
import glob
import json
import pathlib
import subprocess
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from models import clients
import storage
from datasets.sources import load_sources, PILOT_QUOTA, FULL_QUOTA

PORT = 8100
PRICE = json.loads((pathlib.Path(__file__).parent / "price_table.json").read_text())["models"]

SLOTS = {
    "small": dict(model="Qwen/Qwen2.5-3B-Instruct",
                  path=lambda: "/root/autodl-tmp/models/Qwen2.5-3B-Instruct"),
    "medium": dict(model="Qwen/Qwen2.5-7B-Instruct",
                   path=lambda: "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"),
    "large": dict(model="Qwen/Qwen2.5-14B-Instruct",
                  path=lambda: "/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8"),
    "reasoning": dict(model="deepseek-ai/DeepSeek-R1-Distill-Qwen-14B", api=True,
                      serving_id="deepseek-r1-distill-qwen-14b",
                      price_key="deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"),
}
PRICE_KEY = {"small": "Qwen/Qwen2.5-3B-Instruct", "medium": "Qwen/Qwen2.5-7B-Instruct",
             "large": "Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8",
             "reasoning": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"}
POOL = {"small": "Qwen/Qwen2.5-3B-Instruct", "medium": "Qwen/Qwen2.5-7B-Instruct",
        "large": "Qwen/Qwen2.5-14B-Instruct", "reasoning": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"}


def wait_healthy(timeout=1800, process=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"vLLM exited with code {process.returncode}; see logs/vllm_*.log")
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def collect_local(slot):
    cfg = SLOTS[slot]
    model, path = cfg["model"], cfg["path"]()
    rows = [r for r in source_rows() if r["query_id"] not in storage.done_ids(slot, retry_failed=ARGS.retry_failed)]
    if not rows:
        print(f"[{slot}] nothing to do"); return
    cmd = ["/root/autodl-tmp/r3_venv/bin/vllm", "serve", path,
           "--served-model-name", model, "--port", str(PORT),
           "--max-model-len", "16384", "--gpu-memory-utilization", "0.92",
           "--dtype", "auto", "--disable-log-requests"]
    print(f"[{slot}] serving {model} from {path} ({len(rows)} to collect)", flush=True)
    env = {**dict(__import__('os').environ), "VLLM_LOGGING_LEVEL": "WARNING"}
    srv = subprocess.Popen(cmd, env=env, stdout=open(pathlib.Path(__file__).parent / "logs" / f"vllm_{slot}.log", "a"),
                           stderr=subprocess.STDOUT)
    try:
        if not wait_healthy(process=srv):
            srv.kill()
            raise RuntimeError(f"vLLM server for {slot} did not become healthy")
        client = clients.make_local_client(PORT)
        price = PRICE[PRICE_KEY[slot]]
        done = 0
        def cb(slot_dict, row):
            nonlocal done
            slot_dict["provenance"] = dict(serving_model=model, slot=slot, protocol="r3-full-v2" if not ARGS.pilot else "pilot-v1",
                                           actual_weights_path=path, quantization="gptq-int8" if slot == "large" else "unquantized")
            storage.append_slot(slot, row["query_id"], model, slot_dict, price)
            done += 1
            if done % 25 == 0:
                print(f"[{slot}] {done}/{len(rows)}", flush=True)
        clients.collect_parallel(client, model, rows, n_threads=8, on_done=cb)
        storage.update_manifest(slot, model, storage.done_ids(slot).__len__())
    finally:
        srv.terminate()
        try:
            srv.wait(30)
        except subprocess.TimeoutExpired:
            srv.kill()


def collect_api(slot):
    cfg = SLOTS[slot]
    model, serving_id = cfg["model"], cfg.get("serving_id", cfg["model"])
    rows = [r for r in source_rows() if r["query_id"] not in storage.done_ids(slot, retry_failed=ARGS.retry_failed)]
    print(f"[{slot}] {model} via DashScope ({len(rows)} to collect)", flush=True)
    if not rows:
        return
    client = clients.make_dashscope_client()
    price = PRICE[PRICE_KEY[slot]]
    done = 0
    def cb(slot_dict, row):
        nonlocal done
        slot_dict["provenance"] = dict(serving_model=serving_id, slot=slot, protocol="r3-full-v2" if not ARGS.pilot else "pilot-v1", revision="provider_unreported")
        storage.append_slot(slot, row["query_id"], model, slot_dict, price)
        done += 1
        if done % 25 == 0:
            print(f"[{slot}] {done}/{len(rows)}", flush=True)
    clients.collect_parallel(client, serving_id, rows, n_threads=4, on_done=cb)
    storage.update_manifest(slot, model, len(storage.done_ids(slot)))


def source_rows():
    if ARGS.pilot:
        return load_sources(PILOT_QUOTA)
    base = pathlib.Path(__file__).resolve().parents[1] / "data/cohort_full_v2"
    payload = (base / "queries.jsonl").read_bytes()
    import hashlib
    manifest = json.loads((base / "MANIFEST.json").read_text())
    if hashlib.sha256(payload).hexdigest() != manifest["query_sha256"]:
        raise RuntimeError("Frozen query cohort hash mismatch")
    rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    assert len(rows) == manifest["n_queries"] == 5000
    return rows


def _quota():
    return PILOT_QUOTA if ARGS.pilot else FULL_QUOTA


def run_metrics():
    import metrics
    recs = storage.assemble(source_rows(), POOL)
    for rec in recs:
        metrics.evaluate(rec)
    with open(storage.DATA / "assembled.jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    st = Counter((r["dataset"], s["model"], s["status"]) for r in recs for s in r["responses"])
    for k in sorted(st):
        print(k, st[k])
    print("metrics done:", len(recs), "records")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--collect", choices=list(SLOTS))
    ap.add_argument("--retry-failed", action="store_true", help="retry terminal transport failures once; preserve raw history")
    ap.add_argument("--assemble", action="store_true")
    ap.add_argument("--metrics", action="store_true")
    ARGS = ap.parse_args()
    (pathlib.Path(__file__).parent / "logs").mkdir(exist_ok=True)
    if ARGS.collect:
        # One GPU owner across all local slots, one writer per API slot.
        lock_name = "reasoning" if SLOTS[ARGS.collect].get("api") else "local_gpu"
        lock_file = open(pathlib.Path(__file__).parent / "logs" / f"{lock_name}.lock", "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"Collection already running: {lock_name}")
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        (collect_api if SLOTS[ARGS.collect].get("api") else collect_local)(ARGS.collect)
    if ARGS.assemble or ARGS.metrics:
        run_metrics()
