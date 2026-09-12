"""Collect a stratified model-pool capability screening panel.

This is a pilot diagnostic, not Router training data. It freezes 60 knowledge,
60 math, and 60 code train queries, reuses existing full-cohort raw responses
where the requested model identity matches, and collects one local vLLM response
for the newly introduced slots.
"""
import argparse
import fcntl
import hashlib
import json
import os
import random
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI
from safetensors import safe_open

from . import run_repeat_stability as repeat_engine
from .data import load_cohort, read_rows, sha
from collect import storage
from collect.models import clients


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/model_pool_screening_stratified_180"
PANEL_PATH = DATA / "PANEL.jsonl"
PORT = 8127
SLOTS = ["small", "medium", "large", "coder", "math", "reasoning"]

REUSE = {
    "medium": {"model": "Qwen/Qwen2.5-7B-Instruct", "raw": ROOT / "data/raw/medium.jsonl"},
    "large": {"model": "Qwen/Qwen2.5-14B-Instruct", "raw": ROOT / "data/raw/large.jsonl"},
    "reasoning": {
        "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        "raw": ROOT / "data/raw/reasoning.jsonl",
    },
}

LOCAL = {
    "small": {
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-1.5B-Instruct"),
        "price": {"input": 0.03, "output": 0.12},
    },
    "coder": {
        "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct"),
        "price": {"input": 0.07, "output": 0.28},
    },
    "math": {
        "model": "Qwen/Qwen2.5-Math-7B-Instruct",
        "path": Path("/root/autodl-tmp/models/Qwen2.5-Math-7B-Instruct"),
        "price": {"input": 0.07, "output": 0.28},
    },
}


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def validate_checkpoint(path):
    index_path = path / "model.safetensors.index.json"
    files = None
    if index_path.exists():
        index = json.loads(index_path.read_text())
        files = sorted(set(index["weight_map"].values()))
    else:
        files = [p.name for p in path.glob("*.safetensors")]
    if not files:
        raise ValueError(f"No safetensors checkpoint found: {path}")
    for filename in files:
        with safe_open(str(path / filename), framework="pt", device="cpu") as stream:
            _ = len(stream.keys())


def freeze_panel(seed=20260912):
    cohort, split = load_cohort(ROOT / "data/cohort_full_v2")
    train = set(split["train"])
    rng = random.Random(seed)

    def sample(dataset, n, domain):
        ids = [qid for qid, row in cohort.items() if qid in train and row["dataset"] == dataset]
        ids = sorted(ids)
        rng.shuffle(ids)
        rows = []
        for qid in ids[:n]:
            rows.append({**cohort[qid], "domain": domain, "stratum": f"{domain}:{dataset}"})
        return rows

    panel = []
    panel += sample("mmlupro", 60, "knowledge")
    panel += sample("gsm8k", 60, "math")
    panel += sample("humaneval", 30, "code")
    panel += sample("mbpp", 30, "code")
    for i, row in enumerate(panel):
        row["panel_index"] = i
    if len(panel) != 180 or len({r["query_id"] for r in panel}) != 180:
        raise ValueError("Bad stratified panel construction")
    return panel, cohort, split


def score_row(source, raw):
    status = raw.get("status", "failed")
    scored = repeat_engine.score_answer(source, raw.get("answer"), status)
    if scored.get("quality") is None and scored.get("evaluation_status") in {
        "dependency_review_required",
        "environment_review_required",
    }:
        scored = {**scored, "quality": 0.0, "screening_quality_policy": "unsupported_dependency_or_environment_scores_zero"}
    if scored.get("quality") is None:
        return scored
    scored["quality"] = float(scored["quality"])
    return scored




