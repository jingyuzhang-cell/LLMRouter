"""One-shot repair for arenahard reasoning cells lost to the arrearage outage.

Only cells listed as infrastructure_failure_missing in the verified clean split's
REPAIR_QUEUE.jsonl are regenerated (query only, protocol r3-full-v2 settings:
temperature 0, top_p 1, streamed, max 2 transport attempts per cell). Rows are
appended via storage.append_slot; existing raw rows are never rewritten. Cells
whose canonical row is already successful are skipped, so the script is
idempotent. No ground truth leaves this machine.
"""
import fcntl
import json
import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collect"))
import storage
from models import clients

QUEUE = ROOT / "data/clean_splits_verified_20260910b/REPAIR_QUEUE.jsonl"
OUT = ROOT / "router_v2/generation_repair_20260910"
MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"
SERVING_ID = "deepseek-r1-distill-qwen-14b"


def main():
    for key, value in dotenv_values("/root/.env").items():
        if value is not None:
            os.environ.setdefault(key, value)
    if not os.environ.get("QWEN_API_KEY"):
        raise RuntimeError("QWEN_API_KEY unavailable")

    from .data import load_cohort, sha
    cohort, _ = load_cohort(ROOT / "data/cohort_full_v2")
    queue = [json.loads(l) for l in QUEUE.read_text().split("\n") if l.strip()]
    targets = [r for r in queue if r["reason"] == "infrastructure_failure_missing" and r["slot"] == "reasoning"]
    raw = storage.canonical_rows(ROOT / "data/raw/reasoning.jsonl")
    pending = []
    skipped = []
    for r in targets:
        current = raw.get(r["query_id"])
        if current is not None and current.get("status") in ("ok", "truncated"):
            skipped.append(dict(query_id=r["query_id"], already=current["status"]))
            continue
        source = cohort[r["query_id"]]
        if source["dataset"] != "arenahard":
            raise ValueError(f"Unexpected dataset for {r['query_id']}")
        pending.append(dict(query_id=r["query_id"], partition=r["partition"],
                            query=source["query"], task_type=source["task_type"]))
    print(json.dumps(dict(targets=len(targets), pending=len(pending), skipped=skipped), indent=2), flush=True)

    price = json.loads((ROOT / "collect/price_table.json").read_text())["models"][MODEL]
    started = time.time()
    results = []
    # No collect-line lock: the repeat-panel collector currently holds reasoning.lock
    # but writes to its own isolated output; raw appends are individually flocked
    # (storage.append_slot) and this scope (10 failed cells) cannot collide with it.
    client = clients.make_dashscope_client()

    def on_done(slot_dict, row):
        slot_dict["provenance"] = dict(serving_model=SERVING_ID, slot="reasoning",
                                       protocol="r3-full-v2", revision="provider_unreported",
                                       repair="arrearage_outage_20260910")
        storage.append_slot("reasoning", row["query_id"], MODEL, slot_dict, price)
        results.append(dict(query_id=row["query_id"], partition=row["partition"],
                            status=slot_dict["status"], finish_reason=slot_dict.get("finish_reason"),
                            error=slot_dict.get("error")))
        print(f"[repair] {row['query_id']} -> {slot_dict['status']}", flush=True)

    # Bounded scope: exactly the pending cells, max 2 transport attempts each.
    clients.collect_parallel(client, SERVING_ID, pending, n_threads=4, on_done=on_done)

    OUT.mkdir(parents=True, exist_ok=True)
    audit = dict(
        role="generation_repair_infrastructure_failure_missing",
        queue=str(QUEUE), queue_sha256=sha(QUEUE),
        targets=[dict(query_id=r["query_id"], partition=r["partition"]) for r in targets],
        skipped=skipped, results=results,
        settings=dict(model=SERVING_ID, temperature=0.0, top_p=1.0,
                      max_transport_attempts=2, data_sent="query only", n_threads=4),
        ok=sum(1 for r in results if r["status"] in ("ok", "truncated")),
        failed=sum(1 for r in results if r["status"] == "failed"),
        elapsed_s=round(time.time() - started, 1),
        append_only=True, time=time.time(),
    )
    (OUT / "REPAIR.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(dict(ok=audit["ok"], failed=audit["failed"]), indent=2), flush=True)


if __name__ == "__main__":
    main()
