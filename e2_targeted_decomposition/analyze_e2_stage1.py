#!/usr/bin/env python3
"""Score completed E2 compositions and execute the frozen Stage 1 gate."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path("/root")
OUT = ROOT / "e2_targeted_decomposition"
EXP = ROOT / "target_support_expansion_v1"
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
PROTOCOL = OUT / "E2_MEASUREMENT_PROTOCOL.json"
MODELS = ("qwen-plus", "glm-5.2")
SEED = 20260901


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_gap(scores):
    # scores: tasks x models x repeats; each repeat is selected using the other repeat.
    gains = []
    for held in range(scores.shape[2]):
        other = 1 - held
        selected = scores[:, :, other].argmax(axis=1)
        best = int(scores[:, :, other].mean(axis=0).argmax())
        pos = np.arange(len(scores))
        gains.append(scores[pos, selected, held] - scores[:, best, held])
    return np.mean(gains, axis=0)


def main():
    protocol = json.loads(PROTOCOL.read_text())
    stage = read_jsonl(OUT / "E2_STAGE1_30.jsonl")
    ids = [x["task_id"] for x in stage]
    responses = read_jsonl(OUT / "E2_STAGE1_RESPONSES.jsonl")
    latest = {(x["task_id"], x["model"], int(x["repeat"]), x["node_id"]): x for x in responses}
    expected = {(tid, model, repeat, f"n{node}") for tid in ids for model in MODELS for repeat in (0, 1) for node in range(1, 5)}
    successful = {key for key, row in latest.items() if key in expected and row.get("success")}
    provider_success = len(successful) / len(expected)
    if successful != expected:
        report = {"status": "E2_STAGE1_INCOMPLETE", "expected_nodes": len(expected),
                  "successful_nodes": len(successful), "provider_success_rate": provider_success,
                  "missing_or_failed": len(expected - successful), "protocol_sha256": sha(PROTOCOL)}
        (OUT / "E2_STAGE1_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    task_map = {x["id"]: x for x in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
    sys.path.insert(0, str(PROJECT))
    from openclaw_router.experiment_protocol import objective_score

    def safe_score(task, answer):
        value = objective_score(task, str(answer) + "\n")
        return float(value or 0.0)

    decomposed = np.asarray([[[safe_score(task_map[tid], latest[(tid, model, repeat, "n4")]["answer"])
                               for repeat in (0, 1)] for model in MODELS] for tid in ids])
    frozen = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
    frozen += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
    lookup = {(x["task_id"], x["model"], int(x["repeat"])): x for x in frozen if x["task_id"] in ids}
    whole = np.asarray([[[float(lookup[(tid, model, repeat)]["quality"]) for repeat in (0, 1)]
                         for model in MODELS] for tid in ids])
    dec_gain = stable_gap(decomposed)
    whole_gain = stable_gap(whole)
    paired = dec_gain - whole_gain
    # GLM is the only specialist in the fixed two-model pool.
    mean_dec = decomposed.mean(axis=2)
    stable_specialist = np.all(decomposed[:, 1, :] > decomposed[:, 0, :] + .05, axis=1)
    harmful_specialist = np.all(decomposed[:, 1, :] < decomposed[:, 0, :] - .05, axis=1)
    rng = np.random.default_rng(SEED)
    boot_idx = rng.integers(0, len(ids), size=(10000, len(ids)))
    boot_paired = paired[boot_idx].mean(axis=1)
    dec_best = int(mean_dec.mean(axis=0).argmax())
    dec_oracle_gap = float(np.mean(mean_dec.max(axis=1) - mean_dec[:, dec_best]))
    metrics = {
        "provider_success_rate": provider_success,
        "decomposition_best_single_model": MODELS[dec_best],
        "decomposition_best_single_quality": float(mean_dec[:, dec_best].mean()),
        "decomposition_observed_oracle_gap": dec_oracle_gap,
        "decomposition_cross_repeat_stable_gap": float(dec_gain.mean()),
        "whole_historical_cross_repeat_stable_gap": float(whole_gain.mean()),
        "decomposition_minus_whole_stable_gap": float(paired.mean()),
        "paired_difference_ci95": [float(np.quantile(boot_paired, .025)), float(np.quantile(boot_paired, .975))],
        "probability_paired_difference_positive": float(np.mean(boot_paired > 0)),
        "specialist_opportunity_rate": float(stable_specialist.mean()),
        "harmful_specialist_rate": float(harmful_specialist.mean()),
    }
    gate = {
        "decomposition_minus_whole_stable_gap_ge_0.01": metrics["decomposition_minus_whole_stable_gap"] >= .01,
        "specialist_opportunity_rate_ge_0.10": metrics["specialist_opportunity_rate"] >= .10,
        "harmful_specialist_rate_le_0.25": metrics["harmful_specialist_rate"] <= .25,
        "provider_success_rate_ge_0.98": provider_success >= .98,
    }
    passed = all(gate.values())
    report = {"status": "E2_STAGE1_PASS_EXPAND_TO_120" if passed else "E2_STAGE1_FAIL_STOP_EXPANSION",
              "integrity": {"tasks": len(ids), "models": 2, "repeats": 2, "nodes": len(expected),
                            "external_judge_calls": 0, "protocol_sha256": sha(PROTOCOL)},
              "metrics": metrics, "gate": {**gate, "pass": passed}}
    result = OUT / "E2_STAGE1_RESULTS.json"
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "E2_STAGE1_SHA256SUMS").write_text(f"{sha(PROTOCOL)}  {PROTOCOL.name}\n{sha(result)}  {result.name}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