def generate_nonstream(client, model, row, max_retries=3):
    last_err = None
    for attempt in range(max_retries):
        try:
            t0 = time.perf_counter()
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": row["query"]}],
                temperature=0.0,
                top_p=1.0,
                max_tokens=clients.MAX_TOKENS[row["task_type"]],
                stream=False,
            )
            total = time.perf_counter() - t0
            choice = resp.choices[0]
            message = choice.message
            answer = (message.content or "").strip() or None
            thinking = getattr(message, "reasoning_content", None)
            usage = resp.usage.model_dump() if resp.usage else {}
            out_tok = usage.get("completion_tokens")
            in_tok = usage.get("prompt_tokens")
            estimated = out_tok is None or in_tok is None
            if out_tok is None:
                out_tok = len((answer or "") + (thinking or "")) // 3
            return {
                "answer": answer,
                "thinking": thinking,
                "finish_reason": choice.finish_reason,
                "requested_max_tokens": clients.MAX_TOKENS[row["task_type"]],
                "cost": {"tokens_input": in_tok, "tokens_output": out_tok, "tokens_estimated": estimated},
                "latency": {
                    "total_ms": round(total * 1000, 1),
                    "ttft_ms": None,
                    "decode_ms": None,
                    "tokens_per_second": round(out_tok / total, 1) if total > 0 and out_tok is not None else None,
                },
                "status": "ok" if choice.finish_reason == "stop" and answer else ("truncated" if choice.finish_reason == "length" else "failed"),
            }
        except Exception as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    return {
        "answer": None,
        "thinking": None,
        "finish_reason": None,
        "cost": {"tokens_input": None, "tokens_output": None, "tokens_estimated": True},
        "latency": {"total_ms": None, "ttft_ms": None, "decode_ms": None, "tokens_per_second": None},
        "status": "failed",
        "error": str(last_err),
    }

def apply_price(row, price):
    cost = row.setdefault("cost", {})
    tin, tout = cost.get("tokens_input"), cost.get("tokens_output")
    if tin is not None and tout is not None:
        cost["price_input_per_mtok"] = price["input"]
        cost["price_output_per_mtok"] = price["output"]
        cost["usd"] = round(tin / 1e6 * price["input"] + tout / 1e6 * price["output"], 8)
    else:
        cost["price_input_per_mtok"] = None
        cost["price_output_per_mtok"] = None
        cost["usd"] = None


def reuse_slot(slot, panel, cohort):
    raw = storage.canonical_rows(REUSE[slot]["raw"])
    records = []
    for row in panel:
        qid = row["query_id"]
        if qid not in raw:
            raise ValueError(f"Missing reusable raw row: {slot}/{qid}")
        source = cohort[qid]
        old = raw[qid]
        if old.get("model") != REUSE[slot]["model"]:
            raise ValueError(f"Reusable model mismatch: {slot}/{qid}: {old.get('model')}")
        scored = score_row(source, old)
        record = {
            **old,
            **scored,
            "slot": slot,
            "dataset": source["dataset"],
            "task_type": source["task_type"],
            "domain": row["domain"],
            "stratum": row["stratum"],
            "panel_index": row["panel_index"],
            "screening_repeat_index": 0,
            "reuse_provenance": {
                "path": str(REUSE[slot]["raw"]),
                "sha256": sha(REUSE[slot]["raw"]),
                "limitation": "legacy full-cohort raw response; original temperature/top_p fields not recorded",
            },
        }
        if record.get("quality") is None:
            raise ValueError(f"Unscored reusable row: {slot}/{qid}")
        records.append(record)
    write_jsonl(DATA / f"{slot}.jsonl", records)
    return {"records": len(records), "raw_sha256": sha(REUSE[slot]["raw"])}


PILOT_MAX_NEW_TOKENS = {"knowledge": 1024, "math": 512, "code": 1024}


