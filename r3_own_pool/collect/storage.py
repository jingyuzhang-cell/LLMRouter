"""Storage: model-major raw JSONL (append, resume-friendly) + listwise assembly.

Layout under r3_own_pool/data/:
  raw/{slot}.jsonl      one line per (query_id, slot) as produced by clients.generate
  assembled.jsonl       per-query listwise records (4 slots)
  manifest_{slot}.json  progress + counts
"""
import hashlib
import fcntl
import json
import os
import pathlib
import time

R = pathlib.Path(__file__).resolve().parents[1]
DATA = R / "data"
RAW = DATA / "raw"


def slot_path(slot):
    RAW.mkdir(parents=True, exist_ok=True)
    return RAW / f"{slot}.jsonl"


def done_ids(slot, retry_failed=False):
    p = slot_path(slot)
    if not p.exists():
        return set()
    rows = canonical_rows(p)
    return {qid for qid, r in rows.items() if not retry_failed or r.get("status") != "failed"}


def canonical_rows(path):
    """Keep successful response if present; otherwise latest terminal attempt."""
    result = {}
    if not pathlib.Path(path).exists():
        return result
    with open(path) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            qid = row["query_id"]
            if qid not in result or result[qid].get("status") != "ok":
                result[qid] = row
    return result


def append_slot(slot, query_id, model, slot_dict, price):
    """Write one completed slot row; cost.usd filled from the frozen price table."""
    row = {"query_id": query_id, "model": model, "ts": time.time(), **slot_dict}
    c = row.get("cost") or {}
    tin, tout = c.get("tokens_input"), c.get("tokens_output")
    if tin is not None and tout is not None:
        c["price_input_per_mtok"] = price["input"]
        c["price_output_per_mtok"] = price["output"]
        c["usd"] = round(tin / 1e6 * price["input"] + tout / 1e6 * price["output"], 8)
    else:
        c["price_input_per_mtok"] = c["price_output_per_mtok"] = c["usd"] = None
    row["cost"] = c
    with open(slot_path(slot), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def update_manifest(slot, model, n_done, notes=""):
    m = dict(slot=slot, model=model, n_done=n_done, updated_at=time.time(), notes=notes)
    (DATA / f"manifest_{slot}.json").write_text(json.dumps(m, indent=2))


def assemble(sources_rows, pool_slots):
    """Merge per-slot raw rows into per-query listwise records (schema v1.1 shape)."""
    per_slot = {}
    for slot, model in pool_slots.items():
        p = slot_path(slot)
        rows = list(canonical_rows(p).values())
        per_slot[slot] = {r["query_id"]: (model, r) for r in rows}
    out = []
    for s in sources_rows:
        rec = dict(query_id=s["query_id"], task_type=s["task_type"], dataset=s["dataset"],
                   difficulty=None, query=s["query"], ground_truth=s["ground_truth"],
                   responses=[])
        for slot in pool_slots:
            model, r = per_slot[slot].get(s["query_id"], (None, None))
            if r is None:
                continue  # validator will reject until all 4 slots collected
            rec["responses"].append(_slot_block(slot, model, r))
        out.append(rec)
    with open(DATA / "assembled.jsonl", "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def _slot_block(slot, model, r):
    lat = r.get("latency") or {}
    lat["source"] = "dashscope_api" if slot == "reasoning" else "local_4090_vllm"
    return dict(model=model, answer=r.get("answer"), thinking=r.get("thinking"),
                quality=dict(auto_score=None, auto_correct=None, judge_score=None,
                             judge=None, final=None, quality_source=None),
                cost=r.get("cost") or {}, latency=lat,
                utility_scores={}, status=r.get("status", "failed"), slot=slot,
                provenance=r.get("provenance", {"protocol": "legacy-pilot", "revision": "unrecorded"}))


def sha256_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
