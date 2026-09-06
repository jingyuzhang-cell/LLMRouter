#!/usr/bin/env python3
"""Phase C: RTG propagation. RTG_t = Q_final(N4) propagated to N1-N3 of each trajectory.

Frozen contract: RTG_t = Q_final(N4) for all nodes N1-N4 (no counterfactual labels).
Delivery-failure trajectory -> RTG_t = 0.0 (Q_final=0). Judge-missing -> RTG_t = None (missing).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/root")
sys.path.insert(0, str(ROOT))
LABELS = ROOT / "phase_e4_1/E4_PHASE_A_FINAL_LABELS.jsonl"
NODE_LOG = ROOT / "phase_e4_0_v2/E4_0_B_V2_EXPLORATION_NODE_LOG.jsonl"
OUT_JSONL = ROOT / "phase_e4_1/E4_PHASE_C_RTG.jsonl"
OUT_JSON = ROOT / "phase_e4_1/E4_PHASE_C_RTG.json"


def read_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def main():
    from phase_e4_0.execution_controls import latest_by_key
    labels = {r["trajectory_id"]: r for r in read_jsonl(LABELS)}
    log = read_jsonl(NODE_LOG)
    finals = latest_by_key(log)
    rtg_rows = []
    n_missing = 0
    n_zero = 0
    n_real = 0
    for key, rec in finals.items():
        tid, traj, node = key
        lab = labels.get(traj)
        if lab is None:
            continue
        q_final = lab["Q_final"]  # None if judge-missing, 0.0 if delivery failure, else [0,1]
        if q_final is None:
            rtg = None
            n_missing += 1
        elif q_final == 0.0:
            rtg = 0.0
            n_zero += 1
        else:
            rtg = float(q_final)
            n_real += 1
        rtg_rows.append({
            "task_id": tid, "trajectory_id": traj, "node_id": node,
            "selected_model": rec["selected_model"],
            "trajectory_arm": traj.split(":V2")[-1],
            "leakage_group_id": lab["leakage_group_id"],
            "node_type": rec.get("node_type"),
            "request_features": rec.get("request_features"),
            "pre_action_state": rec.get("pre_action_state"),
            "RTG_t": rtg,
            "workflow_valid": lab["workflow_valid"],
            "scoring_layer": lab["scoring_layer"],
            "Q_final_N4": lab["Q_final"],
        })
    OUT_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rtg_rows) + "\n", encoding="utf-8")
    summary = {
        "version": "E4.1-phase-C-RTG-v1",
        "n_rows": len(rtg_rows),
        "expected": 640,
        "n_real_rtg": n_real,
        "n_zero_rtg": n_zero,
        "n_missing_rtg": n_missing,
        "rule": "RTG_t = Q_final(N4) for N1-N4; missing (judge failure) carried as None; delivery failure as 0.0",
        "propagation_complete": len(rtg_rows) == 640,
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
