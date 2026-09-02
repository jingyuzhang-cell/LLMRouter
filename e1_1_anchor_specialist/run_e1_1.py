#!/usr/bin/env python3
"""Audit stable, actionable advantages over a fixed financial anchor."""

import hashlib
import json
import re
from pathlib import Path

import numpy as np


ROOT = Path("/root")
OUT = ROOT / "e1_1_anchor_specialist"
EXP = ROOT / "target_support_expansion_v1"
PROTOCOL = OUT / "E1_1_PROTOCOL.json"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
ANCHOR = MODELS.index("qwen-plus")
SEED = 20260901


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol = json.loads(PROTOCOL.read_text())
    delta = float(protocol["meaningful_advantage_delta"])
    old = json.loads((ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json").read_text())
    new = json.loads((EXP / "EXPANSION_DEV_VALIDATION_SPLIT.json").read_text())
    ids = sorted(set(old["train_task_ids"] + old["validation_task_ids"] + new["train_task_ids"]))
    assert len(ids) == 419 and not set(ids) & set(new["validation_task_ids"])
    tasks = {x["id"]: x for x in read_jsonl(EXP / "combined_509_tasks_frozen.jsonl")}
    rows = read_jsonl(ROOT / "five_model_routability_audit/five_model_training_repeats_frozen.jsonl")
    rows += read_jsonl(EXP / "expanded_five_model_repeats_frozen.jsonl")
    lookup = {(x["task_id"], x["model"], int(x["repeat"])): x for x in rows if x["task_id"] in ids}
    assert len(lookup) == len(ids) * len(MODELS) * 3
    quality = np.asarray([[[float(lookup[(tid, model, r)]["quality"]) for r in range(3)]
                           for model in MODELS] for tid in ids])
    advantages = quality - quality[:, ANCHOR:ANCHOR + 1, :]

    context_lengths = np.asarray([len(str(tasks[x].get("context") or "").split()) for x in ids])
    long_cut = float(np.median(context_lengths))
    strata = {
        "has_table": np.asarray([bool(tasks[x].get("table")) for x in ids]),
        "long_context": context_lengths >= long_cut,
        "numeric_dense": np.asarray([len(re.findall(r"\d", str(tasks[x].get("question") or "") + " " + str(tasks[x].get("context") or ""))) >= 10 for x in ids]),
        "calculation_cues": np.asarray([bool(re.search(r"(?i)percent|ratio|difference|increase|decrease|calculate|how much|total|average", str(tasks[x].get("question") or ""))) for x in ids]),
        "compliance_cues": np.asarray([bool(re.search(r"(?i)compliance|regulation|penalt|audit|required|shall|obligation|appeal", str(tasks[x].get("question") or ""))) for x in ids]),
    }
    rng = np.random.default_rng(SEED)
    boot_idx = rng.integers(0, len(ids), size=(10000, len(ids)))
    positions = np.arange(len(ids))
    results = {}
    passing = []
    for m, model in enumerate(MODELS):
        if m == ANCHOR:
            continue
        adv = advantages[:, m, :]
        stable = np.sum(adv > delta, axis=1) >= 2
        held_task_gains = np.zeros((3, len(ids)))
        held_switches = np.zeros((3, len(ids)), dtype=bool)
        held_harms = np.zeros((3, len(ids)), dtype=bool)
        for held in range(3):
            other = [r for r in range(3) if r != held]
            switch = adv[:, other].mean(axis=1) > delta
            held_switches[held] = switch
            held_task_gains[held] = np.where(switch, adv[:, held], 0.0)
            held_harms[held] = switch & (adv[:, held] < -delta)
        task_gain = held_task_gains.mean(axis=0)
        boot = task_gain[boot_idx].mean(axis=1)
        total_switches = int(held_switches.sum())
        harm_rate = float(held_harms.sum() / total_switches) if total_switches else 0.0
        base_rate = float(stable.mean())
        enrichments = {}
        for name, mask in strata.items():
            rate = float(stable[mask].mean()) if mask.any() else 0.0
            enrichments[name] = {"tasks": int(mask.sum()), "stable_switch_rate": rate,
                                 "enrichment": float(rate / base_rate) if base_rate > 0 else 0.0}
        max_enrichment = max(x["enrichment"] for x in enrichments.values())
        checks = {
            "stable_switch_rate_ge_0.05": base_rate >= .05,
            "cross_repeat_gain_positive": float(task_gain.mean()) > 0,
            "gain_ci95_lower_ge_0": float(np.quantile(boot, .025)) >= 0,
            "harmful_switch_rate_le_0.25": harm_rate <= .25,
            "observable_stratum_enrichment_ge_1.5": max_enrichment >= 1.5,
        }
        passed = all(checks.values())
        if passed:
            passing.append(model)
        results[model] = {
            "mean_advantage": float(adv.mean()),
            "repeat_level_win_tie_loss": {
                "win_gt_delta": float(np.mean(adv > delta)),
                "neutral_abs_le_delta": float(np.mean(np.abs(adv) <= delta)),
                "loss_lt_minus_delta": float(np.mean(adv < -delta)),
            },
            "stable_switch_tasks": int(stable.sum()), "stable_switch_rate": base_rate,
            "cross_repeat_switches": total_switches,
            "cross_repeat_gain": float(task_gain.mean()),
            "gain_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
            "probability_gain_positive": float(np.mean(boot > 0)),
            "harmful_switch_rate_among_switches": harm_rate,
            "observable_strata": enrichments,
            "max_observable_enrichment": max_enrichment,
            "gate": {**checks, "pass": passed},
        }
    report = {
        "status": "E1_1_PASS" if passing else "E1_1_FAIL_STOP_ROUTER_FITTING",
        "integrity": {"tasks": len(ids), "models": len(MODELS), "repeats": 3, "external_api_calls": 0,
                      "router_models_trained": 0, "protocol_sha256": sha(PROTOCOL)},
        "anchor": MODELS[ANCHOR], "delta": delta, "long_context_word_cutoff": long_cut,
        "specialists": results, "passing_specialists": passing, "gate_pass": bool(passing),
    }
    result = OUT / "E1_1_RESULTS.json"
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "E1_1_SHA256SUMS").write_text(f"{sha(PROTOCOL)}  {PROTOCOL.name}\n{sha(result)}  {result.name}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