def generate_transformers(model, tokenizer, row):
    import torch

    started = time.perf_counter()
    messages = [{"role": "user", "content": row["query"]}]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_tokens = int(inputs["input_ids"].shape[-1])
    max_new = PILOT_MAX_NEW_TOKENS[row["task_type"]]
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_tokens = output[0, input_tokens:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    total = time.perf_counter() - started
    finish_reason = "length" if int(new_tokens.numel()) >= max_new else "stop"
    return {
        "answer": text if text else None,
        "thinking": None,
        "finish_reason": finish_reason,
        "requested_max_tokens": max_new,
        "cost": {"tokens_input": input_tokens, "tokens_output": int(new_tokens.numel()), "tokens_estimated": False},
        "latency": {
            "total_ms": round(total * 1000, 1),
            "ttft_ms": None,
            "decode_ms": None,
            "tokens_per_second": round(float(new_tokens.numel()) / total, 1) if total > 0 else None,
        },
        "status": "ok" if text else "failed",
    }


def local_targets(slot, panel):
    output = DATA / f"{slot}.jsonl"
    done = set()
    if output.exists():
        done = {r["query_id"] for r in read_rows(output) if r.get("quality") is not None}
    return [row for row in panel if row["query_id"] not in done]


def collect_local_slot(slot, panel, cohort, workers):
    del workers
    cfg = LOCAL[slot]
    validate_checkpoint(cfg["path"])
    targets = local_targets(slot, panel)
    status_path = DATA / f"{slot}_STATUS.json"
    output = DATA / f"{slot}.jsonl"
    attempts_path = DATA / f"{slot}_ATTEMPTS.jsonl"
    if not targets:
        atomic_json(status_path, {"phase": "FINISHED", "records": len(read_rows(output)), "target": len(panel)})
        return
    lock_path = ROOT / "collect/logs/local_gpu.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic_json(status_path, {"phase": "LOADING_TRANSFORMERS", "records": len(read_rows(output)) if output.exists() else 0, "target": len(panel)})
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        tokenizer = AutoTokenizer.from_pretrained(str(cfg["path"]), trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            str(cfg["path"]),
            torch_dtype=torch.bfloat16,
            device_map="cuda",
            trust_remote_code=True,
        )
        model.eval()
        completed = len(read_rows(output)) if output.exists() else 0
        try:
            smoke = generate_transformers(model, tokenizer, targets[0])
            smoke_score = score_row(cohort[targets[0]["query_id"]], smoke)
            with attempts_path.open("a") as attempts:
                attempts.write(json.dumps({
                    "kind": "smoke",
                    "slot": slot,
                    "query_id": targets[0]["query_id"],
                    "ts": time.time(),
                    **smoke,
                    **smoke_score,
                }, ensure_ascii=False) + "\n")
            if smoke_score.get("quality") is None:
                raise RuntimeError(f"{slot} transformers smoke failed: {smoke.get('status')}")
            with output.open("a") as stream, attempts_path.open("a") as attempts:
                for source_row in targets:
                    slot_dict = generate_transformers(model, tokenizer, source_row)
                    scored = score_row(cohort[source_row["query_id"]], slot_dict)
                    record = {
                        "query_id": source_row["query_id"],
                        "model": cfg["model"],
                        "slot": slot,
                        "dataset": source_row["dataset"],
                        "task_type": source_row["task_type"],
                        "domain": source_row["domain"],
                        "stratum": source_row["stratum"],
                        "panel_index": source_row["panel_index"],
                        "screening_repeat_index": 0,
                        "temperature": 0.0,
                        "top_p": 1.0,
                        "backend": "transformers",
                        "ts": time.time(),
                        **slot_dict,
                        **scored,
                    }
                    apply_price(record, cfg["price"])
                    if record.get("quality") is None:
                        attempts.write(json.dumps(record, ensure_ascii=False) + "\n")
                        attempts.flush()
                        atomic_json(status_path, {
                            "phase": "COLLECTING",
                            "records": completed,
                            "target": len(panel),
                            "attempt_failures": sum(1 for r in read_rows(attempts_path) if r.get("quality") is None),
                            "last_failure": {"query_id": source_row["query_id"], "status": record.get("status")},
                        })
                        continue
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                    completed += 1
                    if completed % 10 == 0 or completed == len(panel):
                        print(f"[{slot}] {completed}/{len(panel)}", flush=True)
                    atomic_json(status_path, {
                        "phase": "COLLECTING",
                        "records": completed,
                        "target": len(panel),
                        "attempt_failures": sum(1 for r in read_rows(attempts_path) if r.get("quality") is None),
                    })
            atomic_json(status_path, {"phase": "FINISHED", "records": len(read_rows(output)), "target": len(panel)})
        finally:
            del model
            torch.cuda.empty_cache()

def aggregate(panel):
    matrix = {}
    raw_hashes = {}
    for slot in SLOTS:
        path = DATA / f"{slot}.jsonl"
        rows = read_rows(path)
        by_id = {r["query_id"]: r for r in rows if r.get("quality") is not None}
        if len(by_id) != len(panel):
            missing = sorted({r["query_id"] for r in panel} - set(by_id))
            raise ValueError(f"Incomplete slot {slot}: {len(by_id)}/{len(panel)} missing={missing[:5]}")
        raw_hashes[slot] = sha(path)
        for qid, row in by_id.items():
            matrix.setdefault(qid, {})[slot] = {
                "quality": float(row["quality"]),
                "cost_usd": (row.get("cost") or {}).get("usd"),
                "latency_ms": (row.get("latency") or {}).get("total_ms"),
                "status": row.get("status"),
                "evaluation_status": row.get("evaluation_status"),
            }
    labels = []
    panel_by_id = {r["query_id"]: r for r in panel}
    for qid in [r["query_id"] for r in panel]:
        src = panel_by_id[qid]
        labels.append({
            "query_id": qid,
            "panel_index": src["panel_index"],
            "dataset": src["dataset"],
            "task_type": src["task_type"],
            "domain": src["domain"],
            "stratum": src["stratum"],
            "models": matrix[qid],
        })
    labels_path = DATA / "SCREENING_LABELS.jsonl"
    write_jsonl(labels_path, labels)
    atomic_json(DATA / "STATUS.json", {
        "phase": "SCREENING_LABELS_COMPLETE",
        "queries": len(panel),
        "records": len(panel) * len(SLOTS),
        "slots": SLOTS,
        "raw_sha256": raw_hashes,
        "labels_sha256": sha(labels_path),
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", choices=["panel", "reuse", "small", "coder", "math", "aggregate", "all"], default="all")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    panel, cohort, split = freeze_panel()
    if any(r["query_id"] in set(split["test"]) for r in panel):
        raise ValueError("Screening panel contains test ids")
    if PANEL_PATH.exists():
        old = read_rows(PANEL_PATH)
        if hashlib.sha256(PANEL_PATH.read_bytes()).hexdigest() != hashlib.sha256(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in panel).encode()
        ).hexdigest():
            raise ValueError("Existing panel changed")
    else:
        write_jsonl(PANEL_PATH, panel)
    atomic_json(DATA / "PROTOCOL.json", {
        "role": "stratified model-pool capability screening; not Router training data and not final test",
        "selection": "train split only: 60 MMLU-Pro knowledge, 60 GSM8K math, 30 HumanEval + 30 MBPP code",
        "seed": 20260912,
        "queries": len(panel),
        "slots": SLOTS,
        "slot_models": {slot: (LOCAL.get(slot) or REUSE.get(slot))["model"] for slot in SLOTS},
        "new_generation": "small/coder/math generated once locally with Transformers, temperature=0.0, top_p=1.0",
        "pilot_max_new_tokens": {"knowledge": 1024, "math": 512, "code": 1024},
        "reuse": "medium/large/reasoning reuse existing full-cohort raw responses when model identity matches",
        "limitations": [
            "Legacy reused raw rows do not record temperature/top_p, so this is a capability screening pilot.",
            "1.5B cost is a documented proxy for later utility analysis, not measured billing.",
            "Code answers requiring unsupported third-party dependencies or unavailable environment support score zero for this screening matrix; flags are retained.",
        ],
        "panel_sha256": sha(PANEL_PATH),
        "cohort_sha256": sha(ROOT / "data/cohort_full_v2/queries.jsonl"),
        "split_sha256": sha(ROOT / "data/cohort_full_v2/split.json"),
    })
    if args.only in ("panel",):
        return
    if args.only in ("reuse", "all"):
        audit = {slot: reuse_slot(slot, panel, cohort) for slot in REUSE}
        atomic_json(DATA / "REUSE_AUDIT.json", audit)
    if args.only in ("small", "all"):
        collect_local_slot("small", panel, cohort, args.workers)
    if args.only in ("coder", "all"):
        collect_local_slot("coder", panel, cohort, args.workers)
    if args.only in ("math", "all"):
        collect_local_slot("math", panel, cohort, args.workers)
    if args.only in ("aggregate", "all"):
        aggregate(panel)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        DATA.mkdir(parents=True, exist_ok=True)
        atomic_json(DATA / "STATUS.json", {"phase": "BLOCKED_ERROR", "error": f"{type(exc).__name__}: {exc}"})
        raise
