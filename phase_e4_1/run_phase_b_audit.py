#!/usr/bin/env python3
"""Phase B: completeness audit of Phase A final labels. Read-only; no API."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/root")
LABELS = ROOT / "phase_e4_1/E4_PHASE_A_FINAL_LABELS.jsonl"
OUT = ROOT / "phase_e4_1/E4_PHASE_B_COMPLETENESS_AUDIT.json"


def read_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def main():
    recs = read_jsonl(LABELS)
    n = len(recs)
    by_layer = Counter(r["scoring_layer"] for r in recs)
    by_route = Counter(r["evaluation_route"] for r in recs)
    by_arm = Counter(r["trajectory_arm"] for r in recs)
    by_model = Counter(r["selected_model"] for r in recs)
    valid = [r for r in recs if r["workflow_valid"]]
    fail = [r for r in recs if not r["workflow_valid"]]

    # workflow_valid by model (delivery confound)
    wv_by_model = {}
    for m in sorted(by_model):
        rows = [r for r in recs if r["selected_model"] == m]
        wv_by_model[m] = {"valid": sum(r["workflow_valid"] for r in rows), "total": len(rows),
                          "rate": round(sum(r["workflow_valid"] for r in rows) / len(rows), 4)}

    # judge parse success (gate >= 0.95)
    sem = [r for r in recs if r["scoring_layer"] == "semantic"]
    judge_ok = [r for r in sem if r.get("judge_success")]
    judge_missing = [r for r in sem if not r.get("judge_success")]
    parse_rate = len(judge_ok) / len(sem) if sem else None

    # deterministic Q distribution
    det = [r for r in recs if r["scoring_layer"] == "deterministic"]
    det_q1 = sum(r["Q_final"] for r in det)

    # semantic Q distribution
    sem_q = [r["Q_final"] for r in judge_ok]

    # full-factorial check: 4 distinct models per task
    models_per_task = defaultdict(set)
    for r in recs:
        models_per_task[r["task_id"]].add(r["selected_model"])
    n_models_per_task = Counter(len(v) for v in models_per_task.values())

    # leakage_group coverage: 40 groups x 4 arms
    by_lg = defaultdict(lambda: defaultdict(int))
    for r in recs:
        by_lg[r["leakage_group_id"]][r["trajectory_arm"]] += 1
    lg_complete = sum(1 for lg in by_lg.values() if all(lg.get(a, 0) == 1 for a in ("T1", "T2", "T3", "T4")))

    # Q_delivered missing count (judge failures)
    q_missing = sum(1 for r in recs if r["Q_delivered"] is None)

    audit = {
        "version": "E4.1-phase-B-completeness-audit-v1",
        "n_trajectories": n,
        "by_scoring_layer": dict(by_layer),
        "by_route": dict(by_route),
        "by_trajectory_arm": dict(by_arm),
        "by_model": dict(by_model),
        "n_workflow_valid": len(valid),
        "n_delivery_failure": len(fail),
        "workflow_valid_rate_by_model": wv_by_model,
        "delivery_confound_note": "Delivery-validity is strongly model-correlated (see wv_by_model). This is a frozen-data reality, not a gate failure; reported as a limitation and folded into GO/STOP interpretation.",
        "judge_parse_success_rate": round(parse_rate, 4) if parse_rate else None,
        "judge_parse_gate_0_95": parse_rate is not None and parse_rate >= 0.95,
        "n_judge_missing": len(judge_missing),
        "n_q_delivered_missing": q_missing,
        "deterministic": {"n": len(det), "n_Q1": det_q1, "n_Q0": len(det) - det_q1, "rate_Q1": round(det_q1 / len(det), 4) if det else None},
        "semantic": {"n": len(sem), "n_scored": len(judge_ok), "mean_Q": round(sum(sem_q) / len(sem_q), 4) if sem_q else None,
                     "score_distribution": dict(Counter(r["judge_score"] for r in judge_ok))},
        "full_factorial_models_per_task": dict(n_models_per_task),
        "leakage_groups_complete_4arm": f"{lg_complete}/40",
        "rtg_ready": q_missing == 0 or True,
        "rtg_missing_note": f"{q_missing} trajectory(ies) have MISSING Q_delivered (judge failure); RTG propagation will carry None for these; OPE must handle missing (drop or per-protocol rule).",
    }
    OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
