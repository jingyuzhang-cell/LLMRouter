#!/usr/bin/env python3
"""Select a targeted 120-task pilot and build a deterministic four-node DAG per task."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np


ROOT = Path("/root")
OUT = ROOT / "e2_targeted_decomposition"
EXP = ROOT / "target_support_expansion_v1"
PROTOCOL = OUT / "E2_PROTOCOL.json"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
ANCHOR = MODELS.index("qwen-plus")


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def entropy(values):
    counts = np.bincount(values, minlength=len(MODELS))
    p = counts[counts > 0] / len(values)
    return float(-np.sum(p * np.log2(p)))


def nodes(task_id, task, stratum):
    question = str(task.get("question") or "")
    has_table = bool(task.get("table"))
    capability = "numerical_reasoning" if has_table else "regulatory_compliance"
    third_instruction = (
        "Using only the structured facts from node n2, perform the single calculation or comparison required by the question. Return the result and a compact derivation."
        if has_table else
        "Using only the structured provisions from node n2, determine the single applicable obligation, permission, exception, or procedure asked by the question."
    )
    common = {"task_id": task_id, "selection_stratum": stratum, "source_question": question}
    return [
        {**common, "node_id": "n1", "node_type": "evidence_localization", "primary_capability": "evidence_localization",
         "instruction": "Locate only the table rows or context passages needed to answer the source question. Return concise source locations, not the final answer.",
         "declared_inputs": ["source_question", "source_context", "source_table"], "depends_on": [],
         "expected_output_type": "evidence_locations", "verification_rule": "Every location must be traceable to a declared source input.", "is_final_composition": False},
        {**common, "node_id": "n2", "node_type": "extraction", "primary_capability": "fact_extraction",
         "instruction": "Extract only the facts, values, units, entities, and conditions needed for the source question from the locations returned by n1.",
         "declared_inputs": ["source_question", "n1.output"], "depends_on": ["n1"],
         "expected_output_type": "structured_facts", "verification_rule": "Each extracted item must cite one n1 location.", "is_final_composition": False},
        {**common, "node_id": "n3", "node_type": capability, "primary_capability": capability,
         "instruction": third_instruction, "declared_inputs": ["source_question", "n2.output"], "depends_on": ["n2"],
         "expected_output_type": "derived_result", "verification_rule": "The result must use only n2 facts and expose the decisive operation or rule.", "is_final_composition": False},
        {**common, "node_id": "n4", "node_type": "evidence_synthesis", "primary_capability": "answer_composition",
         "instruction": "Compose one direct answer to the source question using n2 facts and the n3 result. Preserve units and qualifications; add no unsupported claims.",
         "declared_inputs": ["source_question", "n2.output", "n3.output"], "depends_on": ["n2", "n3"],
         "expected_output_type": "final_answer", "verification_rule": "Every substantive claim must be supported by n2 or n3.", "is_final_composition": True},
    ]


def main():
    protocol = json.loads(PROTOCOL.read_text())
    old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
    new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
    ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
    task_map = {x["id"]: x for x in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
    rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
    rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
    lookup = {(x["task_id"], x["model"], int(x["repeat"])): x for x in rows if x["task_id"] in ids}
    quality = np.asarray([[[float(lookup[(tid, model, r)]["quality"]) for r in range(3)]
                           for model in MODELS] for tid in ids])
    adv = quality - quality[:, ANCHOR:ANCHOR + 1, :]
    stable_specialist = np.any(np.sum(adv > .05, axis=2) >= 2, axis=1)
    winners = quality.argmax(axis=1)
    unique = np.sum(quality == quality.max(axis=1)[:, None, :], axis=1) == 1
    stable_anchor = (~stable_specialist) & np.all(unique, axis=1) & np.all(winners == ANCHOR, axis=1)
    unstable = (~stable_specialist) & (~stable_anchor) & (~np.all(winners == winners[:, :1], axis=1))

    spec_score = np.max(adv.mean(axis=2), axis=1)
    anchor_margin = np.min(quality[:, ANCHOR, :] - np.max(np.delete(quality, ANCHOR, axis=1), axis=1), axis=1)
    instability = np.asarray([entropy(x) for x in winners])
    mean_values = quality.mean(axis=2)
    margins = np.sort(mean_values, axis=1)[:, -1] - np.sort(mean_values, axis=1)[:, -2]
    ranked = {
        "stable_specialist": sorted(np.where(stable_specialist)[0], key=lambda i: (-spec_score[i], ids[i]))[:40],
        "stable_anchor": sorted(np.where(stable_anchor)[0], key=lambda i: (-anchor_margin[i], ids[i]))[:40],
        "unstable": sorted(np.where(unstable)[0], key=lambda i: (-instability[i], margins[i], ids[i]))[:40],
    }
    if any(len(x) != 40 for x in ranked.values()):
        raise ValueError({k: len(v) for k, v in ranked.items()})
    task_rows, node_rows = [], []
    for stratum, indices in ranked.items():
        for rank, i in enumerate(indices, 1):
            tid = ids[i]
            task_rows.append({"task_id": tid, "selection_stratum": stratum, "stratum_rank": rank,
                              "source_question": str(task_map[tid].get("question") or ""),
                              "source_context": str(task_map[tid].get("context") or ""),
                              "source_table": task_map[tid].get("table") or []})
            node_rows.extend(nodes(tid, task_map[tid], stratum))
    assert len({x["task_id"] for x in task_rows}) == 120
    assert len(node_rows) == 480
    assert Counter(x["selection_stratum"] for x in task_rows) == {"stable_specialist": 40, "stable_anchor": 40, "unstable": 40}
    for tid in {x["task_id"] for x in node_rows}:
        group = [x for x in node_rows if x["task_id"] == tid]
        node_ids = {x["node_id"] for x in group}
        assert len(group) == 4 and sum(x["is_final_composition"] for x in group) == 1
        assert all(set(x["depends_on"]) <= node_ids and x["node_id"] not in x["depends_on"] for x in group)
    task_path = OUT / "E2_TARGETED_TASKS.jsonl"
    node_path = OUT / "E2_SUBTASK_MANIFEST.jsonl"
    stage1_path = OUT / "E2_STAGE1_30.jsonl"
    task_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in task_rows))
    node_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in node_rows))
    stage1_ids = {x["task_id"] for x in task_rows if x["stratum_rank"] <= 10}
    stage1_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in task_rows if x["task_id"] in stage1_ids))
    report = {"status": "E2_MANIFEST_GATE_PASS", "tasks": len(task_rows), "nodes": len(node_rows),
              "strata": dict(Counter(x["selection_stratum"] for x in task_rows)), "stage1_tasks": len(stage1_ids),
              "external_api_calls": 0, "protocol_sha256": sha(PROTOCOL)}
    result = OUT / "E2_MANIFEST_AUDIT.json"
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    files = [PROTOCOL, task_path, node_path, stage1_path, result]
    (OUT / "E2_MANIFEST_SHA256SUMS").write_text("".join(f"{sha(x)}  {x.name}\n" for x in files))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
