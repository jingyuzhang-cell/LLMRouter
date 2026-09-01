#!/usr/bin/env python3
"""Freeze blinded human calibration packets for selecting the C9 replacement judge."""
from __future__ import annotations

import hashlib
import json
import random
import string
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root")
DATA = ROOT / "phase_c9_0"
OUT = DATA / "human_judge_calibration"
SEED = "C9-HUMAN-JUDGE-CALIBRATION-v1|20260901"
BLIND_SEED = "20260831|C9_2_QUALITY_EVALUATION_V1"
GROUPS = 30


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


tasks = {
    row["task_id"]: row
    for row in read_jsonl(DATA / "C9_DEV_TASKS.jsonl")
    if row.get("split") == "development_train"
}
routes = {row["task_id"]: row for row in read_jsonl(DATA / "C9_2_EVALUATION_ROUTE_MANIFEST.jsonl")}
grouped = defaultdict(list)
for row in read_jsonl(DATA / "C9_TRAIN_RESPONSES.jsonl"):
    if row.get("success") and routes[row["task_id"]]["evaluation_route"] == "independent_judge_0_4":
        grouped[(row["task_id"], int(row["repeat"]))].append(row)
assert len(grouped) == 810

# Terciles are computed from input-side context length only.
lengths = sorted(float(tasks[tid]["observable_features"].get("context_token_count", 0)) for tid, _ in grouped)
cut1, cut2 = lengths[len(lengths) // 3], lengths[(2 * len(lengths)) // 3]


def length_band(value: float) -> str:
    if value <= cut1:
        return "short"
    if value <= cut2:
        return "medium"
    return "long"


strata = defaultdict(list)
for key, answers in grouped.items():
    task = tasks[key[0]]
    length = float(task["observable_features"].get("context_token_count", 0))
    stratum = (task["primary_capability"], len(answers), length_band(length))
    strata[stratum].append(key)
for stratum, keys in strata.items():
    keys.sort(key=lambda key: hashlib.sha256(f"{SEED}|{key[0]}|{key[1]}".encode()).hexdigest())

# Round-robin across deterministic strata avoids any response-outcome selection.
selected = []
for stratum in sorted(strata, key=lambda x: hashlib.sha256(f"{SEED}|{x}".encode()).hexdigest()):
    if strata[stratum] and len(selected) < GROUPS:
        selected.append((stratum, strata[stratum].pop(0)))
while len(selected) < GROUPS:
    progressed = False
    for stratum in sorted(strata):
        if strata[stratum] and len(selected) < GROUPS:
            selected.append((stratum, strata[stratum].pop(0)))
            progressed = True
    if not progressed:
        break
assert len(selected) == GROUPS


def blinded_candidates(key):
    tid, repeat = key
    answers = sorted(grouped[key], key=lambda row: row["model"])
    labels = list(string.ascii_uppercase[: len(answers)])
    order = list(range(len(answers)))
    digest = hashlib.sha256(f"{BLIND_SEED}|primary|{tid}|{repeat}".encode()).hexdigest()
    random.Random(int(digest, 16)).shuffle(order)
    displayed = [{"label": labels[index], "answer": answers[index].get("answer", "")} for index in order]
    mapping = {labels[index]: answers[index]["model"] for index in range(len(answers))}
    return displayed, mapping


packets = []
mappings = []
manifest_groups = []
for ordinal, (stratum, key) in enumerate(selected, 1):
    tid, repeat = key
    task = tasks[tid]
    displayed, mapping = blinded_candidates(key)
    group_id = f"{tid}:{repeat}"
    packets.append({
        "ordinal": ordinal,
        "group_id": group_id,
        "question": task.get("question", ""),
        "context": task.get("context", ""),
        "table": task.get("table") or [],
        "reference_answer": task.get("reference_answer"),
        "candidates": [dict(candidate, score=None, reason="") for candidate in displayed],
        "reviewer_confidence": None,
        "reviewer_notes": "",
    })
    mappings.append({"group_id": group_id, "label_to_model": mapping})
    manifest_groups.append({
        "ordinal": ordinal,
        "group_id": group_id,
        "task_id": tid,
        "repeat_id": repeat,
        "primary_capability": stratum[0],
        "candidate_count": stratum[1],
        "context_length_band": stratum[2],
        "context_token_count": task["observable_features"].get("context_token_count", 0),
    })

OUT.mkdir(parents=True, exist_ok=True)
manifest_path = OUT / "C9_HUMAN_CALIBRATION_MANIFEST.json"
reviewer_a = OUT / "C9_HUMAN_REVIEWER_A.jsonl"
reviewer_b = OUT / "C9_HUMAN_REVIEWER_B.jsonl"
mapping_path = OUT / "C9_HUMAN_CALIBRATION_SEALED_MAPPING.jsonl"
instructions_path = OUT / "C9_HUMAN_REVIEW_INSTRUCTIONS.md"
protocol_path = OUT / "C9_HUMAN_CALIBRATION_PROTOCOL.json"

manifest_path.write_text(json.dumps({
    "version": "C9-human-calibration-manifest-v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "selection_seed": SEED,
    "groups": manifest_groups,
}, ensure_ascii=False, indent=2) + "\n")
packet_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in packets)
reviewer_a.write_text(packet_text)
reviewer_b.write_text(packet_text)
mapping_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in mappings))
instructions_path.write_text("""# C9 Human Judge Calibration Instructions

Score every candidate independently using only the supplied question, context/table, and reference answer.

- 4: fully correct; key conclusion and reasoning are supported.
- 3: mostly correct; a minor omission does not change the main conclusion.
- 2: partly correct; contains a material omission or local error.
- 1: little correct content; main conclusion is wrong.
- 0: incorrect, irrelevant, unsupported, or no valid answer.

Rules:

1. Assign an integer score from 0 to 4 to every candidate label exactly once.
2. Do not rank candidates relative to each other; assess each independently.
3. Do not infer or record model identity.
4. Give a short evidence-based reason for every score.
5. Set reviewer_confidence to low, medium, or high.
6. Reviewers A and B must work independently before adjudication.
7. A score difference greater than one point requires adjudication; all other differences are retained for agreement statistics and resolved by the frozen adjudication rule before forming human gold.
""")
protocol = {
    "version": "C9-human-judge-calibration-v1",
    "status": "FROZEN_BEFORE_HUMAN_SCORING",
    "purpose": "Select an operational replacement judge by agreement with human-calibrated semantic scores, never by downstream C9 routability results.",
    "groups": GROUPS,
    "expected_candidate_answers": sum(row["candidate_count"] for row in manifest_groups),
    "selection": "outcome-blind deterministic round-robin across primary capability x candidate-count x input-context-length tercile strata",
    "selection_seed": SEED,
    "reviewers": 2,
    "independent_review_required": True,
    "adjudication_trigger": "absolute score disagreement > 1",
    "adjudication_rule": "A third adjudicator assigns the final 0-4 score after seeing both reasons but not model identity; for disagreements <=1, rounded mean with halves rounded toward the more conservative lower score.",
    "judge_selection_forbidden_inputs": ["C9 stable gap", "specialist opportunity", "candidate model ranking", "router outcome"],
    "judge_validity_gates": {
        "parse_success_min": 0.95,
        "human_within_one_agreement_min": 0.80,
        "human_mae_max": 0.75,
        "duplicate_exact_agreement_min": 0.80,
        "order_perturbation_mae_max": 0.50,
        "family_bias_review_required": True
    },
    "formal_c9_labels_created": False,
    "model_calls": 0,
    "router_training": False,
    "wave_2_access": False,
    "dag_execution": False,
    "source_hashes": {
        "tasks": sha(DATA / "C9_DEV_TASKS.jsonl"),
        "responses": sha(DATA / "C9_TRAIN_RESPONSES.jsonl"),
        "routes": sha(DATA / "C9_2_EVALUATION_ROUTE_MANIFEST.jsonl")
    }
}
protocol_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")

targets = [protocol_path, manifest_path, reviewer_a, reviewer_b, mapping_path, instructions_path]
(OUT / "C9_HUMAN_CALIBRATION_SHA256SUMS").write_text("".join(f"{sha(path)}  {path.name}\n" for path in targets))
print(json.dumps({
    "status": protocol["status"],
    "groups": GROUPS,
    "candidate_answers": protocol["expected_candidate_answers"],
    "capabilities": dict(Counter(row["primary_capability"] for row in manifest_groups)),
    "candidate_counts": dict(Counter(row["candidate_count"] for row in manifest_groups)),
    "length_bands": dict(Counter(row["context_length_band"] for row in manifest_groups)),
    "model_calls": 0,
}, ensure_ascii=False, indent=2))
