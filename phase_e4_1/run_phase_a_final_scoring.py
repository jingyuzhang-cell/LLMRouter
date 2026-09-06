#!/usr/bin/env python3
"""Phase A: 160 final N4 labels under the frozen E4.1 scorer.

Frozen contract (do NOT modify):
- workflow_valid: provider_success AND json_parse_valid AND node_schema_valid('N4', canonicalized)
  AND NOT generation_ceiling_binding AND NOT execution_implementation_defect.
  All fields from frozen execution contract; none from judge/reference.
- Q_delivered = Q_final if workflow_valid else 0.0.
- Deterministic layer (17 tasks): score_deterministic -> 0/1.
- Semantic layer (23 tasks): qwen-max single primary judge, integer 0-4 -> /4.0. NO secondary judge.
- Judge failure (transport/parse, 3 attempts): label stays MISSING (not 0).
- RTG_t = Q_final(N4) propagated to N1-N3 (handled in Phase C).

Judge invocation mirrors run_c9_multi_judge_feasibility.py (frozen C9.2 rubric/prompt),
atomized to one candidate per call per E4 Amendment-002.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root")
DATA = ROOT / "phase_c9_0"
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
JUDGE_MODEL = "qwen-max"
TIMEOUT = 90
MAX_TOKENS = 1500
SEED = "20260831|C9_2_QUALITY_EVALUATION_V1"

LABELS_JSONL = ROOT / "phase_e4_1/E4_PHASE_A_FINAL_LABELS.jsonl"
LABELS_JSON = ROOT / "phase_e4_1/E4_PHASE_A_FINAL_LABELS.json"
JUDGE_EVENTS = ROOT / "phase_e4_1/E4_PHASE_A_JUDGE_EVENTS.jsonl"

sys.path.insert(0, str(ROOT))
from phase_e4_0.execution_controls import (  # noqa: E402
    latest_by_key, parse_json_object, canonicalize_node_output, node_schema_valid,
    _schema_failure_reasons, outcome_key,
)
from phase_e4_1.deterministic_extractor import score_deterministic  # noqa: E402
from phase_e4_1.judge_format_normalization import parse_scores  # noqa: E402

for line in (ROOT / ".env").read_text().splitlines():
    v = line.strip()
    if v and not v.startswith("#") and "=" in v:
        k, s = v.split("=", 1)
        os.environ.setdefault(k.strip(), s.strip().strip('"').strip("'"))

sys.path.insert(0, str(PROJECT))
from openclaw_router.config import OpenClawConfig  # noqa: E402
from openclaw_router.judge_utils import extract_message_text  # noqa: E402
from openclaw_router.server import LLMBackend  # noqa: E402


def read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


TASKS = {r["task_id"]: r for r in read_jsonl(DATA / "C9_DEV_TASKS.jsonl")}
ROUTES = {r["task_id"]: r for r in read_jsonl(DATA / "C9_2_EVALUATION_ROUTE_MANIFEST.jsonl")}
CONTRACT = {t["task_id"]: t for t in json.loads((ROOT / "phase_e4_1/E4_1_NUMERIC_UNIT_CONTRACT_FROZEN.json").read_text())["tasks"]}


def atomic_prompt(task, answer_text):
    """Single-candidate ('A') rubric prompt; identical rubric to frozen C9.2 prompt_for."""
    reference = str(task.get("reference_answer") or "").strip()
    if reference:
        refpart = f"\nReference answer:\n{reference}"
    else:
        refpart = "\nNo reference answer is available. Judge only whether each answer is correct and supported by the supplied context/table."
    return f'''You are an independent evaluator. Score every blinded candidate answer independently; do not rank candidates or infer model identity. Use only the question, supplied context/table, and reference answer when present.
Rubric: 4=fully correct and supported; 3=mostly correct with only minor omission; 2=partly correct with a material omission or local error; 1=little correct content and main conclusion wrong; 0=incorrect, irrelevant, unsupported, or no valid answer.
Return only JSON exactly shaped as {{"scores":[{{"label":"A","score":4,"reason":"brief reason"}}]}}. Include every supplied label exactly once; score must be an integer 0..4.
Question:
{task.get("question", "")}
Context:
{task.get("context", "")}
Table:
{json.dumps(task.get("table") or [], ensure_ascii=False)}{refpart}

Answer A:
{answer_text}'''


def workflow_valid_fields(record, manifest_cls):
    """Compute workflow_valid per frozen delivered-quality contract."""
    post = record["post_action_outcome"]
    parsed, json_valid, _ = parse_json_object(record.get("raw_output"))
    canonicalized, _ = canonicalize_node_output("N4", parsed)
    schema_ok = node_schema_valid("N4", canonicalized, json_valid)
    reasons = _schema_failure_reasons("N4", canonicalized, json_valid)
    provider_ok = post.get("provider_success") is True
    json_ok = post.get("json_parse_valid") is True
    ceiling = post.get("generation_ceiling_binding") is True
    # execution_defect from manifest: invalidation_reason == execution_implementation_defect on a non-KEEP key
    exec_defect = manifest_cls.get("classification") != "KEEP" and manifest_cls.get("invalidation_reason") == "execution_implementation_defect"
    valid = provider_ok and json_ok and schema_ok and not ceiling and not exec_defect
    detail = {
        "provider_success": provider_ok,
        "json_parse_valid": json_ok,
        "node_schema_valid": schema_ok,
        "generation_ceiling_binding": ceiling,
        "execution_defect": exec_defect,
        "failure_reason": reasons[0] if reasons else None,
        "manifest_classification": manifest_cls.get("classification"),
    }
    return valid, detail, canonicalized


async def call_judge(backend, task, answer_text, max_attempts=3):
    prompt = atomic_prompt(task, answer_text)
    last_err = None
    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                backend.call(JUDGE_MODEL, [{"role": "user", "content": prompt}],
                             max_tokens=MAX_TOKENS, temperature=0, stream=False),
                timeout=TIMEOUT,
            )
            raw = extract_message_text(response)
            scores = parse_scores(raw, ["A"])
            return {
                "success": True, "attempt": attempt, "score": scores["A"],
                "raw": raw[:2000], "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                "error": None,
            }
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:400]}"
            await asyncio.sleep(2 * attempt)
    return {"success": False, "attempt": max_attempts, "score": None, "raw": None,
            "latency_ms": None, "error": last_err}


def build_base_records():
    log = read_jsonl(ROOT / "phase_e4_0_v2/E4_0_B_V2_EXPLORATION_NODE_LOG.jsonl")
    finals = list(latest_by_key(log).values())
    n4 = [r for r in finals if r["node_id"] == "N4"]
    manifest = json.loads((ROOT / "phase_e4_0_v2/E4_0_B_V2_AMENDMENT_006_RECOLLECTION_MANIFEST.json").read_text())
    cls = {tuple(e["key"]): e for e in manifest["entries"]}
    records = []
    for r in n4:
        tid, traj = r["task_id"], r["trajectory_id"]
        mcls = cls.get((tid, traj, "N4"), {})
        valid, detail, canon = workflow_valid_fields(r, mcls)
        arm = traj.split(":V2")[-1]
        rec = {
            "task_id": tid, "trajectory_id": traj, "node_id": "N4",
            "trajectory_arm": arm,
            "leakage_group_id": TASKS.get(tid, {}).get("leakage_group_id"),
            "selected_model": r["selected_model"],
            "source_dataset": TASKS.get(tid, {}).get("source_dataset"),
            "evaluation_route": ROUTES.get(tid, {}).get("evaluation_route"),
            "reference_available": ROUTES.get(tid, {}).get("reference_available"),
            "workflow_valid": valid,
            "workflow_valid_detail": detail,
            "answer_text": str(canon.get("answer", "")) if valid else None,
        }
        if not valid:
            rec["scoring_layer"] = "delivery_failure"
            rec["Q_final"] = 0.0
            rec["Q_delivered"] = 0.0
            rec["judge_model"] = None
            rec["judge_success"] = None
            rec["judge_score"] = None
        elif rec["evaluation_route"] == "deterministic_numeric":
            entry = CONTRACT.get(tid)
            res = score_deterministic(rec["answer_text"], entry) if entry else None
            rec["scoring_layer"] = "deterministic"
            rec["deterministic_extracted"] = res.get("extracted") if res else None
            rec["deterministic_within_tolerance"] = res.get("within_tolerance") if res else None
            rec["deterministic_reason"] = res.get("reason") if res else "no_contract_entry"
            rec["Q_final"] = float(res["score"]) if res else 0.0
            rec["Q_delivered"] = rec["Q_final"]
            rec["judge_model"] = None
            rec["judge_success"] = None
            rec["judge_score"] = None
        else:
            rec["scoring_layer"] = "semantic"
            rec["Q_final"] = None  # filled by judge
            rec["Q_delivered"] = None
        records.append(rec)
    return records


async def run_semantic(records):
    """Call Qwen-Max atomically for valid semantic records. Resume-capable."""
    completed = {}
    if JUDGE_EVENTS.exists():
        for row in read_jsonl(JUDGE_EVENTS):
            if row.get("success") and row.get("trajectory_id"):
                completed[row["trajectory_id"]] = row
    semantic = [r for r in records if r["scoring_layer"] == "semantic"]
    todo = [r for r in semantic if r["trajectory_id"] not in completed]
    print(f"semantic valid: {len(semantic)} | already done: {len(completed)} | todo: {len(todo)}", flush=True)
    if not todo:
        return completed
    backend = LLMBackend(OpenClawConfig.from_yaml(str(PROJECT / "configs/openclaw_multi_provider.yaml")))
    with JUDGE_EVENTS.open("a", encoding="utf-8") as handle:
        for r in todo:
            task = TASKS[r["task_id"]]
            res = await call_judge(backend, task, r["answer_text"])
            event = {
                "trajectory_id": r["trajectory_id"], "task_id": r["task_id"],
                "judge_model": JUDGE_MODEL, "timestamp": datetime.now(timezone.utc).isoformat(),
                **res,
            }
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            completed[r["trajectory_id"]] = event
            q = res["score"] / 4.0 if res["success"] else None
            status = f"score={res['score']} Q={q:.3f}" if res["success"] else f"FAIL {res['error'][:60]}"
            print(f"  [{r['trajectory_arm']}] {r['task_id'][:18]} {r['selected_model']:14} {status}", flush=True)
    return completed


def finalize(records, completed):
    missing = 0
    for r in records:
        if r["scoring_layer"] != "semantic":
            continue
        ev = completed.get(r["trajectory_id"])
        if ev and ev.get("success"):
            r["judge_model"] = JUDGE_MODEL
            r["judge_success"] = True
            r["judge_score"] = ev["score"]
            r["Q_final"] = ev["score"] / 4.0
            r["Q_delivered"] = r["Q_final"]
        else:
            r["judge_model"] = JUDGE_MODEL
            r["judge_success"] = False
            r["judge_score"] = None
            r["Q_final"] = None  # MISSING per judge_failure_rule
            r["Q_delivered"] = None
            missing += 1
    return missing


async def main():
    records = build_base_records()
    completed = await run_semantic(records)
    missing = finalize(records, completed)

    LABELS_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    by_layer = Counter(r["scoring_layer"] for r in records)
    by_route = Counter(r["evaluation_route"] for r in records)
    by_arm = Counter(r["trajectory_arm"] for r in records)
    valid = sum(1 for r in records if r["workflow_valid"])
    has_q = [r for r in records if r["Q_delivered"] is not None]
    q_by_layer = {l: [r["Q_delivered"] for r in records if r["scoring_layer"] == l and r["Q_delivered"] is not None] for l in by_layer}
    summary = {
        "version": "E4.1-phase-A-final-labels-v1",
        "frozen_scorer": "phase_e4_1/E4_SCORER_FROZEN.json",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_trajectories": len(records),
        "n_workflow_valid": valid,
        "n_delivery_failure": len(records) - valid,
        "by_scoring_layer": dict(by_layer),
        "by_route": dict(by_route),
        "by_trajectory_arm": dict(by_arm),
        "n_judge_calls": len(completed),
        "n_judge_missing": missing,
        "mean_Q_delivered": round(sum(r["Q_delivered"] for r in has_q) / len(has_q), 4) if has_q else None,
        "mean_Q_by_layer": {l: round(sum(qs) / len(qs), 4) if qs else None for l, qs in q_by_layer.items()},
        "judge_model": JUDGE_MODEL,
        "rtg_note": "RTG_t = Q_final(N4) propagated to N1-N3 in Phase C; this file holds N4 only.",
        "single_judge_limitation": "23 open-task semantic endpoint rests on Qwen-Max as the SOLE machine judge.",
    }
    LABELS_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
